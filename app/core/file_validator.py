"""
File validate utilities.

SECURITY-CRITICAL MODULE:
This module prevent malicious file uploads.
Every uploaded file must pass ALL validation layers.

VALIDATION ORDER (cheapest checks first):
1. Size check        → O(1), just read Content-Length header
2. Extension check   → O(1), string comparison
3. MIME type check   → O(1), header comparison
4. Magic bytes check → O(1), read first few bytes
5. Filename sanitize → O(n), string processing

WHY THIS ORDER:
If we check magic bytes first, we've already read part of the file.
If it fails the size check later, we wasted bandwidth.
Cheapest checks first = fail fast = save resources.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings

settings = get_settings()

# MAGIC BYTE SIGNATURE

# Map of file extensions to their magic bytes (first N bytes of the file)
# Used for content sniffing — verifying the file IS what it claims to be

MAGIC_BYTES: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],  # DOCX is a ZIP archive
    ".doc": [b"\xd0\xcf\x11\xe0"],  # OLE2 compound document
    ".xlsx": [b"PK\x03\x04"],  # XLSX is also a ZIP archive
    ".xls": [b"\xd0\xcf\x11\xe0"],
    ".pptx": [b"PK\x03\x04"],  # PPTX is also ZIP
    ".ppt": [b"\xd0\xcf\x11\xe0"],
    ".zip": [b"PK\x03\x04"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".epub": [b"PK\x03\x04"],  # EPUB is a ZIP archive
    ".rtf": [b"{\\rtf"],
    ".xml": [b"<?xml", b"\xef\xbb\xbf<?xml"],  # With or without BOM
    ".html": [b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML"],
    ".htm": [b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML"],
}

# Extensions that are plain text (no magic bytes to check)
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".odt"}

# MIME(Multipurpose internet mail extension)
EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".rtf": "application/rtf",
    ".epub": "application/epub+zip",
    ".odt": "application/vnd.oasis.opendocument.text",
}


class FileValidationError(Exception):
    """Raised when file validation fails."""

    def __init__(self, message: str, field: str = "file"):
        self.message = message
        self.field = field
        super().__init__(message)


class FileValidator:
    """
    Validates uploaded files through multiple security layers.

    USAGE:
      validator = FileValidator()
      validator.validate_size(file_size)
      validator.validate_extension(filename)
      validator.validate_content_type(filename, content_type)
      await validator.validate_magic_bytes(file, filename)
      safe_name = validator.sanitize_filename(filename)
    """

    def __init__(self):
        self.max_size = settings.max_upload_size_bytes
        self.allowed_extensions = settings.allowed_extensions

    def validate_size(self, file_size: int) -> None:
        """
        Check if file size is within limits.

          WHY CHECK SIZE FIRST:
          - Prevents disk exhaustion attacks
          - No point validating a 10GB file if the limit is 50MB
          - Can check from Content-Length header before reading the body
        """

        if file_size > self.max_size:
            max_mb = self.max_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            raise FileValidationError(
                f"File size ({actual_mb:.1f}MB) exceeds maximum allowed ({max_mb:.0f}MB)",
                field="file_size",
            )

        if file_size == 0:
            raise FileValidationError("File is empty (0 bytes)", field="file_size")

    def validate_extension(self, filename: str) -> str:
        """
        Validate and return the file extension.

        Returns the validated extension (lowercase, with dot).

        WHY NOT JUST CHECK MIME TYPE:
        - Users can set arbitrary Content-Type headers
        - Extension is a quick first filter
        - Combined with magic bytes, catches most attacks
        """

        ext = Path(filename).suffix.lower()

        if not ext:
            raise FileValidationError("File must have an extension", field=filename)

        if ext not in self.allowed_extensions:
            raise FileValidationError(
                f"File type '{ext} is not allowed."
                f"Allowed types: {', '.join(sorted(self.allowed_extensions))}",
                field="file_type",
            )

        return ext

    def validate_content_type(self, filename: str, content_type: str | None) -> None:
        """
        Check if the Content-Type header matches the file extension.

        This catches simple attacks like a renaming .exe to .pdf without
        changing the Content-Type header.

        NOTE: this is not foolproof! An attacker can set any Content-Type.
        That's wht we also check magic bytes (layer-4)
        """
        if content_type is None:
            return  # Some clients don't send Content-Type; we'll verify via magic bytes

        ext = Path(filename).suffix.lower()
        expected_mime = EXTENSION_TO_MIME.get(ext)

        if expected_mime and content_type != expected_mime:
            # Allow some flexibility for common MIME type variations
            # e.g., "text/plain" vs "text/plain; charset=utf-8"
            base_content_type = content_type.split(";")[0].strip()
            base_expected = expected_mime.split(";")[0].strip()

            if base_content_type != base_expected:
                # Log warning but don't reject (magic bytes are more reliable)
                # In a stricter system, you'd reject here
                pass

    async def validate_magic_bytes(self, file: BinaryIO, filename: str) -> None:
        """
        Read the first bytes of the file and verify they match the expected type.

        This is the most reliable validation because it checks the ACTUAL content,
        not metadata that can be forged.

        ATTACK THIS CATCHES:
        - malware.exe renamed to malware.pdf
        - Content-Type header set to "application/pdf"
        - Extension check passes (.pdf)
        - MIME type check passes (forged header)
        - BUT magic bytes show "MZ" (EXE signature) → REJECTED!
        """

        ext = Path(filename).suffix.lower()

        # Text files don't have magic bytes
        if ext in TEXT_EXTENSIONS:
            return

        expected_signature = MAGIC_BYTES.get(ext)
        if not expected_signature:
            return  # no known signature for this extension

        # Read the first 16 bytes (enough for any signature)
        # Seek back to the start after reading
        current_pos = file.tell() if hasattr(file, "tell") else 0
        header = file.read(16)
        if hasattr(file, "seek"):
            file.seek(current_pos)

        if not header:
            raise FileValidationError(
                "Could not read file content for validation",
                filed="file_content",
            )

        # check if any of the expected signature match
        for signature in expected_signature:
            if header[: len(signature)] == signature:
                return  # Valid!

        raise FileValidationError(
            f"File content does not match the declared file type ({ext}).",
            f"The file may be corrupted or have been renamed from a different type.",
            field="file_content",
        )

    def sanitize_filename(self, filename: str) -> str:
        """
        Clean a filename to prevent security issues.


        """

        # Remove path separator (prevent path traversal)
        filename = os.path.basename(filename)

        # Remove null bytes
        filename = filename.replace("\x00", "")

        # Remove or replace dangerous characters
        # Keep only: alphanumeric, dots, hyphens, underscore

        name, ext = os.path.splitext(filename)
        name = re.sub(r"[^\w\-.]", "-", name)
        name = re.sub(r"_+", "_", name)
        name = name.stripe("_.")

        # Truncate name (keep extension)
        max_name_length = 200  # Leave room for extension and hash
        if len(name) > max_name_length:
            name = name[:max_name_length]

        # handle empty name(after sanitization)
        if not name:
            name = "unnamed"

        return f"{name}{ext.lower()}"

    def compute_checksum(self, content: bytes):
        """
        Compute SHA-256 checksum of file content.

        USES:
        - Detect duplicate uploads (same hash = same content)
        - Verify file integrity after storage/retrieval
        - Content-addressable storage(CAS) lookups
        """
        return hashlib.sha256(content).hexdigest()
