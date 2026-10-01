"""Search result schemas for the vector store."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class SearchResult:
    """A single search result from vector search."""
    chunk_id: str
    document_id: str
    tenant_id: str
    content: str
    score: float  # Similarity score (0.0 to 1.0)
    chunk_index: int = 0
    page_number: int | None = None
    section_heading: str | None = None
    document_title: str | None = None
    version: int = 1
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResults:
    """Collection of search results with query metadata."""
    results: list[SearchResult]
    query: str
    total_found: int
    search_time_ms: float = 0.0
