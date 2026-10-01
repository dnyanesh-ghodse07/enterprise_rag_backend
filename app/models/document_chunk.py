"""
Document chunk model — stores extracted and chunked text.

WHAT A CHUNK REPRESENTS:
A chunk is a self-contained piece of text from a document,
sized for embedding and retrieval. Each chunk:
- Is 300-700 tokens (target: 500)
- Overlaps with neighbors by ~50 tokens
- Carries metadata for citation
- Will be embedded into a vector (Day 5)

LIFECYCLE:
1. Document uploaded (Day 3)
2. Text extracted and chunked (TODAY)
3. Chunks embedded into vectors (Day 5)
4. Vectors stored in Qdrant (Day 5)
5. User asks a question → Qdrant finds relevant chunks
6. Chunks are sent to LLM as context → LLM answers

THE CHUNK IS THE ATOMIC UNIT OF KNOWLEDGE IN OUR SYSTEM.
"""

from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class DocumentChunk(BaseModel):
    """
    A chunk of extracted text from a document.
    
    This is what gets embedded and searched.
    Think of it as one "flashcard" of knowledge.
    """
    __tablename__ = "document_chunks"
    
    # ─── Parent Document ──────────────────────────────────────
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Source document",
    )
    
    # ─── Tenant (denormalized for RLS) ────────────────────────
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant for row-level security",
    )
    
    # ─── Chunk Content ────────────────────────────────────────
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Position in document (0-indexed)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The actual chunk text",
    )
    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of tokens in this chunk",
    )
    
    # ─── Source Location ──────────────────────────────────────
    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Page number (for PDFs)",
    )
    section_heading: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Section heading this chunk belongs to",
    )
    
    # ─── Version Tracking ─────────────────────────────────────
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Document version this chunk was created from",
    )
    
    # ─── Integrity ────────────────────────────────────────────
    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 of chunk content (for dedup/cache)",
    )
    
    # ─── Flexible Metadata ────────────────────────────────────
    doc_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
        comment="Format-specific metadata",
    )
    # Example metadata for PDF:
    # {
    #   "page_range": "7-8",
    #   "heading_path": ["Chapter 3", "Revenue Analysis"],
    #   "has_table": true,
    #   "extraction_method": "pymupdf"
    # }
    
    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Chunk(doc={self.document_id}, idx={self.chunk_index}, '{preview}')>"
