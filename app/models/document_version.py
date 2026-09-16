"""
Document version model — tracks every version of a document.

VERSIONING STRATEGY:
- Each upload creates a new version
- Each version has its own storage_key (separate file in storage)
- The document's current_version points to the latest
- Old versions are never deleted (audit trail)
- Can restore by creating a new version from an old one

VERSION NUMBERING:
  v1 → Initial upload
  v2 → Re-upload (updated content)
  v3 → Another update
  ...

  document.current_version = 3  (the latest)
"""

from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class DocumentVersion(BaseModel):
    """
    Represents a specific version of a document.

    EACH VERSION HAS:
    - Its own file in storage (different storage_key)
    - Its own file size and checksum
    - A reference to who uploaded it
    - An optional change note ("Fixed revenue calculations")
    """

    __tablename__ = "document_versions"

    # ─── Parent Document ──────────────────────────────────────
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The document this version belongs to",
    )

    # ─── Version Info ─────────────────────────────────────────
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential version number (1, 2, 3, ...)",
    )

    # ─── File Properties ─────────────────────────────────────
    storage_key: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="Storage key for this version's file",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Size of this version's file in bytes",
    )
    mime_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="MIME type of this version",
    )
    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of this version's content",
    )

    # ─── Metadata ─────────────────────────────────────────────
    uploaded_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who uploaded this version",
    )
    change_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional note describing changes in this version",
    )

    # ─── Relationships ────────────────────────────────────────
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="versions",
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentVersion(id={self.id}, doc={self.document_id}, "
            f"v{self.version_number})>"
        )
