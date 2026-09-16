"""Collection request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    """Schema for creating a new collection."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Collection name",
        examples=["Engineering Docs"],
    )
    description: str | None = Field(
        None,
        max_length=2000,
        description="Optional description",
        examples=["All engineering documentation and specs"],
    )


class CollectionUpdate(BaseModel):
    """Schema for updating a collection."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class CollectionResponse(BaseModel):
    """Collection details returned in API responses."""

    id: UUID
    name: str
    description: str | None = None
    tenant_id: UUID
    created_by: UUID | None = None
    document_count: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CollectionListResponse(BaseModel):
    """Paginated list of collections."""

    items: list[CollectionResponse]
    total: int
