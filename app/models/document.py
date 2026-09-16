"""
Document model — represents an uploaded file's metadata.

THE DOCUMENT VS. THE FILE:
- The DOCUMENT is the metadata in PostgreSQL
  (name, owner, tenant, status, version count)
- The FILE is the actual bytes in storage
  (the PDF content, the Word document bytes)

WHY SEPARATE:
- We can search metadata without reading files (fast)
- We can move files between storage backends
- We can have multiple versions of the same document
- Database backup doesn't include multi-GB file content
- Files are immutable, metadata changes (rename, move to collection)
"""

import enum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class DocumentStatus(str, enum.Enum):
    """
    Processing status of a document.

    LIFECYCLE:
    uploaded → processing → ready
                          → error (if processing fails)

    WHY A STATUS:
    When a document is uploaded, it needs to be:
    1. Stored (storage)
    2. Text extracted (Day 4)
    3. Chunked (Day 4)
    4. Embedded (Day 5)
    5. Indexed in Qdrant (Day 5)

    Steps 2-5 happen asynchronously. The status tracks progress.
    The frontend shows a spinner until status = "ready".
    """

    UPLOADED = "uploaded"  # File saved, not yet processed
    PROCESSING = "processing"  # Text extraction / embedding in progress
    READY = "ready"  # Fully processed, searchable
    ERROR = "error"  # Processing failed
    ARCHIVED = "archived"  # Soft-deleted / hidden


class Document(BaseModel):
    """
    Represents an uploaded document's metadata.

    DESIGN DECISIONS:
    - title: User-facing name (can be different from filename)
    - filename: Original upload name (preserved for downloads)
    - storage_key: Internal path in storage (NOT a URL)
    - current_version: Denormalized for fast access
      → Avoids MAX(version_num) query on every document load
      → Updated atomically when a new version is uploaded
    - file_size: Stored for quota enforcement and UI display
    - checksum: SHA-256 for deduplication and integrity
    """

    __tablename__ = "documents"

    # ----- Core Fields ------
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="User-facing document title",
    )
    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Original uploaded filename",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional document description",
    )

    # file properties
    mime_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="MIME type (e.g., application/pdf)",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="File size in bytes",
    )
    storage_key: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="Key/path in storage backend",
    )
    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of file content",
    )

    # ─── Versioning ───────────────────────────────────────────
    current_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="Current (latest) version number",
    )

    # ─── Status ───────────────────────────────────────────────
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda enum_class: [e.value for e in enum_class],
            create_constraint=True,
        ),
        default=DocumentStatus.UPLOADED,
        server_default=DocumentStatus.UPLOADED.value,
        nullable=False,
        comment="Processing status (uploaded → processing → ready)",
    )

    # ─── Tenant & Ownership ──────────────────────────────────
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The tenant this document belongs to",
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,  # SET NULL if user is deleted
        index=True,
        comment="The user who uploaded this document",
    )

    # ─── Collection ───────────────────────────────────────────
    collection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional collection this document belongs to",
    )

    # ─── Soft Delete ──────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="False = soft-deleted (hidden but preserved)",
    )

    # ─── Relationships ────────────────────────────────────────
    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number.desc()",
    )

    collection: Mapped["Collection | None"] = relationship(
        "Collection",
        back_populates="documents",
        lazy="selectin",
    )

    uploader: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[uploaded_by],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, title='{self.title}', "
            f"status={self.status.value}, v{self.current_version})>"
        )
