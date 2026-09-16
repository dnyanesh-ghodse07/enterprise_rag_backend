"""Storage package exports."""

from app.core.storage.base import StorageBackend
from app.core.storage.factory import get_storage

__all__ = ["StorageBackend", "get_storage"]
