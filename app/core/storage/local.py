"""
Local filesystem storage backend.

USE FOR: Development and testing ONLY.
DO NOT USE IN PRODUCTION — local disk is:
  - Not replicated (disk failure = data loss)
  - Not scalable (limited by single disk size)
  - Not accessible from multiple servers
  - No built-in backup

PRODUCTION: Use S3Storage (or equivalent cloud storage)
"""

import os
import aiofiles
from pathlib import Path

from app.core.storage.base import StorageBackend
from app.config import get_settings

settings = get_settings()


class LocalStorage(StorageBackend):
    """
    Local filesystem storage implementation.

    Stores files under a configurable root directory.
    Default: ./uploads/

    Directory structure mirrors the storage key:
      key:  "tenants/acme/documents/abc/v1/file.pdf"
      path: ./uploads/tenants/acme/documents/abc/v1/file.pdf
    """

    def __init__(self, root_path: str | None = None):
        """
        Initialize local storage.

        Args:
            root_path: Base directory for file storage.
                      Defaults to settings.storage_local_path
        """
        self.root = Path(root_path or settings.storage_local_path).resolve()
        # Create root directory if it doesn't exist
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        """
        Convert a storage key to an absolute filesystem path.

        SECURITY: Validates that the resolved path is under root_path.
        This prevents path traversal attacks:
          key = "../../etc/passwd"
          resolved = /uploads/../../etc/passwd = /etc/passwd
          → NOT under /uploads/ → REJECTED!
        """
        path = (self.root / key).resolve()

        # Security check: ensure path is under root
        if not str(path).startswith(str(self.root)):
            raise ValueError(f"Invalid storage key: path traversal detected in '{key}'")

        return path

    async def save(self, key: str, content: bytes) -> str:
        """
        Save file to local filesystem.

        Creates parent directories automatically.
        Uses aiofiles for async file I/O (doesn't block the event loop).
        """
        path = self._resolve_path(key)

        # Create parent directories
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write file asynchronously
        async with aiofiles.open(path, "wb") as f:
            if isinstance(content, bytes):
                await f.write(content)
            else:
                # Handle file-like objects
                while chunk := content.read(8192):
                    await f.write(chunk)

        return key

    async def get(self, key: str) -> bytes:
        """Read file content from local filesystem."""
        path = self._resolve_path(key)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {key}")

        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        """
        Delete a file from local filesystem.

        Idempotent: no error if file doesn't exist.
        Also removes empty parent directories (cleanup).
        """
        path = self._resolve_path(key)

        if path.exists():
            path.unlink()

            # Clean up empty parent directories
            parent = path.parent
            while parent != self.root:
                try:
                    parent.rmdir()  # Only removes if empty
                    parent = parent.parent
                except OSError:
                    break  # Directory not empty, stop

    async def exists(self, key: str) -> bool:
        """Check if a file exists in local storage."""
        path = self._resolve_path(key)
        return path.exists()

    async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Generate a download URL for local storage.

        For local dev, this returns an API path that serves the file.
        In production (S3), this would return a presigned URL.

        Note: expires_in is ignored for local storage.
        """
        # Return a path relative to the API that can serve the file
        return f"/api/v1/documents/files/{key}"

    async def get_size(self, key: str) -> int:
        """Get file size from local filesystem."""
        path = self._resolve_path(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {key}")
        return path.stat().st_size
