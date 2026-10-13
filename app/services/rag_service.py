"""
RAG Chain Service — The heart of Cognix AI.

THIS IS WHERE EVERYTHING COMES TOGETHER:
  Search (Day 5) + Prompt Builder (Today) + LLM (Today) = RAG

THE RAG CHAIN:
1. Load conversation history (memory)
2. Search for relevant chunks (retrieval)
3. Build the prompt (augmentation)
4. Call the LLM (generation)
5. Save to history (memory update)
6. Return response with sources

TWO MODES:
- Complete: Wait for full response, return JSON
- Streaming: Stream tokens via SSE, return chunk-by-chunk
"""

import json
import logging
import time
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.llm import LLMMessage, OpenAIClient, PromptBuilder
from app.core.vector_store.schemas import SearchResult
from app.services.conversation_service import ConversationService
from app.services.search_service import SearchService

settings = get_settings()
logger = logging.getLogger(__name__)


class RAGService:
    """
    Retrieval-Augmented Generation service.
    
    Orchestrates the complete RAG chain:
    question → search → prompt → LLM → answer
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.search = SearchService(db)
        self.conversation_svc = ConversationService(db)
        self.prompt_builder = PromptBuilder()
        self.llm = OpenAIClient()
    
    async def ask(
        self,
        question: str,
        user_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> dict:
        """
        Ask a question and get a complete (non-streamed) answer.
        
        Returns the full response with sources and metadata.
        """
        start_time = time.time()
        
        # ─── Step 1: Load or create conversation ─────────────
        conversation = await self.conversation_svc.get_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        
        # ─── Step 2: Get conversation history ─────────────────
        chat_history = self.conversation_svc.get_history_as_messages(
            conversation
        )
        
        # ─── Step 3: Search for relevant chunks ──────────────
        search_results = await self.search.semantic_search(
            query=question,
            tenant_id=tenant_id,
            limit=settings.rag_top_k,
            score_threshold=settings.rag_score_threshold,
            document_ids=document_ids,
        )
        
        # ─── Step 4: Build prompt ─────────────────────────────
        messages = self.prompt_builder.build(
            question=question,
            search_results=search_results.results,
            chat_history=chat_history,
        )
        
        # ─── Step 5: Call LLM ─────────────────────────────────
        llm_response = await self.llm.generate(
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        
        # ─── Step 6: Save messages to conversation ────────────
        # Save user message
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="user",
            content=question,
        )
        
        # Save assistant response
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="assistant",
            content=llm_response.content,
            sources_used=len(search_results.results),
            model_used=llm_response.model,
        )
        
        await self.db.commit()
        
        # ─── Step 7: Format response ─────────────────────────
        total_time = time.time() - start_time
        
        sources = [
            {
                "index": i + 1,
                "document_id": r.document_id,
                "document_title": r.document_title,
                "page_number": r.page_number,
                "section_heading": r.section_heading,
                "relevance_score": round(r.score, 3),
            }
            for i, r in enumerate(search_results.results)
        ]
        
        return {
            "answer": llm_response.content,
            "conversation_id": str(conversation.id),
            "sources": sources,
            "metadata": {
                "model": llm_response.model,
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "total_tokens": llm_response.total_tokens,
                "cost_estimate": round(llm_response.cost_estimate, 6),
                "search_time_ms": search_results.search_time_ms,
                "total_time_ms": round(total_time * 1000, 2),
                "chunks_retrieved": len(search_results.results),
            },
        }
    
    async def ask_stream(
        self,
        question: str,
        user_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> AsyncIterator[str]:
        """
        Ask a question and stream the answer token-by-token.
        
        Yields SSE-formatted events:
          data: {"type": "source", "sources": [...]}
          data: {"type": "token", "content": "word"}
          data: {"type": "done", "metadata": {...}}
        
        The client receives each token in real-time,
        creating a typewriter effect.
        """
        # ─── Steps 1-4: Same as complete mode ─────────────────
        conversation = await self.conversation_svc.get_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        
        chat_history = self.conversation_svc.get_history_as_messages(
            conversation
        )
        
        search_results = await self.search.semantic_search(
            query=question,
            tenant_id=tenant_id,
            limit=settings.rag_top_k,
            score_threshold=settings.rag_score_threshold,
            document_ids=document_ids,
        )
        
        messages = self.prompt_builder.build(
            question=question,
            search_results=search_results.results,
            chat_history=chat_history,
        )
        
        # ─── Send sources first ───────────────────────────────
        sources = [
            {
                "index": i + 1,
                "document_id": r.document_id,
                "document_title": r.document_title,
                "page_number": r.page_number,
                "section_heading": r.section_heading,
                "relevance_score": round(r.score, 3),
            }
            for i, r in enumerate(search_results.results)
        ]
        
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        
        # ─── Stream LLM tokens ────────────────────────────────
        full_response = []
        
        async for token in self.llm.stream(
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        ):
            full_response.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        
        # ─── Save to conversation history ─────────────────────
        complete_answer = "".join(full_response)
        
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="user",
            content=question,
        )
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="assistant",
            content=complete_answer,
            sources_used=len(search_results.results),
            model_used=settings.llm_model,
        )
        await self.db.commit()
        
        # ─── Send completion event ────────────────────────────
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id)})}\n\n"
