"""
Processing service — triggers and manages document processing.

CURRENT APPROACH: Synchronous processing (process during request).
FUTURE APPROACH: Background tasks with Celery (Day 14).

For now, we process documents inline. This is fine for development
and small documents. For production:
- Large documents (>10 pages) → background task
- Batch uploads → queue with priority
- Failures → retry with exponential backoff
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.processing.pipeline import ProcessingPipeline
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class ProcessingService:
    """Service for document text processing."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.pipeline = ProcessingPipeline(db)
    
    async def process_document(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """
        Process a single document.
        
        Extracts text, chunks it, and saves chunks to the database.
        """
        return await self.pipeline.process(document_id, tenant_id)
    
    async def get_chunks(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[dict]:
        """Get all chunks for a document."""
        result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = result.scalars().all()
        
        return [
            {
                "id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "page_number": chunk.page_number,
                "section_heading": chunk.section_heading,
                "version": chunk.version,
            }
            for chunk in chunks
        ]
    
    async def get_processing_status(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """Get the processing status of a document."""
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        doc = result.scalar_one_or_none()
        
        if not doc:
            return {"error": "Document not found"}
        
        # Count chunks
        count_result = await self.db.execute(
            select(func.count()).where(
                DocumentChunk.document_id == document_id
            )
        )
        chunk_count = count_result.scalar() or 0
        
        # Sum tokens
        token_result = await self.db.execute(
            select(func.sum(DocumentChunk.token_count)).where(
                DocumentChunk.document_id == document_id
            )
        )
        total_tokens = token_result.scalar() or 0
        
        return {
            "document_id": str(document_id),
            "status": doc.status.value,
            "chunks": chunk_count,
            "total_tokens": total_tokens,
            "current_version": doc.current_version,
        }
