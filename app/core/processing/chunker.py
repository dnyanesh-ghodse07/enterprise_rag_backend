"""
Intelligent text chunking engine.

THIS IS ONE OF THE MOST IMPORTANT FILES FOR RAG QUALITY.

THE CHUNKING STRATEGY DIRECTLY AFFECTS:
1. Retrieval accuracy (can we find the right chunks?)
2. Answer quality (does the LLM have enough context?)
3. Cost (more chunks = more embeddings = more money)
4. Speed (more chunks = more vector search results to process)

OUR STRATEGY: Recursive Structure-Aware Chunking
  1. Split by document structure (headings, sections)
  2. If a section is too large, split by paragraphs
  3. If a paragraph is too large, split by sentences
  4. If a sentence is too large, split by tokens (last resort)
  5. Add overlap between adjacent chunks

TOKEN COUNTING:
  We use tiktoken for accurate token counting.
  This ensures chunks fit within embedding model limits
  and LLM context windows.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field

import tiktoken

from app.config import get_settings
from app.core.processing.extractors.base import ExtractionResult, PageContent

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """
    A single chunk of text with metadata.
    
    This is the internal representation before saving to the database.
    """
    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    section_heading: str | None = None
    metadata: dict = field(default_factory=dict)
    
    @property
    def checksum(self) -> str:
        """SHA-256 of content for dedup and integrity."""
        return hashlib.sha256(self.content.encode()).hexdigest()


class ChunkingEngine:
    """
    Splits extracted text into overlapping, token-aware chunks.
    
    USAGE:
        engine = ChunkingEngine(chunk_size=500, overlap=50)
        chunks = engine.chunk(extraction_result)
    """
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        max_chunks: int | None = None,
    ):
        """
        Initialize the chunking engine.
        
        Args:
            chunk_size: Target chunk size in tokens (default from config)
            chunk_overlap: Overlap between chunks in tokens (default from config)
            max_chunks: Maximum chunks per document (safety limit)
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.max_chunks = max_chunks or settings.max_chunks_per_document
        
        # Initialize tokenizer for accurate token counting
        try:
            self.encoding = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in a text string."""
        return len(self.encoding.encode(text))
    
    def chunk(self, extraction_result: ExtractionResult) -> list[Chunk]:
        """
        Split extracted text into intelligent chunks.
        
        ALGORITHM:
        1. If we have pages/sections, use them as initial segments
        2. For each segment that's too large, recursively split
        3. For each segment that's too small, merge with neighbors
        4. Add overlap between adjacent chunks
        5. Enrich with metadata (page number, heading, etc.)
        """
        if not extraction_result.success or extraction_result.is_empty:
            return []
        
        # Step 1: Get initial segments from document structure
        segments = self._get_initial_segments(extraction_result)
        
        # Step 2: Split large segments recursively
        split_segments = []
        for segment in segments:
            if self.count_tokens(segment["text"]) > self.chunk_size:
                sub_segments = self._recursive_split(
                    segment["text"],
                    segment.get("page_number"),
                    segment.get("heading"),
                )
                split_segments.extend(sub_segments)
            elif segment["text"].strip():
                split_segments.append(segment)
        
        # Step 3: Merge small segments with neighbors
        merged_segments = self._merge_small_segments(split_segments)
        
        # Step 4: Add overlap
        chunks_with_overlap = self._add_overlap(merged_segments)
        
        # Step 5: Create Chunk objects with metadata
        chunks = []
        for idx, seg in enumerate(chunks_with_overlap):
            if idx >= self.max_chunks:
                logger.warning(
                    f"Document exceeded max chunks ({self.max_chunks}). "
                    f"Truncating."
                )
                break
            
            content = seg["text"].strip()
            if not content:
                continue
            
            chunks.append(Chunk(
                content=content,
                chunk_index=idx,
                token_count=self.count_tokens(content),
                page_number=seg.get("page_number"),
                section_heading=seg.get("heading"),
                metadata=seg.get("metadata", {}),
            ))
        
        logger.info(
            f"Created {len(chunks)} chunks "
            f"(avg {sum(c.token_count for c in chunks) // max(len(chunks), 1)} tokens/chunk)"
        )
        
        return chunks
    
    def _get_initial_segments(self, result: ExtractionResult) -> list[dict]:
        """
        Get initial text segments from the extraction result.
        
        Uses page/section structure if available,
        otherwise treats the whole document as one segment.
        """
        if result.pages:
            segments = []
            for page in result.pages:
                segments.append({
                    "text": page.text,
                    "page_number": page.page_number,
                    "heading": page.headings[0] if page.headings else None,
                    "metadata": page.metadata,
                })
            return segments
        
        # No page structure — return whole text
        return [{"text": result.text, "page_number": None, "heading": None}]
    
    def _recursive_split(
        self,
        text: str,
        page_number: int | None = None,
        heading: str | None = None,
    ) -> list[dict]:
        """
        Recursively split text until each piece fits within chunk_size.
        
        SPLITTING HIERARCHY:
        1. Double newline (paragraph boundary)
        2. Single newline (line boundary)
        3. Sentence boundary (. ? ! followed by space)
        4. Token-level split (last resort)
        """
        # Base case: text fits in one chunk
        if self.count_tokens(text) <= self.chunk_size:
            return [{"text": text, "page_number": page_number, "heading": heading}]
        
        # Try splitting by paragraphs
        separators = [
            "\n\n",          # Paragraph boundary
            "\n",            # Line boundary
            ". ",            # Sentence boundary
            "? ",            # Question boundary
            "! ",            # Exclamation boundary
            "; ",            # Semicolon
            ", ",            # Comma (last resort for text)
        ]
        
        for separator in separators:
            parts = text.split(separator)
            
            if len(parts) <= 1:
                continue  # This separator doesn't split the text
            
            # Reconstruct chunks from parts
            segments = []
            current_text = ""
            
            for part in parts:
                # Add separator back (except for first part)
                candidate = current_text + separator + part if current_text else part
                
                if self.count_tokens(candidate) <= self.chunk_size:
                    current_text = candidate
                else:
                    if current_text.strip():
                        segments.append({
                            "text": current_text,
                            "page_number": page_number,
                            "heading": heading,
                        })
                    current_text = part
            
            # Don't forget the last piece
            if current_text.strip():
                segments.append({
                    "text": current_text,
                    "page_number": page_number,
                    "heading": heading,
                })
            
            if len(segments) > 1:
                # Recursively split any segments that are still too large
                result = []
                for seg in segments:
                    if self.count_tokens(seg["text"]) > self.chunk_size:
                        result.extend(self._recursive_split(
                            seg["text"], page_number, heading
                        ))
                    else:
                        result.append(seg)
                return result
        
        # Last resort: split by token count
        return self._token_split(text, page_number, heading)
    
    def _token_split(
        self,
        text: str,
        page_number: int | None,
        heading: str | None,
    ) -> list[dict]:
        """
        Split text by exact token count (last resort).
        
        This is the fallback when no natural boundary is found.
        It's crude but guarantees chunks fit within the limit.
        """
        tokens = self.encoding.encode(text)
        segments = []
        
        for i in range(0, len(tokens), self.chunk_size):
            chunk_tokens = tokens[i:i + self.chunk_size]
            chunk_text = self.encoding.decode(chunk_tokens)
            
            if chunk_text.strip():
                segments.append({
                    "text": chunk_text,
                    "page_number": page_number,
                    "heading": heading,
                })
        
        return segments
    
    def _merge_small_segments(self, segments: list[dict]) -> list[dict]:
        """
        Merge very small segments with their neighbors.
        
        WHY: A 20-token chunk wastes embedding space and
        provides insufficient context for retrieval.
        
        RULE: If a segment is < 25% of target chunk_size,
        merge it with the next segment.
        """
        min_size = self.chunk_size // 4  # Minimum useful chunk size
        merged = []
        
        i = 0
        while i < len(segments):
            current = segments[i].copy()
            
            # While current is too small and there's a next segment
            while (
                self.count_tokens(current["text"]) < min_size
                and i + 1 < len(segments)
            ):
                i += 1
                next_seg = segments[i]
                current["text"] = current["text"] + "\n\n" + next_seg["text"]
                # Keep the heading from whichever segment had one
                if not current.get("heading") and next_seg.get("heading"):
                    current["heading"] = next_seg["heading"]
            
            merged.append(current)
            i += 1
        
        return merged
    
    def _add_overlap(self, segments: list[dict]) -> list[dict]:
        """
        Add overlapping text between adjacent chunks.
        
        HOW OVERLAP WORKS:
        
        Original:  [Chunk A text] [Chunk B text] [Chunk C text]
        
        With overlap:
          Chunk A: [Chunk A text][← end of A overlaps with start of B →]
          Chunk B: [← start of B overlaps with end of A →][Chunk B text][← end overlaps C →]
          Chunk C: [← start overlaps end of B →][Chunk C text]
        
        Each chunk ENDS with the first N tokens of the NEXT chunk.
        Each chunk STARTS with the last N tokens of the PREVIOUS chunk.
        """
        if self.chunk_overlap <= 0 or len(segments) <= 1:
            return segments
        
        result = []
        
        for i, segment in enumerate(segments):
            text = segment["text"]
            
            # Add overlap from previous chunk (prefix)
            if i > 0:
                prev_text = segments[i - 1]["text"]
                prev_tokens = self.encoding.encode(prev_text)
                overlap_tokens = prev_tokens[-self.chunk_overlap:]
                overlap_text = self.encoding.decode(overlap_tokens)
                text = overlap_text + "\n" + text
            
            # We don't add overlap from the next chunk (suffix)
            # because the next chunk will add it as its prefix.
            # This prevents double-counting the overlap.
            
            result.append({
                "text": text,
                "page_number": segment.get("page_number"),
                "heading": segment.get("heading"),
                "metadata": segment.get("metadata", {}),
            })
        
        return result
