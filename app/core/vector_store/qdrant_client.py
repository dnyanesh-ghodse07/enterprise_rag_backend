"""
Qdrant vector database client wrapper.

THIS IS THE INTERFACE TO OUR VECTOR DATABASE.

RESPONSIBILITIES:
- Initialize and manage the Qdrant collection
- Insert/update/delete vectors with payload metadata
- Perform semantic search with tenant filtering
- Handle connection lifecycle

TENANT ISOLATION:
Every search method REQUIRES tenant_id.
The tenant filter is ALWAYS applied.
There is no way to search across tenants (by design).

COLLECTION STRUCTURE:
- One collection: "cognix_documents"
- Each point = one document chunk
- Point ID = chunk UUID (same as in PostgreSQL)
- Payload = metadata for filtering and display
"""

import logging
import time
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings
from app.core.vector_store.schemas import SearchResult, SearchResults

settings = get_settings()
logger = logging.getLogger(__name__)


class QdrantService:
    """
    Qdrant vector database client.
    
    USAGE:
        qdrant = QdrantService()
        await qdrant.initialize()  # Create collection if needed
        await qdrant.upsert_chunks(chunks_with_vectors)
        results = await qdrant.search(query_vector, tenant_id)
    """
    
    def __init__(self):
        """Initialize the Qdrant client."""
        self.client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key or None,
            timeout=30,
        )
        self.collection_name = settings.qdrant_collection_name
        self.vector_size = settings.embedding_dimensions
    
    async def initialize(self) -> None:
        """
        Create the Qdrant collection if it doesn't exist.
        
        COLLECTION CONFIG:
        - Vector size: 1536 (matches text-embedding-3-small)
        - Distance: Cosine (standard for text embeddings)
        - HNSW: m=16, ef_construct=100 (balanced recall/speed)
        
        PAYLOAD INDEXES:
        - tenant_id: For mandatory tenant filtering
        - document_id: For document-level operations (delete all chunks)
        """
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        
        if self.collection_name not in existing:
            logger.info(f"Creating Qdrant collection: {self.collection_name}")
            
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                    # COSINE distance:
                    # - 1.0 = identical
                    # - 0.0 = unrelated
                    # - -1.0 = opposite (rare)
                ),
                hnsw_config=models.HnswConfigDiff(
                    m=16,             # Edges per node (higher = better recall, more memory)
                    ef_construct=100, # Build-time quality (higher = better index)
                ),
                # Optimizers config for better performance
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=20000,  # Build index after 20K points
                ),
            )
            
            # Create payload indexes for fast filtering
            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="tenant_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="document_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            
            logger.info(f"Collection '{self.collection_name}' created with payload indexes")
        else:
            logger.info(f"Collection '{self.collection_name}' already exists")
    
    async def upsert_chunks(
        self,
        points: list[dict],
    ) -> None:
        """
        Insert or update vectors in Qdrant.
        
        Args:
            points: List of dicts with keys:
                - id: UUID string
                - vector: list of floats
                - payload: dict of metadata
        
        UPSERT means:
        - If the ID doesn't exist → INSERT
        - If the ID exists → UPDATE (replace vector + payload)
        
        This makes re-processing idempotent:
        processing a document twice produces the same result.
        """
        if not points:
            return
        
        qdrant_points = [
            models.PointStruct(
                id=point["id"],
                vector=point["vector"],
                payload=point["payload"],
            )
            for point in points
        ]
        
        # Upsert in batches of 100 (Qdrant's recommended batch size)
        batch_size = 100
        for i in range(0, len(qdrant_points), batch_size):
            batch = qdrant_points[i:i + batch_size]
            await self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )
            logger.info(f"Upserted batch {i // batch_size + 1}: {len(batch)} points")
    
    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 10,
        score_threshold: float | None = None,
        document_ids: list[str] | None = None,
    ) -> SearchResults:
        """
        Perform semantic search with mandatory tenant filtering.
        
        Args:
            query_vector: The query embedding (1536 dims)
            tenant_id: REQUIRED. Only returns results for this tenant.
            limit: Maximum number of results
            score_threshold: Minimum similarity score (0.0-1.0)
            document_ids: Optional. Filter to specific documents.
        
        Returns:
            SearchResults with ranked results and metadata.
        
        TENANT ISOLATION:
        The tenant_id filter is ALWAYS applied.
        There is NO code path that skips this filter.
        This is a security-critical design decision.
        """
        # Build filter — tenant_id is ALWAYS required
        must_conditions = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id),
            )
        ]
        
        # Optional: filter by specific documents
        if document_ids:
            must_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            )
        
        search_filter = models.Filter(must=must_conditions)
        
        # Perform search
        start_time = time.time()
        
        threshold = (
            score_threshold
            if score_threshold is not None
            else getattr(settings, "search_score_threshold", 0.5)
        )
        
        response = await self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=search_filter,
            limit=limit,
            score_threshold=threshold,
            with_payload=True,
        )
        results = response.points
        
        search_time_ms = (time.time() - start_time) * 1000
        
        # Convert to our schema
        search_results = []
        for result in results:
            payload = result.payload or {}
            search_results.append(SearchResult(
                chunk_id=str(result.id),
                document_id=payload.get("document_id", ""),
                tenant_id=payload.get("tenant_id", ""),
                content=payload.get("content", ""),
                score=result.score,
                chunk_index=payload.get("chunk_index", 0),
                page_number=payload.get("page_number"),
                section_heading=payload.get("section_heading"),
                document_title=payload.get("document_title"),
                version=payload.get("version", 1),
                token_count=payload.get("token_count", 0),
                metadata=payload,
            ))
        
        return SearchResults(
            results=search_results,
            query="",  # Will be set by the search service
            total_found=len(search_results),
            search_time_ms=round(search_time_ms, 2),
        )
    
    async def delete_by_document(
        self,
        document_id: str,
        tenant_id: str,
    ) -> int:
        """
        Delete all vectors for a document.
        
        Used when:
        - Re-processing a document (delete old vectors, insert new)
        - Deleting a document
        
        Returns the number of points deleted.
        """
        result = await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        ),
                    ]
                )
            ),
        )
        logger.info(f"Deleted vectors for document {document_id}")
        return result.status  # type: ignore
    
    async def delete_by_tenant(self, tenant_id: str) -> None:
        """
        Delete ALL vectors for a tenant.
        
        Used when: Tenant account is deleted.
        This is a destructive operation — use with caution!
        """
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        ),
                    ]
                )
            ),
        )
        logger.warning(f"Deleted ALL vectors for tenant {tenant_id}")
    
    async def get_collection_info(self) -> dict:
        """Get collection statistics."""
        info = await self.client.get_collection(self.collection_name)
        return {
            "name": self.collection_name,
            # "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": info.status.value,
            "optimizer_status": str(info.optimizer_status),
        }
