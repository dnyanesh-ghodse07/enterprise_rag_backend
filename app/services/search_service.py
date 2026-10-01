"""
Search service — semantic search over document chunks.

THE HEART OF OUR RAG SYSTEM:
1. User asks a question
2. We embed the question
3. We search Qdrant for similar chunks
4. We return the most relevant chunks with metadata
5. (Day 6: We send these chunks to the LLM for answering)

SEARCH MODES:
- Semantic: Vector similarity search (default)
- Keyword: PostgreSQL full-text search (fallback)
- Hybrid: Both combined with Reciprocal Rank Fusion
"""

import logging
import time
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingService
from app.core.vector_store import QdrantService, SearchResult, SearchResults
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class SearchService:
    """
    Semantic search over tenant-scoped document chunks.
    
    EVERY search method requires tenant_id.
    There is no "search everything" function.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = EmbeddingService()
        self.qdrant = QdrantService()
    
    async def semantic_search(
        self,
        query: str,
        tenant_id: UUID,
        limit: int = 10,
        score_threshold: float | None = None,
        document_ids: list[UUID] | None = None,
    ) -> SearchResults:
        """
        Perform semantic search using vector similarity.
        
        FLOW:
        1. Embed the query using OpenAI
        2. Search Qdrant for similar vectors
        3. Filter by tenant_id (mandatory)
        4. Return ranked results with scores
        
        Args:
            query: The user's question or search text
            tenant_id: REQUIRED. Only searches this tenant's documents.
            limit: Maximum results to return
            score_threshold: Minimum similarity (0.0-1.0)
            document_ids: Optional. Restrict to specific documents.
        """
        if not query.strip():
            return SearchResults(results=[], query=query, total_found=0)
        
        start_time = time.time()
        
        # ─── Step 1: Embed the query ──────────────────────────
        try:
            query_vector = await self.embedder.embed_query(query)
        except Exception as e:
            logger.error(f"Query embedding failed: {e}")
            return SearchResults(
                results=[],
                query=query,
                total_found=0,
                search_time_ms=0,
            )
        
        # ─── Step 2: Search Qdrant ────────────────────────────
        doc_id_strs = [str(d) for d in document_ids] if document_ids else None
        
        results = await self.qdrant.search(
            query_vector=query_vector,
            tenant_id=str(tenant_id),
            limit=limit,
            score_threshold=score_threshold,
            document_ids=doc_id_strs,
        )
        
        results.query = query
        results.search_time_ms = round((time.time() - start_time) * 1000, 2)
        
        logger.info(
            f"Search '{query[:50]}...' → {results.total_found} results "
            f"in {results.search_time_ms}ms"
        )
        
        return results
    
    async def keyword_search(
        self,
        query: str,
        tenant_id: UUID,
        limit: int = 10,
    ) -> SearchResults:
        """
        Full-text keyword search using PostgreSQL.
        
        This is a fallback when:
        - Looking for exact terms (product codes, names)
        - OpenAI embedding API is down
        - User wants exact phrase matching
        
        Uses PostgreSQL's built-in full-text search with ts_vector.
        """
        start_time = time.time()
        
        # Simple ILIKE search (can be upgraded to ts_vector later)
        search_pattern = f"%{query}%"
        
        result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.content.ilike(search_pattern),
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        chunks = result.scalars().all()
        
        search_time_ms = (time.time() - start_time) * 1000
        
        results = []
        for i, chunk in enumerate(chunks):
            # Simple relevance score based on position
            # (keyword search doesn't have natural similarity scores)
            score = 1.0 - (i * 0.05)  # Decrease by rank
            
            results.append(SearchResult(
                chunk_id=str(chunk.id),
                document_id=str(chunk.document_id),
                tenant_id=str(chunk.tenant_id),
                content=chunk.content,
                score=max(score, 0.1),
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                section_heading=chunk.section_heading,
                version=chunk.version,
                token_count=chunk.token_count,
            ))
        
        return SearchResults(
            results=results,
            query=query,
            total_found=len(results),
            search_time_ms=round(search_time_ms, 2),
        )
    
    async def hybrid_search(
        self,
        query: str,
        tenant_id: UUID,
        limit: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> SearchResults:
        """
        Hybrid search combining semantic and keyword results.
        
        Uses Reciprocal Rank Fusion (RRF) to merge results:
        
        RRF score = Σ (weight_i / (k + rank_i))
        
        Where:
        - k = 60 (standard constant)
        - rank_i = position in result list (1-indexed)
        - weight_i = semantic_weight or keyword_weight
        
        This ensures:
        - Top semantic results get high scores
        - Top keyword results get high scores
        - Results appearing in BOTH lists get boosted
        
        WHY RRF INSTEAD OF SIMPLE AVERAGING:
        Semantic scores (0.0-1.0) and keyword scores have
        different distributions. Direct averaging is unfair.
        RRF only uses RANK (position), not raw scores.
        """
        start_time = time.time()
        
        # Run both searches
        fetch_limit = limit * 2  # Fetch more to have enough after fusion
        
        semantic_results = await self.semantic_search(
            query, tenant_id, limit=fetch_limit,
        )
        keyword_results = await self.keyword_search(
            query, tenant_id, limit=fetch_limit,
        )
        
        # ─── Reciprocal Rank Fusion ───────────────────────────
        k = 60  # Standard RRF constant
        rrf_scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}
        
        # Score semantic results
        for rank, result in enumerate(semantic_results.results, 1):
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + \
                semantic_weight / (k + rank)
            result_map[chunk_id] = result
        
        # Score keyword results
        for rank, result in enumerate(keyword_results.results, 1):
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + \
                keyword_weight / (k + rank)
            # Only update result_map if not already present (prefer semantic version)
            if chunk_id not in result_map:
                result_map[chunk_id] = result
        
        # Sort by RRF score
        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
        
        # Build final results
        final_results = []
        for chunk_id in sorted_ids[:limit]:
            result = result_map[chunk_id]
            result.score = rrf_scores[chunk_id]
            result.metadata["search_type"] = "hybrid"
            final_results.append(result)
        
        search_time_ms = (time.time() - start_time) * 1000
        
        return SearchResults(
            results=final_results,
            query=query,
            total_found=len(final_results),
            search_time_ms=round(search_time_ms, 2),
        )
