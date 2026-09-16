"""Collection management service."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.collection import Collection
from app.models.document import Document
from app.models.user import User
from app.schemas.collection import (
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
)


class CollectionService:
    """Business logic for collection operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_collection(
        self,
        data: CollectionCreate,
        user: User,
    ) -> CollectionResponse:
        """Create a new collection within the user's tenant."""
        # Check for duplicate name within tenant
        result = await self.db.execute(
            select(Collection).where(
                Collection.name == data.name,
                Collection.tenant_id == user.tenant_id,
                Collection.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none():
            raise ValidationError(
                message=f"A collection named '{data.name}' already exists",
                details={"field": "name"},
            )

        collection = Collection(
            name=data.name,
            description=data.description,
            tenant_id=user.tenant_id,
            created_by=user.id,
        )
        self.db.add(collection)
        await self.db.commit()
        await self.db.refresh(collection)

        return CollectionResponse(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            tenant_id=collection.tenant_id,
            created_by=collection.created_by,
            document_count=0,
            is_active=collection.is_active,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
        )

    async def list_collections(
        self,
        tenant_id: UUID,
    ) -> CollectionListResponse:
        """List all active collections for a tenant."""
        # Get collections with document count
        result = await self.db.execute(
            select(Collection)
            .where(
                Collection.tenant_id == tenant_id,
                Collection.is_active == True,  # noqa: E712
            )
            .order_by(Collection.name)
        )
        collections = result.scalars().all()

        items = []
        for coll in collections:
            # Count documents in this collection
            count_result = await self.db.execute(
                select(func.count()).where(
                    Document.collection_id == coll.id,
                    Document.is_active == True,  # noqa: E712
                )
            )
            doc_count = count_result.scalar() or 0

            items.append(
                CollectionResponse(
                    id=coll.id,
                    name=coll.name,
                    description=coll.description,
                    tenant_id=coll.tenant_id,
                    created_by=coll.created_by,
                    document_count=doc_count,
                    is_active=coll.is_active,
                    created_at=coll.created_at,
                    updated_at=coll.updated_at,
                )
            )

        return CollectionListResponse(items=items, total=len(items))

    async def get_collection(
        self,
        collection_id: UUID,
        tenant_id: UUID,
    ) -> CollectionResponse:
        """Get a single collection by ID."""
        result = await self.db.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.tenant_id == tenant_id,
                Collection.is_active == True,  # noqa: E712
            )
        )
        coll = result.scalar_one_or_none()

        if not coll:
            raise NotFoundError(
                message="Collection not found",
                resource_type="Collection",
                resource_id=str(collection_id),
            )

        # Count documents
        count_result = await self.db.execute(
            select(func.count()).where(
                Document.collection_id == coll.id,
                Document.is_active == True,  # noqa: E712
            )
        )
        doc_count = count_result.scalar() or 0

        return CollectionResponse(
            id=coll.id,
            name=coll.name,
            description=coll.description,
            tenant_id=coll.tenant_id,
            created_by=coll.created_by,
            document_count=doc_count,
            is_active=coll.is_active,
            created_at=coll.created_at,
            updated_at=coll.updated_at,
        )

    async def update_collection(
        self,
        collection_id: UUID,
        tenant_id: UUID,
        data: CollectionUpdate,
    ) -> CollectionResponse:
        """Update a collection's metadata."""
        result = await self.db.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.tenant_id == tenant_id,
                Collection.is_active == True,  # noqa: E712
            )
        )
        coll = result.scalar_one_or_none()

        if not coll:
            raise NotFoundError(
                message="Collection not found",
                resource_type="Collection",
                resource_id=str(collection_id),
            )

        if data.name is not None:
            coll.name = data.name
        if data.description is not None:
            coll.description = data.description

        await self.db.commit()
        return await self.get_collection(collection_id, tenant_id)

    async def delete_collection(
        self,
        collection_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """
        Soft-delete a collection.

        Documents in this collection are NOT deleted.
        Their collection_id is set to NULL (moved to uncategorized).
        """
        result = await self.db.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.tenant_id == tenant_id,
                Collection.is_active == True,  # noqa: E712
            )
        )
        coll = result.scalar_one_or_none()

        if not coll:
            raise NotFoundError(
                message="Collection not found",
                resource_type="Collection",
                resource_id=str(collection_id),
            )

        # Move documents to uncategorized
        doc_result = await self.db.execute(
            select(Document).where(Document.collection_id == collection_id)
        )
        for doc in doc_result.scalars().all():
            doc.collection_id = None

        coll.is_active = False
        await self.db.commit()
