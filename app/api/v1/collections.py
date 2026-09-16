"""
Collection management API endpoints.

ENDPOINTS:
  POST   /api/v1/collections           → Create a collection
  GET    /api/v1/collections           → List collections
  GET    /api/v1/collections/{id}      → Get collection details
  PATCH  /api/v1/collections/{id}      → Update collection
  DELETE /api/v1/collections/{id}      → Delete collection
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EditorUser
from app.core.database import get_session
from app.schemas.auth import MessageResponse
from app.schemas.collection import (
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
)
from app.services.collection_service import CollectionService

router = APIRouter()


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a collection",
)
async def create_collection(
    data: CollectionCreate,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    """Create a new collection for organizing documents."""
    service = CollectionService(db)
    return await service.create_collection(data, user)


@router.get(
    "",
    response_model=CollectionListResponse,
    summary="List collections",
)
async def list_collections(
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> CollectionListResponse:
    """List all collections for the current tenant."""
    service = CollectionService(db)
    return await service.list_collections(user.tenant_id)


@router.get(
    "/{collection_id}",
    response_model=CollectionResponse,
    summary="Get collection details",
)
async def get_collection(
    collection_id: UUID,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    """Get detailed information about a collection."""
    service = CollectionService(db)
    return await service.get_collection(collection_id, user.tenant_id)


@router.patch(
    "/{collection_id}",
    response_model=CollectionResponse,
    summary="Update a collection",
)
async def update_collection(
    collection_id: UUID,
    data: CollectionUpdate,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    """Update a collection's name or description."""
    service = CollectionService(db)
    return await service.update_collection(collection_id, user.tenant_id, data)


@router.delete(
    "/{collection_id}",
    response_model=MessageResponse,
    summary="Delete a collection",
)
async def delete_collection(
    collection_id: UUID,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Delete a collection. Documents in it become uncategorized."""
    service = CollectionService(db)
    await service.delete_collection(collection_id, user.tenant_id)
    return MessageResponse(message="Collection deleted successfully")
