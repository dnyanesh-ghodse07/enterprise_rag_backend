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
  __abstract__ = True # will not create a table for this class, but can be inherited by other models

  id: Mapped[UUID] = mapped_column(
    primary_key=True,
    default=uuid7,
  )