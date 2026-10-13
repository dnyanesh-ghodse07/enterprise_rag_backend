"""Chat API request and response schemas."""

from uuid import UUID
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Schema for chat messages."""
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The question to ask",
        examples=["What was Q4 revenue?"],
    )
    conversation_id: UUID | None = Field(
        default=None,
        description="Continue an existing conversation (omit for new)",
    )
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Restrict search to specific documents",
    )
    stream: bool = Field(
        default=False,
        description="Stream the response token-by-token",
    )


class SourceReference(BaseModel):
    """A source reference in a chat response."""
    index: int
    document_id: str
    document_title: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    relevance_score: float


class ChatMetadata(BaseModel):
    """Metadata about the chat response."""
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_estimate: float
    search_time_ms: float
    total_time_ms: float
    chunks_retrieved: int


class ChatResponse(BaseModel):
    """Complete chat response."""
    answer: str
    conversation_id: str
    sources: list[SourceReference]
    metadata: ChatMetadata


class ConversationListItem(BaseModel):
    """A conversation in the list view."""
    id: str
    title: str
    message_count: int
    created_at: str | None = None
    updated_at: str | None = None
