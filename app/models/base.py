from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from uuid_extensions import uuid7
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    from uuid_v7 import uuid_v7 as uuid7


class Base(DeclarativeBase):

    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BaseModel(Base, TimestampMixin):
    __abstract__ = True  # will not create a table for this class, but can be inherited by other models

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid7,
    )


# Import all models so Alembic and metadata-based tooling register every table.
# This prevents "relation does not exist" errors when a table is defined in the
# ORM but never actually included in Base.metadata during migration setup.
from app.models.tenant import Tenant  # noqa: F401,E402
from app.models.user import User  # noqa: F401,E402
from app.models.refresh_token import RefreshToken  # noqa: F401,E402
from app.models.collection import Collection  # noqa: F401,E402
from app.models.document import Document  # noqa: F401,E402
from app.models.document_version import DocumentVersion  # noqa: F401,E402
