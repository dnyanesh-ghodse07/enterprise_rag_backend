"""
Extractor factory — selects the right extractor for each file type.
"""

import logging

from app.core.processing.extractors.base import BaseExtractor
from app.core.processing.extractors.pdf_extractor import PDFExtractor
from app.core.processing.extractors.docx_extractor import DOCXExtractor
from app.core.processing.extractors.text_extractor import TextExtractor

logger = logging.getLogger(__name__)

# Registry of all available extractors
_EXTRACTORS: list[BaseExtractor] = [
    PDFExtractor(),
    DOCXExtractor(),
    TextExtractor(),
]


def get_extractor(mime_type: str) -> BaseExtractor | None:
    """
    Get the appropriate extractor for a MIME type.
    
    Returns None if no extractor can handle the type.
    """
    for extractor in _EXTRACTORS:
        if extractor.can_handle(mime_type):
            return extractor
    
    logger.warning(f"No extractor found for MIME type: {mime_type}")
    return None


def get_supported_mime_types() -> list[str]:
    """Return all MIME types we can extract text from."""
    mime_types = []
    for extractor in _EXTRACTORS:
        mime_types.extend(extractor.supported_mime_types)
    return mime_types
