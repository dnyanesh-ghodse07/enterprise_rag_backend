"""Search API request and response schemas."""

from uuid import UUID
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Schema for search queries."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The search query or question",
        examples=["What was Q4 revenue?"],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results",
    )
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0.0-1.0)",
    )
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Optional: restrict search to specific documents",
    )
    search_mode: str = Field(
        default="semantic",
        description="Search mode: 'semantic', 'keyword', or 'hybrid'",
    )


class SearchResultItem(BaseModel):
    """A single search result."""
    chunk_id: str
    document_id: str
    content: str
    score: float
    chunk_index: int
    page_number: int | None = None
    section_heading: str | None = None
    document_title: str | None = None
    version: int = 1
    token_count: int = 0


class SearchResponse(BaseModel):
    """Search results response."""
    results: list[SearchResultItem]
    query: str
    total_found: int
    search_time_ms: float
    search_mode: str


class EmbedDocumentRequest(BaseModel):
    """Request to embed a document's chunks."""
    document_id: UUID = Field(..., description="Document to embed")
