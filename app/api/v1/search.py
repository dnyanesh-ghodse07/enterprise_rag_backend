"""
Search API endpoints.

ENDPOINTS:
  POST /api/v1/search              → Search documents
  POST /api/v1/search/embed        → Embed a document's chunks
  GET  /api/v1/search/stats        → Search system statistics
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EditorUser
from app.core.database import get_session
from app.core.vector_store import QdrantService
from app.schemas.search import (
    EmbedDocumentRequest,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.embedding_service import ChunkEmbeddingService
from app.services.search_service import SearchService

router = APIRouter()


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search documents",
    description=(
        "Semantic search over your organization's documents. "
        "Supports semantic, keyword, and hybrid search modes."
    ),
)
async def search_documents(
    request: SearchRequest,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """
    Search across all documents for the current tenant.
    
    SEARCH MODES:
    - 'semantic': Vector similarity search (finds meaning, not just words)
    - 'keyword': Exact text matching (finds specific terms)
    - 'hybrid': Combines both for best results (recommended)
    
    EXAMPLE:
    {
        "query": "What was Q4 revenue?",
        "limit": 5,
        "search_mode": "hybrid"
    }
    
    RESPONSE:
    {
        "results": [
            {
                "chunk_id": "...",
                "document_id": "...",
                "content": "Q4 revenue was $50M...",
                "score": 0.92,
                "page_number": 7,
                "document_title": "Q4 Financial Report"
            },
            ...
        ],
        "total_found": 5,
        "search_time_ms": 45.2
    }
    """
    service = SearchService(db)
    
    if request.search_mode == "keyword":
        results = await service.keyword_search(
            query=request.query,
            tenant_id=user.tenant_id,
            limit=request.limit,
        )
    elif request.search_mode == "hybrid":
        results = await service.hybrid_search(
            query=request.query,
            tenant_id=user.tenant_id,
            limit=request.limit,
        )
    else:  # semantic (default)
        results = await service.semantic_search(
            query=request.query,
            tenant_id=user.tenant_id,
            limit=request.limit,
            score_threshold=request.score_threshold,
            document_ids=request.document_ids,
        )
    
    return SearchResponse(
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                content=r.content,
                score=r.score,
                chunk_index=r.chunk_index,
                page_number=r.page_number,
                section_heading=r.section_heading,
                document_title=r.document_title,
                version=r.version,
                token_count=r.token_count,
            )
            for r in results.results
        ],
        query=results.query,
        total_found=results.total_found,
        search_time_ms=results.search_time_ms,
        search_mode=request.search_mode,
    )


@router.post(
    "/embed",
    summary="Embed document chunks",
    description="Generate embeddings for a document's chunks and store in vector database.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def embed_document(
    request: EmbedDocumentRequest,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """
    Embed all chunks for a document and store in Qdrant.
    
    PREREQUISITE: Document must be processed first (Day 4).
    This endpoint generates vectors and stores them for search.
    """
    service = ChunkEmbeddingService(db)
    return await service.embed_document_chunks(
        document_id=request.document_id,
        tenant_id=user.tenant_id,
    )


@router.post(
    "/process-and-embed",
    summary="Full pipeline: process + embed",
    description="Extract text, chunk, embed, and store — all in one call.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_and_embed(
    request: EmbedDocumentRequest,
    user: EditorUser = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """
    Run the complete pipeline:
    1. Extract text from document
    2. Chunk the text
    3. Embed chunks via OpenAI
    4. Store vectors in Qdrant
    
    This is the one-call-does-it-all endpoint.
    """
    service = ChunkEmbeddingService(db)
    return await service.embed_and_process(
        document_id=request.document_id,
        tenant_id=user.tenant_id,
    )


@router.get(
    "/stats",
    summary="Vector database statistics",
)
async def get_search_stats(
    user: CurrentUser = None,
) -> dict:
    """Get statistics about the vector database."""
    qdrant = QdrantService()
    try:
        info = await qdrant.get_collection_info()
        return {"status": "connected", **info}
    except Exception as e:
        return {"status": "error", "error": str(e)}
