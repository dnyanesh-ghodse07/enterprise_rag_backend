"""
Document request and response schemas.

SCHEMA CATEGORIES:
- *Create: Input for creating a resource
- *Update: Input for updating a resource
- *Response: Output returned to the client
- *InDB: Internal representation (never returned to client)
"""

from app.core import storage
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Response after successful document upload."""

    id: UUID
    title: str
    filename: str
    mime_type: str
    file_size: int
    status: str
    current_version: int
    collection_id: UUID | None = None
    uploaded_by: UUID | None = None
    checksum: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    """Full document details returned in API responses."""

    id: UUID
    title: str
    filename: str
    description: str | None = None
    mime_type: str
    file_size: int
    status: str
    current_version: int
    collection_id: UUID | None = None
    collection_name: str | None = None
    uploaded_by: UUID | None = None
    uploader_name: str | None = None
    tenant_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    """Schema for updating document metadata (not the file itself)."""

    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    collection_id: UUID | None = None


class DocumentVersionResponse(BaseModel):
    """Response for a document version."""

    id: UUID
    document_id: UUID
    version_number: int
    file_size: int
    mime_type: str
    checksum: str
    uploaded_by: UUID | None = None
    change_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentDownloadResponse(BaseModel):
    """Response with download URL."""

    download_url: str
    filename: str
    mime_type: str
    file_size: int
    expires_in: int = Field(description="URL validity in seconds")


class DocumentStatsResponse(BaseModel):
    total: int
    storage: int
    count_by_status: dict[str, int]
    count_by_collection: dict[str, int]