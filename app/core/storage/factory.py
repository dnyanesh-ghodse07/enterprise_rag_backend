"""
Storage backend factory.

THE FACTORY PATTERN:
Instead of:
    if config.storage == "local":
        storage = LocalStorage()
    elif config.storage == "s3":
        storage = S3Storage()

We use:
    storage = get_storage()  # Returns the right backend based on config

WHY A FACTORY:
- Single point of configuration
- Easy to add new backends
- Can be cached (singleton pattern)
- Tests can override it
"""

from functools import lru_cache

from app.config import get_settings
from app.core.storage.base import StorageBackend
from app.core.storage.local import LocalStorage

settings = get_settings()


@lru_cache()
def get_storage() -> StorageBackend:
    """
    Get the configured storage backend.

    Returns a cached singleton instance.
    The backend is determined by the STORAGE_BACKEND environment variable.

    Supported backends:
    - "local": Local filesystem (development)
    - "s3": AWS S3 (production, implemented later)
    """
    backend = settings.storage_backend.lower()

    if backend == "local":
        return LocalStorage()
    elif backend == "s3":
        # We'll implement S3Storage in Day 14 (Production Deployment)
        raise NotImplementedError(
            "S3 storage is not yet implemented. "
            "Set STORAGE_BACKEND=local for development."
        )
    else:
        raise ValueError(
            f"Unknown storage backend: '{backend}'. " f"Supported: 'local', 's3'"
        )
