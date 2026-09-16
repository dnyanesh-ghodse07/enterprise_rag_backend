from app.models.base import Base, BaseModel, TimestampMixin
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.refresh_token import RefreshToken
from app.models.collection import Collection
from app.models.document import Document, DocumentStatus
from app.models.document_version import DocumentVersion

# Backward-compatible alias for code paths still importing UserRoles
UserRoles = UserRole

__all__ = [
    "Base",
    "BaseModel",
    "TimestampMixin",
    "Tenant",
    "User",
    "UserRole",
    "UserRoles",
    "RefreshToken",
    "Collection",
    "Document",
    "DocumentStatus",
    "DocumentVersion",
]
