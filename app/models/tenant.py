from uuid import UUID

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

class Tenant(BaseModel):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(
      String(length=255),
      nullable=False,
      comment="Display name of the Organization",
    )
    slug: Mapped[str] = mapped_column(
      String(length=255),
      unique=True,
      nullable=False,
      index=True,
      comment="URL-friendly identifier (e.g., 'acme-corp')",
    )
    description: Mapped[str] = mapped_column(
      Text,
      nullable=True,
      comment="Brief description of the Organization",
    )
    # Status and Configuration
    is_active: Mapped[bool] = mapped_column(
      Boolean,
      default=True,
      nullable=False,
      comment="Indicates if the Organization is active",
    )
    settings: Mapped[dict] = mapped_column(
      JSONB,
      default=dict,
      server_default="{}",
      nullable=False,
      comment="Per-tenant configuration (LLM model, limits, etc.)",
    )
    # Relationships
    users: Mapped[list["User"]] = relationship(
      "User",
      back_populates="tenant",
      cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name}, slug={self.slug})>"