import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class UserRole(str, enum.Enum):
  VIEWER = "viewer"
  EDITOR = "editor"
  ADMIN = "admin"

  @classmethod
  def has_permission(cls, user_role: "UserRole", required_role: "UserRole") -> bool:
    """
    Check if the given role has the specified permission.
    """
    hierarchy = {
      cls.VIEWER: 0,
      cls.EDITOR: 1,
      cls.ADMIN: 2,
    }
    return hierarchy[user_role] >= hierarchy[required_role]

class User(BaseModel):
  __tablename__ = "users"

  # Identity
  email: Mapped[str] = mapped_column(
    String(length=255),
    unique=True,
    nullable=False,
    index=True,
    comment="User's email address (used for login)",
  )
  hashed_password: Mapped[str] = mapped_column(
    String(length=255),
    nullable=False,
    comment="Hashed password for authentication",
  )
  full_name: Mapped[str] = mapped_column(
    String(length=255),
    nullable=False,
    comment="User's full name",
  )
  
  # Tenant relationship
  tenant_id: Mapped[UUID] = mapped_column(
    ForeignKey("tenants.id", ondelete="CASCADE"),
    nullable=False,
    index=True, #important we filter by tenant_id constantly
    comment="Foreign key to the Tenant the user belongs to",
  )

  # Role
  role: Mapped[UserRole] = mapped_column(
    Enum(UserRole, 
    name="user_role", 
    values_callable=lambda enum_class: [e.value for e in enum_class],
    ),
    default=UserRole.VIEWER,
    server_default=UserRole.VIEWER.value,
    nullable=False,
    comment="Role of the user (viewer, editor, admin)",
  )

  # Status
  is_active: Mapped[bool] = mapped_column(
    Boolean,
    default=True,
    server_default="true",
    nullable=False,
    comment="Indicates if the user account is active",
  )
  last_login: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
    comment="Timestamp of the user's last login",
  )

  # Relationships
  tenant: Mapped['Tenant'] = relationship(
    "Tenant",
    back_populates="users",
    lazy='selectin',
  )
  refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
    "RefreshToken",
    back_populates="user",
    cascade="all, delete-orphan",
  )

  @property
  def last_login_at(self) -> datetime | None:
      return self.last_login

  @last_login_at.setter
  def last_login_at(self, value: datetime | None) -> None:
      self.last_login = value

  def __repr__(self) -> str:
      return f"<User(id={self.id}, email={self.email}, role={self.role}, full_name={self.full_name}, last_login={self.last_login})>"
