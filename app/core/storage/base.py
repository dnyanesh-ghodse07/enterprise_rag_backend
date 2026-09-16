"""
Abstract base class for storage backends.

THIS IS THE STRATEGY PATTERN IN ACTION:
- Define an interface (StorageBackend)
- Implement it differently (LocalStorage, S3Storage)
- Choose the implementation at runtime (via config)
- Application code uses the interface, not the implementation

WHY AN ABSTRACT CLASS:
- Enforces that all backends have the same methods
- IDE autocomplete works correctly
- If you add a new backend, Python tells you which methods to implement
- Documents the contract for future developers
"""

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageBackend(ABC):
  """
  Abstract storage backend interface.
  
  All storage implementations must implement these methods.
  This ensures our application code works identically
  regardless of whether we're using local disk, S3, or GCS.
  """

  @abstractmethod
  async def save(self, key:str, content: bytes | BinaryIO) -> str:
    """
    Save content to storage.
    
    Args:
        key: The storage key (path). Example: "tenants/acme/docs/abc/v1/file.pdf"
        content: The file content (bytes or file-like object)
    
    Returns:
        The storage key where the file was saved
    
    Raises:
        StorageError: If the save operation fails
    """

    ...

  @abstractmethod
  async def get(self, key: str) -> bytes:
    """
    Retrieve content from storage.
    
    Args:
        key: The storage key
    
    Returns:
        The file content as bytes
    
    Raises:
        FileNotFoundError: If the key doesn't exist
        StorageError: If the retrieval fails
    """
    ...

  @abstractmethod
  async def delete(self, key: str) -> None:
    """
    Delete content from storage.
    
    Args:
        key: The storage key
    
    Note: This should be idempotent — deleting a non-existent
    key should NOT raise an error.
    """
    ...
  
  @abstractmethod
  async def exists(self, key: str) -> bool:
    """
    Check if a key exists in storage.
    
    Args:
        key: The storage key
    
    Returns:
        True if the key exists, False otherwise
    """
    ...

  @abstractmethod
  async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
    """
    Generate a URL for downloading the file.
    
    For local storage: returns a relative path
    For S3: returns a presigned URL
    
    Args:
        key: The storage key
        expires_in: URL validity in seconds (default: 1 hour)
    
    Returns:
        A URL string for downloading the file
    """
    ...
  
  @abstractmethod
  async def get_size(self, key: str) -> int:
    """
    Get the size of a stored file in bytes.
    
    Args:
        key: The storage key
    
    Returns:
        File size in bytes
    """
    ...

  def generate_key(
    self,
    tenant_id: str,
    document_id: str,
    version: int,
    filename: str,
    ) -> str:
    """
    Generate a storage key following our naming convention.
    
    This is concrete (not abstract) because the key format
    is the same regardless of storage backend.
    
    Format: tenants/{tenant_id}/documents/{document_id}/v{version}/{filename}
    """
    return f"tenants/{tenant_id}/documents/{document_id}/v{version}/{filename}"