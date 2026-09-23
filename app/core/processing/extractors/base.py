"""
Abstract base class for text extractors.

THE EXTRACTOR PATTERN:
Each document format has a specialized extractor.
All extractors share the same interface so the pipeline
doesn't need to know which format it's processing.

   pipeline.process(document)
       │
       ▼
   factory.get_extractor(mime_type)
       │
       ├── "application/pdf"    → PDFExtractor
       ├── "application/vnd..." → DOCXExtractor
       ├── "text/plain"         → TextExtractor
       └── ...

Each extractor returns the same structure:
   ExtractionResult(
     text="...",
     pages=[PageContent(...)],
     metadata={...}
   )
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PageContent:
    """
    Extracted content from a single page.
    
    For PDFs: one entry per page.
    For DOCX: one entry per section (or whole document).
    For TXT: one entry for the whole file.
    """
    page_number: int
    text: str
    headings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """
    The result of extracting text from a document.
    
    Contains:
    - text: The full extracted text (all pages concatenated)
    - pages: Per-page content (for page-level metadata)
    - metadata: Document-level metadata (author, title, etc.)
    - success: Whether extraction succeeded
    - error: Error message if extraction failed
    """
    text: str
    pages: list[PageContent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None
    
    @property
    def total_pages(self) -> int:
        return len(self.pages)
    
    @property
    def total_characters(self) -> int:
        return len(self.text)
    
    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0


class BaseExtractor(ABC):
    """
    Abstract base class for document text extractors.
    
    RESPONSIBILITIES:
    - Extract text from a specific document format
    - Preserve structure (headings, pages)
    - Return consistent ExtractionResult
    - Handle errors gracefully (never crash)
    
    IMPLEMENTING A NEW EXTRACTOR:
    1. Create a new class that inherits from BaseExtractor
    2. Implement the extract() method
    3. Register it in the factory (factory.py)
    """
    
    # Supported MIME types for this extractor
    supported_mime_types: list[str] = []
    
    @abstractmethod
    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """
        Extract text from document content.
        
        Args:
            content: Raw file bytes
            filename: Original filename (for format detection)
        
        Returns:
            ExtractionResult with extracted text and metadata
        
        IMPORTANT:
        - This method must NEVER raise an exception
        - If extraction fails, return ExtractionResult(success=False, error="...")
        - The pipeline handles errors based on the result
        """
        ...
    
    def can_handle(self, mime_type: str) -> bool:
        """Check if this extractor can handle the given MIME type."""
        return mime_type in self.supported_mime_types
