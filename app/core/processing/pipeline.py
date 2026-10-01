"""
Document processing pipeline — orchestrates extraction and chunking.

THE PIPELINE PATTERN:
Each step in the pipeline:
1. Receives input from the previous step
2. Processes it
3. Passes output to the next step
4. Handles errors without crashing the whole pipeline

PIPELINE STEPS:
  Read file → Extract text → Chunk → Save chunks → Update status
"""

import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.processing.chunker import ChunkingEngine
from app.core.processing.extractors import get_extractor
from app.core.storage import get_storage
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class ProcessingPipeline:
    """
    Orchestrates the complete document processing flow.

    USAGE:
        pipeline = ProcessingPipeline(db)
        result = await pipeline.process(document_id, tenant_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage()
        self.chunker = ChunkingEngine()

    async def process(self, document_id: UUID, tenant_id: UUID) -> dict:
        """
        Process a document: extract text, chunk, and save.

        Returns a summary dict with processing results.
        """
        from sqlalchemy import select

        # ─── Step 1: Load document ────────────────────────────
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        document = result.scalar_one_or_none()

        if not document:
            return {"success": False, "error": "Document not found"}

        # Update status to processing
        document.status = DocumentStatus.PROCESSING
        await self.db.commit()

        try:
            # ─── Step 2: Read file from storage ───────────────
            logger.info(f"Reading file from storage: {document.storage_key}")
            file_content = await self.storage.get(document.storage_key)

            # ─── Step 3: Extract text ─────────────────────────
            logger.info(f"Extracting text from {document.mime_type}")
            # return extractor as per mime type
            extractor = get_extractor(document.mime_type)

            if not extractor:
                document.status = DocumentStatus.ERROR
                await self.db.commit()
                return {
                    "success": False,
                    "error": f"No extractor available for {document.mime_type}",
                }

            extraction = await extractor.extract(file_content, document.filename)

            if not extraction.success:
                document.status = DocumentStatus.ERROR
                await self.db.commit()
                return {
                    "success": False,
                    "error": extraction.error or "Text extraction failed",
                }

            if extraction.is_empty:
                document.status = DocumentStatus.ERROR
                await self.db.commit()
                return {
                    "success": False,
                    "error": "No text content found in document",
                }

            logger.info(
                f"Extracted {extraction.total_characters} chars "
                f"from {extraction.total_pages} pages"
            )

            # ─── Step 4: Chunk text ───────────────────────────
            logger.info("Chunking text...")
            chunks = self.chunker.chunk(extraction)

            if not chunks:
                document.status = DocumentStatus.ERROR
                await self.db.commit()
                return {
                    "success": False,
                    "error": "Chunking produced no chunks",
                }

            logger.info(f"Created {len(chunks)} chunks")

            # ─── Step 5: Delete old chunks ────────────────────
            # Remove chunks from previous version
            await self.db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

            # ─── Step 6: Save new chunks ──────────────────────
            chunk_models = []
            for chunk in chunks:
                chunk_model = DocumentChunk(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    version=document.current_version,
                    checksum=chunk.checksum,
                    metadata=chunk.metadata,
                )
                chunk_models.append(chunk_model)

            self.db.add_all(chunk_models)

            # ─── Step 7: Update document status ───────────────
            document.status = DocumentStatus.READY
            await self.db.commit()

            total_tokens = sum(c.token_count for c in chunks)
            avg_tokens = total_tokens // len(chunks) if chunks else 0

            logger.info(
                f"Processing complete: {len(chunks)} chunks, "
                f"{total_tokens} total tokens, "
                f"{avg_tokens} avg tokens/chunk"
            )

            return {
                "success": True,
                "document_id": str(document_id),
                "chunks_created": len(chunks),
                "total_tokens": total_tokens,
                "avg_tokens_per_chunk": avg_tokens,
                "total_characters": extraction.total_characters,
                "total_pages": extraction.total_pages,
                "extraction_metadata": extraction.metadata,
            }

        except Exception as e:
            logger.error(f"Processing failed for document {document_id}: {e}")
            # Rollback the aborted transaction before issuing new SQL.
            # PostgreSQL marks the transaction as aborted on any error, so
            # any subsequent statement (including our status update) will raise
            # InFailedSQLTransactionError unless we rollback first.
            await self.db.rollback()
            try:
                document.status = DocumentStatus.ERROR
                await self.db.commit()
            except Exception as update_err:
                logger.error(
                    f"Failed to update document {document_id} status to ERROR: {update_err}"
                )
                await self.db.rollback()
            return {
                "success": False,
                "error": f"Processing failed: {str(e)}",
            }
