"""
Text extractor for plain text formats: TXT, MD, CSV, HTML, JSON, XML.

These formats are simpler to extract because the text is already
accessible — no binary parsing needed.

EACH FORMAT HAS NUANCES:
- TXT: Just read it. Handle encoding.
- MD: Preserve structure (headings, lists, code blocks).
- CSV: Convert rows to natural language sentences.
- HTML: Strip tags, preserve structure.
- JSON: Convert to readable key-value format.
- XML: Strip tags, extract text content.
"""

import csv
import io
import json
import logging
from pathlib import Path

from app.core.processing.extractors.base import (
    BaseExtractor,
    ExtractionResult,
    PageContent,
)

logger = logging.getLogger(__name__)


class TextExtractor(BaseExtractor):
    """Extract text from plain text formats."""
    
    supported_mime_types = [
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "text/htm",
        "application/json",
        "application/xml",
        "text/xml",
        "application/rtf",
    ]
    
    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """Extract text based on file extension."""
        try:
            ext = Path(filename).suffix.lower()
            
            # Detect and decode text encoding
            text = self._decode_content(content)
            
            if ext in (".txt", ".md"):
                return self._extract_text_or_markdown(text, filename)
            elif ext == ".csv":
                return self._extract_csv(text, filename)
            elif ext in (".html", ".htm"):
                return self._extract_html(text, filename)
            elif ext == ".json":
                return self._extract_json(text, filename)
            elif ext in (".xml",):
                return self._extract_xml(text, filename)
            else:
                # Default: treat as plain text
                return self._extract_text_or_markdown(text, filename)
        
        except Exception as e:
            logger.error(f"Text extraction failed for {filename}: {e}")
            return ExtractionResult(
                text="",
                success=False,
                error=f"Text extraction failed: {str(e)}",
            )
    
    def _decode_content(self, content: bytes) -> str:
        """
        Decode bytes to string with encoding detection.
        
        ENCODING ISSUES:
        - Most modern files are UTF-8
        - Some older files are Latin-1 (ISO-8859-1)
        - Some Windows files are CP-1252
        - Some Asian files are Shift-JIS or GB2312
        
        STRATEGY: Try UTF-8 first, then fall back.
        """
        # Try UTF-8 (most common)
        try:
            # Handle BOM (Byte Order Mark)
            if content.startswith(b'\xef\xbb\xbf'):
                return content[3:].decode('utf-8')
            return content.decode('utf-8')
        except UnicodeDecodeError:
            pass
        
        # Try Latin-1 (never fails, but may be wrong)
        try:
            return content.decode('latin-1')
        except Exception:
            # Last resort: ignore errors
            return content.decode('utf-8', errors='ignore')
    
    def _extract_text_or_markdown(self, text: str, filename: str) -> ExtractionResult:
        """Extract text/markdown with heading detection."""
        headings = []
        sections: list[PageContent] = []
        current_section: list[str] = []
        current_heading = ""
        section_idx = 0
        
        for line in text.split("\n"):
            # Detect markdown headings
            stripped = line.strip()
            if stripped.startswith("#"):
                # Save previous section
                if current_section:
                    sections.append(PageContent(
                        page_number=section_idx + 1,
                        text="\n".join(current_section),
                        headings=[current_heading] if current_heading else [],
                    ))
                    section_idx += 1
                    current_section = []
                
                current_heading = stripped.lstrip("#").strip()
                headings.append(current_heading)
            
            current_section.append(line)
        
        # Save last section
        if current_section:
            sections.append(PageContent(
                page_number=section_idx + 1,
                text="\n".join(current_section),
                headings=[current_heading] if current_heading else [],
            ))
        
        return ExtractionResult(
            text=text,
            pages=sections,
            metadata={
                "extraction_method": "direct_read",
                "headings": headings,
                "encoding": "utf-8",
            },
            success=True,
        )
    
    def _extract_csv(self, text: str, filename: str) -> ExtractionResult:
        """
        Convert CSV to natural language text.
        
        WHY CONVERT:
        A CSV row like: "Acme Corp,50000000,2024-Q4"
        is meaningless without headers.
        
        We convert to: "Company: Acme Corp, Revenue: $50,000,000, Quarter: 2024-Q4"
        This is much better for semantic search and LLM understanding.
        """
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows: list[str] = []
            headers = reader.fieldnames or []
            
            for i, row in enumerate(reader):
                if i >= 10000:  # Safety limit
                    rows.append(f"... (truncated at 10,000 rows)")
                    break
                
                # Convert row to natural language
                parts = [f"{key}: {value}" for key, value in row.items() if value]
                rows.append(", ".join(parts))
            
            converted_text = f"Data with columns: {', '.join(headers)}\n\n"
            converted_text += "\n".join(rows)
            
            return ExtractionResult(
                text=converted_text,
                pages=[PageContent(
                    page_number=1,
                    text=converted_text,
                    headings=[f"CSV Data: {filename}"],
                    metadata={"row_count": len(rows), "columns": headers},
                )],
                metadata={
                    "extraction_method": "csv_reader",
                    "row_count": len(rows),
                    "columns": headers,
                },
                success=True,
            )
        except Exception as e:
            # If CSV parsing fails, treat as plain text
            return self._extract_text_or_markdown(text, filename)
    
    def _extract_html(self, text: str, filename: str) -> ExtractionResult:
        """
        Extract text from HTML, preserving structure.
        
        STRATEGY:
        1. Parse HTML with BeautifulSoup
        2. Remove script and style tags
        3. Convert headings to markdown format
        4. Preserve list structure
        5. Extract text content
        """
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(text, "lxml")
            
            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            
            # Extract headings
            headings = []
            for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                heading_text = tag.get_text(strip=True)
                if heading_text:
                    level = int(tag.name[1])
                    headings.append(heading_text)
                    # Replace tag with markdown heading
                    tag.replace_with(f"\n{'#' * level} {heading_text}\n")
            
            # Get text with some structure preserved
            extracted = soup.get_text(separator="\n", strip=True)
            
            # Clean up excessive newlines
            import re
            extracted = re.sub(r'\n{3,}', '\n\n', extracted)
            
            return ExtractionResult(
                text=extracted,
                pages=[PageContent(
                    page_number=1,
                    text=extracted,
                    headings=headings,
                )],
                metadata={
                    "extraction_method": "beautifulsoup",
                    "headings": headings,
                },
                success=True,
            )
        except ImportError:
            # If BeautifulSoup not available, strip tags manually
            import re
            clean = re.sub(r'<[^>]+>', ' ', text)
            clean = re.sub(r'\s+', ' ', clean).strip()
            return self._extract_text_or_markdown(clean, filename)
    
    def _extract_json(self, text: str, filename: str) -> ExtractionResult:
        """Convert JSON to readable text."""
        try:
            data = json.loads(text)
            # Pretty-print the JSON
            readable = json.dumps(data, indent=2, ensure_ascii=False)
            
            return ExtractionResult(
                text=readable,
                pages=[PageContent(
                    page_number=1,
                    text=readable,
                    headings=[f"JSON Data: {filename}"],
                )],
                metadata={"extraction_method": "json_parser"},
                success=True,
            )
        except json.JSONDecodeError:
            return self._extract_text_or_markdown(text, filename)
    
    def _extract_xml(self, text: str, filename: str) -> ExtractionResult:
        """Extract text content from XML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "lxml-xml")
            extracted = soup.get_text(separator="\n", strip=True)
            
            return ExtractionResult(
                text=extracted,
                pages=[PageContent(page_number=1, text=extracted)],
                metadata={"extraction_method": "xml_parser"},
                success=True,
            )
        except Exception:
            # Fallback: strip XML tags
            import re
            clean = re.sub(r'<[^>]+>', ' ', text)
            return self._extract_text_or_markdown(clean, filename)
