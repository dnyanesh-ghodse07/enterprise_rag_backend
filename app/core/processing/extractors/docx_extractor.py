"""
DOCX text extractor using python-docx.

HOW DOCX FILES WORK:
A .docx file is actually a ZIP archive containing:
  [Content_Types].xml  → file type declarations
  word/document.xml    → the actual document content
  word/styles.xml      → style definitions (headings, fonts)
  word/media/          → embedded images
  word/_rels/          → relationships between parts

python-docx reads the XML and provides a clean API:
  doc.paragraphs → list of paragraphs
  para.style.name → "Heading 1", "Normal", "List Bullet"
  para.text → the text content
  doc.tables → list of tables
  table.rows → list of rows
  row.cells → list of cells

ADVANTAGES OVER PDF:
- Text order is always correct (paragraphs are sequential)
- Headings are explicitly marked (by style)
- Tables are structured (rows and cells)
- Much simpler extraction logic
"""

import io
import logging

from docx import Document as DocxDocument

from app.core.processing.extractors.base import (
    BaseExtractor,
    ExtractionResult,
    PageContent,
)

logger = logging.getLogger(__name__)


class DOCXExtractor(BaseExtractor):
    """Extract text from DOCX documents."""
    
    supported_mime_types = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    
    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """
        Extract text from a DOCX file.
        
        STRATEGY:
        1. Open DOCX from bytes
        2. Extract paragraphs with style information
        3. Extract tables as structured text
        4. Detect headings from paragraph styles
        5. Build page-like sections from headings
        """
        try:
            doc = DocxDocument(io.BytesIO(content))
            
            text_parts: list[str] = []
            headings: list[str] = []
            current_section_text: list[str] = []
            current_heading: str = ""
            sections: list[PageContent] = []
            section_idx = 0
            
            # Process paragraphs
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                
                # Check if this is a heading
                style_name = para.style.name if para.style else ""
                
                if style_name.startswith("Heading"):
                    # Save previous section
                    if current_section_text:
                        sections.append(PageContent(
                            page_number=section_idx + 1,
                            text="\n".join(current_section_text),
                            headings=[current_heading] if current_heading else [],
                        ))
                        section_idx += 1
                        current_section_text = []
                    
                    current_heading = text
                    headings.append(text)
                    text_parts.append(f"\n{'#' * self._heading_level(style_name)} {text}\n")
                    current_section_text.append(f"{'#' * self._heading_level(style_name)} {text}")
                else:
                    text_parts.append(text)
                    current_section_text.append(text)
            
            # Save last section
            if current_section_text:
                sections.append(PageContent(
                    page_number=section_idx + 1,
                    text="\n".join(current_section_text),
                    headings=[current_heading] if current_heading else [],
                ))
            
            # Extract tables
            for table_idx, table in enumerate(doc.tables):
                table_text = self._extract_table(table)
                if table_text:
                    text_parts.append(f"\n[Table {table_idx + 1}]\n{table_text}\n")
            
            full_text = "\n".join(text_parts)
            
            if not full_text.strip():
                return ExtractionResult(
                    text="",
                    success=False,
                    error="No text found in DOCX document.",
                )
            
            return ExtractionResult(
                text=full_text,
                pages=sections if sections else [PageContent(
                    page_number=1,
                    text=full_text,
                    headings=headings,
                )],
                metadata={
                    "extraction_method": "python-docx",
                    "total_sections": len(sections),
                    "total_tables": len(doc.tables),
                    "headings": headings,
                },
                success=True,
            )
        
        except Exception as e:
            logger.error(f"DOCX extraction failed for {filename}: {e}")
            return ExtractionResult(
                text="",
                success=False,
                error=f"DOCX extraction failed: {str(e)}",
            )
    
    def _heading_level(self, style_name: str) -> int:
        """Convert Word heading style to markdown level."""
        # "Heading 1" → 1, "Heading 2" → 2, etc.
        try:
            return int(style_name.split()[-1])
        except (ValueError, IndexError):
            return 1
    
    def _extract_table(self, table) -> str:
        """
        Convert a DOCX table to a markdown-style text representation.
        
        WHY MARKDOWN FORMAT:
        LLMs understand markdown tables very well.
        Converting to markdown preserves structure while
        being readable as plain text.
        """
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append("| " + " | ".join(cells) + " |")
        
        if not rows:
            return ""
        
        # Add separator after header row
        if len(rows) > 1:
            num_cols = len(table.rows[0].cells)
            separator = "| " + " | ".join(["---"] * num_cols) + " |"
            rows.insert(1, separator)
        
        return "\n".join(rows)
