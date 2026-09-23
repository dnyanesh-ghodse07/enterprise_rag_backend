"""
PDF text extractor using PyMuPDF (fitz).

WHY PyMuPDF:
- Written in C/C++ → very fast (10x faster than pdfplumber)
- Handles most PDF layouts correctly
- Extracts text in reading order (using text blocks)
- Preserves paragraph structure
- Detects tables (basic)
- Can extract images (for future multimodal)

HOW IT WORKS:
1. Open PDF from bytes (no temp file needed)
2. For each page:
   a. Get text blocks (paragraphs with positions)
   b. Sort blocks by position (top→bottom, left→right)
   c. Join blocks into page text
   d. Detect headings (larger font = heading)
3. Combine all pages into full text
4. Return with per-page metadata

LIMITATIONS:
- Scanned PDFs (images of text): no text to extract
  → Falls back to OCR (not implemented today)
- Complex tables: columns may merge
  → Use pdfplumber for table-heavy documents
- Right-to-left languages: may need special handling
"""

import pymupdf  # PyMuPDF
import logging

from app.core.processing.extractors.base import (
    BaseExtractor,
    ExtractionResult,
    PageContent,
)

logger = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """Extract text from PDF documents using PyMuPDF."""

    supported_mime_types = ["application/pdf"]

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """
        Extract text from a PDF file.

        PROCESSING STEPS:
        1. Open PDF from memory (no temp file)
        2. Iterate through pages
        3. Extract text blocks with positions
        4. Detect headings by font size
        5. Reconstruct reading order
        6. Return structured result
        """
        try:
            # Open PDF from bytes (no need to save to disk)
            doc = pymupdf.open(stream=content, filetype="pdf")

            pages: list[PageContent] = []
            all_text_parts: list[str] = []

            for page_num in range(len(doc)):
                page = doc[page_num]

                # Extract text blocks
                # Each block: (x0, y0, x1, y1, "text", block_no, block_type)
                # block_type 0 = text, 1 = image
                blocks = page.get_text("blocks")

                # Filter to text blocks only and sort by position
                text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text

                # Sort: top to bottom, then left to right
                text_blocks.sort(key=lambda b: (b[1], b[0]))

                # Extract text from blocks
                page_text = "\n".join(
                    block[4].strip() for block in text_blocks if block[4].strip()
                )

                # Detect headings (text with larger font size)
                headings = self._detect_headings(page, text_blocks)

                if page_text.strip():
                    pages.append(
                        PageContent(
                            page_number=page_num + 1,  # 1-indexed
                            text=page_text,
                            headings=headings,
                            metadata={
                                "width": page.rect.width,
                                "height": page.rect.height,
                                "has_images": len(page.get_images()) > 0,
                            },
                        )
                    )
                    all_text_parts.append(page_text)

            doc.close()

            full_text = "\n\n".join(all_text_parts)

            # Check if we got any text
            if not full_text.strip():
                return ExtractionResult(
                    text="",
                    pages=[],
                    metadata={"scanned": True},
                    success=False,
                    error=(
                        "No text found in PDF. This may be a scanned document. "
                        "OCR processing is required."
                    ),
                )

            return ExtractionResult(
                text=full_text,
                pages=pages,
                metadata={
                    "total_pages": len(doc) if not doc.is_closed else len(pages),
                    "extraction_method": "pymupdf",
                    "scanned": False,
                },
                success=True,
            )

        except Exception as e:
            logger.error(f"PDF extraction failed for {filename}: {e}")
            return ExtractionResult(
                text="",
                success=False,
                error=f"PDF extraction failed: {str(e)}",
            )

    def _detect_headings(self, page, text_blocks: list) -> list[str]:
        """
        Detect headings by analyzing font sizes.

        HEURISTIC:
        - Get all font sizes on the page
        - Text with font size > 1.2x the median is likely a heading
        - This is a simple heuristic; more sophisticated approaches
          use ML (layoutparser) or font name analysis
        """
        headings = []

        try:
            # Get detailed text with font info
            text_dict = page.get_text("dict")

            # Collect all font sizes
            font_sizes = []
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            font_sizes.append(span.get("size", 12))

            if not font_sizes:
                return headings

            # Calculate median font size
            sorted_sizes = sorted(font_sizes)
            median_size = sorted_sizes[len(sorted_sizes) // 2]
            heading_threshold = median_size * 1.2

            # Find text with larger-than-median font size
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if span.get("size", 12) >= heading_threshold:
                                text = span.get("text", "").strip()
                                if text and len(text) > 2 and len(text) < 200:
                                    headings.append(text)
        except Exception:
            pass  # Heading detection is best-effort

        return headings
