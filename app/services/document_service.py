"""
Document management service — core business logic.

RESPONSIBILITIES:
- Upload files (validate → store → save metadata)
- List documents (with pagination, filtering)
- Get document details
- Update document metadata
- Upload new version
- Delete documents (soft-delete)
- Generate download URLs

TENANT ISOLATION:
Every query includes tenant_id filtering.
A user from Tenant A can NEVER access Tenant B's documents.
This is enforced at:
1. This service layer (application code)
2. Database RLS (database level, Day 2)
"""

import math
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.file_validator import (
    FileValidator,
    FileValidationError,
    EXTENSION_TO_MIME,
)
from app.core.storage import StorageBackend, get_storage
from app.models.collection import Collection
from app.models.document import Document, DocumentStatus
from app.models.document_version import DocumentVersion
from app.models.user import User
from app.schemas.document import (
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentUploadResponse,
    DocumentVersionResponse,
)


class DocumentService:
    """
    Document management service.

    DESIGN:
    - Receives database session and storage backend via constructor
    - All operations are tenant-scoped (user's tenant_id)
    - File validation happens before storage (fail fast)
    - Metadata and file storage are coordinated (all-or-nothing)
    """

    def __init__(self, db: AsyncSession, storage: StorageBackend | None = None):
        self.db = db
        self.storage = storage or get_storage()
        self.validator = FileValidator()

    async def upload_document(
        self,
        file_content: bytes,
        filename: str,
        content_type: str | None,
        user: User,
        title: str | None = None,
        description: str | None = None,
        collection_id: UUID | None = None,
    ) -> DocumentUploadResponse:
        """
        Upload a new document.

        FLOW:
        1. Validate file (size, extension, content type, magic bytes)
        2. Sanitize filename
        3. Compute checksum (SHA-256)
        4. Check for duplicate (same checksum in same tenant)
        5. Generate storage key
        6. Save file to storage
        7. Create document record in database
        8. Create version 1 record
        9. Commit transaction

        If ANY step fails, nothing is saved.
        File is cleaned up from storage if DB commit fails.
        """
        # ─── Step 1: Validate ────────────────────────────────
        try:
            self.validator.validate_size(len(file_content))
            ext = self.validator.validate_extension(filename)
            self.validator.validate_content_type(filename, content_type)
        except FileValidationError as e:
            raise ValidationError(message=e.message, details={"field": e.field})

        # ─── Step 2: Sanitize filename ───────────────────────
        safe_filename = self.validator.sanitize_filename(filename)

        # ─── Step 3: Compute checksum ────────────────────────
        checksum = self.validator.compute_checksum(file_content)

        # ─── Step 4: Determine MIME type ─────────────────────
        mime_type = content_type or EXTENSION_TO_MIME.get(
            ext, "application/octet-stream"
        )
        # Normalize MIME type (remove charset and other params)
        mime_type = mime_type.split(";")[0].strip()

        # ─── Step 5: Validate collection belongs to tenant ────
        if collection_id:
            result = await self.db.execute(
                select(Collection).where(
                    Collection.id == collection_id,
                    Collection.tenant_id == user.tenant_id,
                    Collection.is_active == True,  # noqa: E712
                )
            )
            if not result.scalar_one_or_none():
                raise ValidationError(
                    message="Collection not found or doesn't belong to your organization",
                    details={"field": "collection_id"},
                )

        # ─── Step 6: Create document ─────────────────────────
        document = Document(
            title=title or safe_filename,
            filename=safe_filename,
            description=description,
            mime_type=mime_type,
            file_size=len(file_content),
            storage_key="",  # Will be set after we know the document ID
            checksum=checksum,
            current_version=1,
            status=DocumentStatus.UPLOADED,
            tenant_id=user.tenant_id,
            uploaded_by=user.id,
            collection_id=collection_id,
        )
        self.db.add(document)
        await self.db.flush()  # Get document.id

        # ─── Step 7: Generate storage key ─────────────────────
        storage_key = self.storage.generate_key(
            tenant_id=str(user.tenant_id),
            document_id=str(document.id),
            version=1,
            filename=safe_filename,
        )
        document.storage_key = storage_key

        # ─── Step 8: Save file to storage ─────────────────────
        try:
            await self.storage.save(storage_key, file_content)
        except Exception as e:
            # If storage fails, rollback everything
            await self.db.rollback()
            raise ValidationError(
                message=f"Failed to store file: {str(e)}",
                details={"field": "file"},
            )

        # ─── Step 9: Create version record ────────────────────
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            storage_key=storage_key,
            file_size=len(file_content),
            mime_type=mime_type,
            checksum=checksum,
            uploaded_by=user.id,
            change_note="Initial upload",
        )
        self.db.add(version)

        # ─── Step 10: Commit ──────────────────────────────────
        try:
            await self.db.commit()
        except Exception:
            # If DB commit fails, clean up the stored file
            await self.storage.delete(storage_key)
            raise

        await self.db.refresh(document)

        return DocumentUploadResponse(
            id=document.id,
            title=document.title,
            filename=document.filename,
            mime_type=document.mime_type,
            file_size=document.file_size,
            status=document.status.value,
            current_version=document.current_version,
            collection_id=document.collection_id,
            uploaded_by=document.uploaded_by,
            checksum=document.checksum,
            created_at=document.created_at,
        )

    async def list_documents(
        self,
        tenant_id: UUID,
        page: int = 1,
        page_size: int = 20,
        collection_id: UUID | None = None,
        status: DocumentStatus | None = None,
        search: str | None = None,
    ) -> DocumentListResponse:
        """
        List documents for a tenant with pagination and filtering.

        PAGINATION:
        - page: 1-indexed page number
        - page_size: items per page (max 100)
        - Returns total count for UI pagination controls

        FILTERING:
        - collection_id: filter by collection
        - status: filter by processing status
        - search: search in title and filename (ILIKE)
        """
        page_size = min(page_size, 100)  # Cap page size

        # Build query
        query = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.is_active == True,  # noqa: E712
        )

        if collection_id:
            query = query.where(Document.collection_id == collection_id)
        if status:
            query = query.where(Document.status == status)
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                Document.title.ilike(search_pattern)
                | Document.filename.ilike(search_pattern)
            )

        # Count total matching documents
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination
        offset = (page - 1) * page_size
        query = (
            query.order_by(Document.created_at.desc()).offset(offset).limit(page_size)
        )

        result = await self.db.execute(query)
        documents = result.scalars().all()

        # Build response
        items = []
        for doc in documents:
            items.append(
                DocumentResponse(
                    id=doc.id,
                    title=doc.title,
                    filename=doc.filename,
                    description=doc.description,
                    mime_type=doc.mime_type,
                    file_size=doc.file_size,
                    status=doc.status.value,
                    current_version=doc.current_version,
                    collection_id=doc.collection_id,
                    collection_name=doc.collection.name if doc.collection else None,
                    uploaded_by=doc.uploaded_by,
                    uploader_name=doc.uploader.full_name if doc.uploader else None,
                    tenant_id=doc.tenant_id,
                    is_active=doc.is_active,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                )
            )

        return DocumentListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total > 0 else 0,
        )

    async def get_document(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> DocumentResponse:
        """Get a single document by ID (tenant-scoped)."""
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={"document_id": str(document_id), "tenant_id": str(tenant_id)},
            )

        return DocumentResponse(
            id=doc.id,
            title=doc.title,
            filename=doc.filename,
            description=doc.description,
            mime_type=doc.mime_type,
            file_size=doc.file_size,
            status=doc.status.value,
            current_version=doc.current_version,
            collection_id=doc.collection_id,
            collection_name=doc.collection.name if doc.collection else None,
            uploaded_by=doc.uploaded_by,
            uploader_name=doc.uploader.full_name if doc.uploader else None,
            tenant_id=doc.tenant_id,
            is_active=doc.is_active,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    async def update_document(
        self,
        document_id: UUID,
        tenant_id: UUID,
        data: DocumentUpdate,
    ) -> DocumentResponse:
        """Update document metadata (title, description, collection)."""
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={document_id: str(document_id), tenant_id: str(tenant_id)},
            )

        # Apply updates (only non-None fields)
        if data.title is not None:
            doc.title = data.title
        if data.description is not None:
            doc.description = data.description
        if data.collection_id is not None:
            # Validate collection belongs to tenant
            coll_result = await self.db.execute(
                select(Collection).where(
                    Collection.id == data.collection_id,
                    Collection.tenant_id == tenant_id,
                )
            )
            if not coll_result.scalar_one_or_none():
                raise ValidationError(
                    message="Collection not found",
                    details={"field": "collection_id"},
                )
            doc.collection_id = data.collection_id

        await self.db.commit()
        await self.db.refresh(doc)

        return await self.get_document(document_id, tenant_id)

    async def upload_new_version(
        self,
        document_id: UUID,
        file_content: bytes,
        filename: str,
        content_type: str | None,
        user: User,
        change_note: str | None = None,
    ) -> DocumentVersionResponse:
        """
        Upload a new version of an existing document.

        FLOW:
        1. Find the existing document (tenant-scoped)
        2. Validate the new file
        3. Increment version number
        4. Store the new file with new version key
        5. Create new version record
        6. Update document's current_version and storage_key
        7. Commit

        The old version's file is NOT deleted — it stays in storage
        for the version history.
        """
        # Find existing document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == user.tenant_id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={document_id: str(document_id)},
            )

        # Validate new file
        try:
            self.validator.validate_size(len(file_content))
            ext = self.validator.validate_extension(filename)
            self.validator.validate_content_type(filename, content_type)
        except FileValidationError as e:
            raise ValidationError(message=e.message, details={"field": e.field})

        safe_filename = self.validator.sanitize_filename(filename)
        checksum = self.validator.compute_checksum(file_content)
        mime_type = (
            (content_type or EXTENSION_TO_MIME.get(ext, "application/octet-stream"))
            .split(";")[0]
            .strip()
        )

        # Increment version
        new_version_num = doc.current_version + 1

        # Generate new storage key
        storage_key = self.storage.generate_key(
            tenant_id=str(user.tenant_id),
            document_id=str(document_id),
            version=new_version_num,
            filename=safe_filename,
        )

        # Store new file
        try:
            await self.storage.save(storage_key, file_content)
        except Exception as e:
            raise ValidationError(
                message=f"Failed to store file: {str(e)}",
                details={"field": "file"},
            )

        # Create version record
        version = DocumentVersion(
            document_id=document_id,
            version_number=new_version_num,
            storage_key=storage_key,
            file_size=len(file_content),
            mime_type=mime_type,
            checksum=checksum,
            uploaded_by=user.id,
            change_note=change_note,
        )
        self.db.add(version)

        # Update document metadata
        doc.current_version = new_version_num
        doc.storage_key = storage_key
        doc.file_size = len(file_content)
        doc.mime_type = mime_type
        doc.checksum = checksum
        doc.filename = safe_filename
        doc.status = DocumentStatus.UPLOADED  # Reset status for reprocessing

        try:
            await self.db.commit()
        except Exception:
            await self.storage.delete(storage_key)
            raise

        await self.db.refresh(version)

        return DocumentVersionResponse(
            id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            file_size=version.file_size,
            mime_type=version.mime_type,
            checksum=version.checksum,
            uploaded_by=version.uploaded_by,
            change_note=version.change_note,
            created_at=version.created_at,
        )

    async def get_versions(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[DocumentVersionResponse]:
        """Get all versions of a document."""
        # Verify document exists and belongs to tenant
        doc_result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if not doc_result.scalar_one_or_none():
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={document_id: str(document_id), tenant_id: str(tenant_id)},
            )

        result = await self.db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )
        versions = result.scalars().all()

        return [
            DocumentVersionResponse(
                id=v.id,
                document_id=v.document_id,
                version_number=v.version_number,
                file_size=v.file_size,
                mime_type=v.mime_type,
                checksum=v.checksum,
                uploaded_by=v.uploaded_by,
                change_note=v.change_note,
                created_at=v.created_at,
            )
            for v in versions
        ]

    async def get_download_url(
        self,
        document_id: UUID,
        tenant_id: UUID,
        version: int | None = None,
    ) -> DocumentDownloadResponse:
        """
        Generate a download URL for a document.

        If version is specified, downloads that specific version.
        Otherwise, downloads the latest version.
        """
        # Find document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={document_id: str(document_id), tenant_id: str(tenant_id)},
            )

        # Get the right version's storage key
        if version:
            ver_result = await self.db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_number == version,
                )
            )
            ver = ver_result.scalar_one_or_none()
            if not ver:
                raise NotFoundError(
                    resource=f"Version {version} not found",
                    identifier=str(document_id),
                    details={document_id: str(document_id), tenant_id: str(tenant_id)},
                )
            storage_key = ver.storage_key
            file_size = ver.file_size
            mime_type = ver.mime_type
        else:
            storage_key = doc.storage_key
            file_size = doc.file_size
            mime_type = doc.mime_type

        # Generate download URL
        expires_in = 3600  # 1 hour
        download_url = await self.storage.get_download_url(storage_key, expires_in)

        return DocumentDownloadResponse(
            download_url=download_url,
            filename=doc.filename,
            mime_type=mime_type,
            file_size=file_size,
            expires_in=expires_in,
        )

    async def delete_document(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """
        Soft-delete a document.

        WHY SOFT-DELETE:
        - Legal requirements (can't delete financial documents)
        - Undo capability for accidental deletion
        - Audit trail
        - Can purge later with a cleanup job

        The file stays in storage. Only the metadata flag changes.
        """
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise NotFoundError(
                resource="Document",
                identifier=str(document_id),
                details={
                    document_id: str(document_id),
                    tenant_id: str(tenant_id),
                },
            )

        doc.is_active = False
        doc.status = DocumentStatus.ARCHIVED
        await self.db.commit()
