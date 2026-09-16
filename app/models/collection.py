"""
Collection model — folders for organizing documents.

COLLECTIONS ARE LIKE FOLDERS:
- A collection belongs to a tenant
- A collection has many documents
- A document optionally belongs to one collection
- Collections are flat (no nested folders — keeps it simple)

WHY FLAT (no nesting):
- Nested folders are a UI/UX nightmare at scale
- "Where did I put that file?" → infinite levels to search
- Flat structure + search is more effective (Gmail approach)
- Can add nesting later if needed (parent_id foreign key)
"""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Collection(BaseModel):
    """
    A collection (folder) for organizing documents within a tenant.
    """

    __tablename__ = "collections"

    # ─── Core Fields ──────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Collection display name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional description of this collection",
    )

    # ─── Tenant & Ownership ──────────────────────────────────
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The tenant this collection belongs to",
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="The user who created this collection",
    )

    # ─── Status ───────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="False = soft-deleted",
    )

    # ─── Relationships ────────────────────────────────────────
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="collection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Collection(id={self.id}, name='{self.name}')>"
