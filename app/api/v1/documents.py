"""
Document management API endpoints.

ENDPOINTS:
  POST   /api/v1/documents/upload         → Upload a new document
  GET    /api/v1/documents                 → List documents
  GET    /api/v1/documents/{id}            → Get document details
  PATCH  /api/v1/documents/{id}            → Update metadata
  DELETE /api/v1/documents/{id}            → Delete (soft)
  POST   /api/v1/documents/{id}/versions   → Upload new version
  GET    /api/v1/documents/{id}/versions   → List versions
  GET    /api/v1/documents/{id}/download   → Get download URL
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EditorUser
from app.core.database import get_session
from app.models.document import DocumentStatus
from app.schemas.auth import MessageResponse
from app.schemas.document import (
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentUploadResponse,
    DocumentVersionResponse,
)
from app.services.document_service import DocumentService

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new document",
    description="Upload a file with metadata. Supports PDF, DOCX, TXT, MD, CSV, and more.",
)
async def upload_document(
    file: UploadFile = File(..., description="The file to upload"),
    title: str | None = Form(None, description="Document title (defaults to filename)"),
    description: str | None = Form(None, description="Document description"),
    collection_id: UUID | None = Form(None, description="Collection to add to"),
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentUploadResponse:
    """
    Upload a new document.

    REQUIRES: Editor or Admin role.

    The file is:
    1. Validated (size, type, content)
    2. Stored in the configured storage backend
    3. Metadata saved in PostgreSQL
    4. Version 1 created

    ACCEPTS: multipart/form-data
    MAX SIZE: 50MB (configurable)
    """
    # Read file content
    content = await file.read()

    service = DocumentService(db)
    return await service.upload_document(
        file_content=content,
        filename=file.filename or "unnamed",
        content_type=file.content_type,
        user=user,
        title=title,
        description=description,
        collection_id=collection_id,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="List documents with pagination and optional filtering.",
)
async def list_documents(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    collection_id: UUID | None = Query(None, description="Filter by collection"),
    status_filter: DocumentStatus | None = Query(
        None, alias="status", description="Filter by status"
    ),
    search: str | None = Query(
        None, min_length=1, max_length=200, description="Search in title/filename"
    ),
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    """List documents for the current user's tenant."""
    service = DocumentService(db)
    return await service.list_documents(
        tenant_id=user.tenant_id,
        page=page,
        page_size=page_size,
        collection_id=collection_id,
        status=status_filter,
        search=search,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
)
async def get_document(
    document_id: UUID,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    """Get detailed information about a document."""
    service = DocumentService(db)
    return await service.get_document(document_id, user.tenant_id)


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Update document metadata",
)
async def update_document(
    document_id: UUID,
    data: DocumentUpdate,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    """Update a document's title, description, or collection."""
    service = DocumentService(db)
    return await service.update_document(document_id, user.tenant_id, data)


@router.delete(
    "/{document_id}",
    response_model=MessageResponse,
    summary="Delete a document",
)
async def delete_document(
    document_id: UUID,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Soft-delete a document. The file is preserved in storage."""
    service = DocumentService(db)
    await service.delete_document(document_id, user.tenant_id)
    return MessageResponse(message="Document deleted successfully")


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new version",
)
async def upload_new_version(
    document_id: UUID,
    file: UploadFile = File(..., description="The updated file"),
    change_note: str | None = Form(None, description="Description of changes"),
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentVersionResponse:
    """Upload a new version of an existing document."""
    content = await file.read()

    service = DocumentService(db)
    return await service.upload_new_version(
        document_id=document_id,
        file_content=content,
        filename=file.filename or "unnamed",
        content_type=file.content_type,
        user=user,
        change_note=change_note,
    )


@router.get(
    "/{document_id}/versions",
    response_model=list[DocumentVersionResponse],
    summary="List document versions",
)
async def list_versions(
    document_id: UUID,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> list[DocumentVersionResponse]:
    """Get version history for a document."""
    service = DocumentService(db)
    return await service.get_versions(document_id, user.tenant_id)


@router.get(
    "/{document_id}/download",
    response_model=DocumentDownloadResponse,
    summary="Get download URL",
)
async def get_download_url(
    document_id: UUID,
    version: int | None = Query(None, description="Specific version to download"),
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> DocumentDownloadResponse:
    """Generate a temporary download URL for a document."""
    service = DocumentService(db)
    return await service.get_download_url(
        document_id,
        user.tenant_id,
        version=version,
    )
