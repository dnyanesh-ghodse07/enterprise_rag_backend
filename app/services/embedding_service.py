"""
Embedding service — orchestrates chunk embedding and Qdrant storage.

RESPONSIBILITIES:
- Load chunks from PostgreSQL
- Embed them via OpenAI
- Store vectors in Qdrant with metadata
- Handle re-embedding (delete old, insert new)
- Track embedding status

THIS IS THE BRIDGE BETWEEN:
  PostgreSQL (chunks) → OpenAI (embeddings) → Qdrant (vectors)
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingService
from app.core.vector_store import QdrantService
from app.models.document import Document
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class ChunkEmbeddingService:
    """
    Embeds document chunks and stores them in Qdrant.
    
    WORKFLOW:
    1. Load chunks from PostgreSQL (for a specific document)
    2. Batch embed via OpenAI
    3. Delete old vectors in Qdrant (if re-processing)
    4. Upsert new vectors with metadata payload
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = EmbeddingService()
        self.qdrant = QdrantService()
    
    async def embed_document_chunks(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """
        Embed all chunks for a document and store in Qdrant.
        
        Returns a summary dict with embedding results.
        """
        # ─── Step 1: Load chunks from PostgreSQL ──────────────
        result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = result.scalars().all()
        
        if not chunks:
            return {
                "success": False,
                "error": "No chunks found. Process the document first.",
            }
        
        # ─── Step 2: Load document metadata ───────────────────
        doc_result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = doc_result.scalar_one_or_none()
        doc_title = document.title if document else "Unknown"
        
        # ─── Step 3: Extract text for embedding ───────────────
        texts = [chunk.content for chunk in chunks]
        
        logger.info(
            f"Embedding {len(texts)} chunks for document {document_id}"
        )
        
        # ─── Step 4: Batch embed via OpenAI ───────────────────
        try:
            vectors = await self.embedder.embed_batch(texts)
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return {
                "success": False,
                "error": f"Embedding API call failed: {str(e)}",
            }
        
        # ─── Step 5: Delete old vectors in Qdrant ─────────────
        await self.qdrant.delete_by_document(
            document_id=str(document_id),
            tenant_id=str(tenant_id),
        )
        
        # ─── Step 6: Prepare Qdrant points ────────────────────
        points = []
        for chunk, vector in zip(chunks, vectors):
            if not vector:  # Skip empty embeddings
                continue
            
            points.append({
                "id": str(chunk.id),
                "vector": vector,
                "payload": {
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                    "section_heading": chunk.section_heading,
                    "document_title": doc_title,
                    "version": chunk.version,
                    "token_count": chunk.token_count,
                },
            })
        
        # ─── Step 7: Upsert to Qdrant ────────────────────────
        if points:
            await self.qdrant.upsert_chunks(points)
        
        logger.info(
            f"Embedded and stored {len(points)} vectors for document {document_id}"
        )
        
        return {
            "success": True,
            "document_id": str(document_id),
            "chunks_embedded": len(points),
            "total_chunks": len(chunks),
            "skipped": len(chunks) - len(points),
        }
    
    async def embed_and_process(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """
        Full pipeline: process document (extract + chunk) then embed.
        
        Combines Day 4's processing with today's embedding.
        """
        from app.core.processing.pipeline import ProcessingPipeline
        
        # Step 1: Process (extract + chunk)
        pipeline = ProcessingPipeline(self.db)
        process_result = await pipeline.process(document_id, tenant_id)
        
        if not process_result.get("success"):
            return process_result
        
        # Step 2: Embed
        embed_result = await self.embed_document_chunks(document_id, tenant_id)
        
        # Combine results
        return {
            **process_result,
            **embed_result,
            "pipeline": "extract → chunk → embed → store",
        }
