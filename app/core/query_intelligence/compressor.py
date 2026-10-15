"""
Contextual compression — extract only relevant parts from chunks.

PROBLEM:
A 500-token chunk might contain 50 tokens of relevant information
and 450 tokens of noise. The noise wastes LLM context window and
can confuse the model.

SOLUTION:
Use a small LLM to extract ONLY the parts of each chunk that are
relevant to the user's question.

TRADE-OFF:
  ✅ Less noise in LLM context → better answers
  ✅ Can fit more chunks in context window
  ❌ Extra LLM call per chunk (~$0.001 per chunk)
  ❌ Adds ~500ms latency

WHEN TO USE:
- Long chunks with mixed content
- Analytical queries that need more context
- When token budget is tight

WHEN NOT TO USE:
- Short, focused chunks (already minimal)
- Factual queries with clear answers
- When latency is critical
"""

import logging

from app.core.llm import LLMMessage, OpenAIClient
from app.core.vector_store.schemas import SearchResult

logger = logging.getLogger(__name__)


class ContextualCompressor:
    """Compresses chunk content to only relevant information."""
    
    def __init__(self):
        self.llm = OpenAIClient(model="gpt-4o-mini")
    
    async def compress(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        Compress each search result to only relevant content.
        
        For each chunk:
        1. Send (query, chunk) to LLM
        2. LLM extracts relevant sentences
        3. Replace chunk content with compressed version
        4. If nothing is relevant, remove the chunk
        """
        compressed_results = []
        
        for result in results:
            compressed_content = await self._compress_single(
                query, result.content
            )
            
            if compressed_content:  # Only keep if something relevant
                # Create a new result with compressed content
                compressed = SearchResult(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    tenant_id=result.tenant_id,
                    content=compressed_content,
                    score=result.score,
                    chunk_index=result.chunk_index,
                    page_number=result.page_number,
                    section_heading=result.section_heading,
                    document_title=result.document_title,
                    version=result.version,
                    token_count=result.token_count,
                    metadata={
                        **result.metadata,
                        "compressed": True,
                        "original_length": len(result.content),
                        "compressed_length": len(compressed_content),
                    },
                )
                compressed_results.append(compressed)
            else:
                logger.info(
                    f"Chunk {result.chunk_id} removed (not relevant to query)"
                )
        
        logger.info(
            f"Compressed {len(results)} chunks → {len(compressed_results)} "
            f"(removed {len(results) - len(compressed_results)})"
        )
        
        return compressed_results
    
    async def _compress_single(self, query: str, content: str) -> str | None:
        """Compress a single chunk to relevant content only."""
        prompt = f"""Extract ONLY the sentences from the following text that are relevant to answering this question. 
If no part of the text is relevant, respond with exactly "NOT_RELEVANT".
Do not add any explanation, just the relevant sentences.

Question: {query}

Text: {content}

Relevant sentences:"""
        
        try:
            response = await self.llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.0,
                max_tokens=300,
            )
            
            result = response.content.strip()
            
            if result == "NOT_RELEVANT" or len(result) < 10:
                return None
            
            return result
        
        except Exception as e:
            logger.warning(f"Compression failed: {e}, using original")
            return content  # Fallback: use original content
