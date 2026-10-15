"""
Enhanced RAG service with query intelligence.

UPGRADES FROM DAY 6:
1. Query classification → adapts strategy per question
2. Query rewriting → better search for follow-ups
3. Multi-query retrieval → broader coverage
4. HyDE → better embeddings for vague queries
5. Contextual compression → less noise in context
6. Conversational handling → no unnecessary search
"""

import json
import logging
import time
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embeddings import EmbeddingService
from app.core.llm import LLMMessage, OpenAIClient, PromptBuilder
from app.core.query_intelligence import (
    ContextualCompressor,
    HyDEGenerator,
    QueryPlan,
    QueryRouter,
    QueryType,
)
from app.core.vector_store import QdrantService
from app.core.vector_store.schemas import SearchResult, SearchResults
from app.services.conversation_service import ConversationService
from app.services.search_service import SearchService

settings = get_settings()
logger = logging.getLogger(__name__)


class RAGService:
    """
    Enhanced RAG service with query intelligence.
    
    Pipeline:
    1. Classify query → determine strategy
    2. Rewrite query → improve search quality
    3. Retrieve → search with optimal strategy
    4. Post-process → compress, re-rank
    5. Generate → LLM with optimized context
    6. Persist → save to conversation history
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.search = SearchService(db)
        self.conversation_svc = ConversationService(db)
        self.prompt_builder = PromptBuilder()
        self.llm = OpenAIClient()
        self.router = QueryRouter()
        self.compressor = ContextualCompressor()
        self.hyde = HyDEGenerator()
        self.embedder = EmbeddingService()
        self.qdrant = QdrantService()
    
    async def ask(
        self,
        question: str,
        user_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> dict:
        """
        Ask a question with intelligent query processing.
        
        Enhanced flow:
        1. Load conversation
        2. Route query (classify + rewrite + plan)
        3. Execute retrieval strategy
        4. Post-process results
        5. Generate answer
        6. Save history
        """
        start_time = time.time()
        
        # ─── Step 1: Load conversation ────────────────────────
        conversation = await self.conversation_svc.get_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        
        chat_history = self.conversation_svc.get_history_as_messages(
            conversation
        )
        
        # ─── Step 2: Route query ──────────────────────────────
        plan = await self.router.plan(question, chat_history)
        
        logger.info(
            f"Query plan: type={plan.classification.query_type.value}, "
            f"chunks={plan.num_chunks}, "
            f"multi_query={plan.use_multi_query}, "
            f"hyde={plan.use_hyde}, "
            f"compress={plan.use_compression}"
        )
        
        # ─── Step 3: Handle non-retrieval queries ─────────────
        if plan.skip_retrieval and plan.direct_response:
            # Conversational — respond directly
            await self.conversation_svc.add_message(
                conversation=conversation,
                role="user",
                content=question,
            )
            await self.conversation_svc.add_message(
                conversation=conversation,
                role="assistant",
                content=plan.direct_response,
            )
            await self.db.commit()
            
            return {
                "answer": plan.direct_response,
                "conversation_id": str(conversation.id),
                "sources": [],
                "metadata": {
                    "query_type": plan.classification.query_type.value,
                    "total_time_ms": round((time.time() - start_time) * 1000, 2),
                    "retrieval_skipped": True,
                },
            }
        
        # ─── Step 4: Execute retrieval ────────────────────────
        all_results = await self._execute_retrieval(
            plan=plan,
            tenant_id=tenant_id,
            document_ids=document_ids,
        )
        
        # ─── Step 5: Post-process results ─────────────────────
        if plan.use_compression and all_results:
            all_results = await self.compressor.compress(
                plan.rewritten_query, all_results
            )
        
        # Deduplicate results by chunk_id
        seen_ids = set()
        unique_results = []
        for r in all_results:
            if r.chunk_id not in seen_ids:
                seen_ids.add(r.chunk_id)
                unique_results.append(r)
        
        # Limit to planned chunk count
        final_results = unique_results[:plan.num_chunks]
        
        # ─── Step 6: Build prompt and generate ────────────────
        messages = self.prompt_builder.build(
            question=plan.rewritten_query,
            search_results=final_results,
            chat_history=chat_history,
        )
        
        llm_response = await self.llm.generate(
            messages=messages,
            temperature=plan.temperature,
            max_tokens=settings.llm_max_tokens,
        )
        
        # ─── Step 7: Save to history ──────────────────────────
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="user",
            content=question,
        )
        await self.conversation_svc.add_message(
            conversation=conversation,
            role="assistant",
            content=llm_response.content,
            sources_used=len(final_results),
            model_used=llm_response.model,
        )
        await self.db.commit()
        
        # ─── Step 8: Format response ─────────────────────────
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
            for i, r in enumerate(final_results)
        ]
        
        return {
            "answer": llm_response.content,
            "conversation_id": str(conversation.id),
            "sources": sources,
            "metadata": {
                "model": llm_response.model,
                "query_type": plan.classification.query_type.value,
                "rewritten_query": plan.rewritten_query,
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "total_tokens": llm_response.total_tokens,
                "cost_estimate": round(llm_response.cost_estimate, 6),
                "total_time_ms": round(total_time * 1000, 2),
                "chunks_retrieved": len(final_results),
                "multi_query_used": plan.use_multi_query,
                "hyde_used": plan.use_hyde,
                "compression_used": plan.use_compression,
            },
        }
    
    async def _execute_retrieval(
        self,
        plan: QueryPlan,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> list[SearchResult]:
        """
        Execute the retrieval strategy defined in the query plan.
        
        Supports:
        - Standard single-query search
        - Multi-query search (union of multiple queries)
        - HyDE-enhanced search
        """
        all_results: list[SearchResult] = []
        doc_id_strs = [str(d) for d in document_ids] if document_ids else None
        
        if plan.use_hyde:
            # HyDE: embed hypothetical answer instead of question
            hyde_vector = await self.hyde.get_hyde_embedding(
                plan.rewritten_query
            )
            
            results = await self.qdrant.search(
                query_vector=hyde_vector,
                tenant_id=str(tenant_id),
                limit=plan.num_chunks,
                document_ids=doc_id_strs,
            )
            all_results.extend(results.results)
        
        # Search with each query
        for query in plan.search_queries:
            results = await self.search.semantic_search(
                query=query,
                tenant_id=tenant_id,
                limit=plan.num_chunks,
                document_ids=document_ids,
            )
            all_results.extend(results.results)
        
        # Sort all results by score (descending)
        all_results.sort(key=lambda r: r.score, reverse=True)
        
        return all_results
    
    async def ask_stream(
        self,
        question: str,
        user_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream version of ask with query intelligence.
        
        Same query planning but with streamed LLM output.
        """
        # ─── Steps 1-5: Same as complete mode ─────────────────
        conversation = await self.conversation_svc.get_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        
        chat_history = self.conversation_svc.get_history_as_messages(
            conversation
        )
        
        plan = await self.router.plan(question, chat_history)
        
        # Send query plan info
        yield f"data: {json.dumps({'type': 'plan', 'query_type': plan.classification.query_type.value, 'rewritten_query': plan.rewritten_query})}\n\n"
        
        # Handle non-retrieval queries
        if plan.skip_retrieval and plan.direct_response:
            await self.conversation_svc.add_message(
                conversation=conversation, role="user", content=question,
            )
            await self.conversation_svc.add_message(
                conversation=conversation, role="assistant",
                content=plan.direct_response,
            )
            await self.db.commit()
            
            yield f"data: {json.dumps({'type': 'token', 'content': plan.direct_response})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id)})}\n\n"
            return
        
        # Execute retrieval
        all_results = await self._execute_retrieval(
            plan=plan, tenant_id=tenant_id, document_ids=document_ids,
        )
        
        if plan.use_compression and all_results:
            all_results = await self.compressor.compress(
                plan.rewritten_query, all_results
            )
        
        # Deduplicate and limit
        seen_ids = set()
        final_results = []
        for r in all_results:
            if r.chunk_id not in seen_ids:
                seen_ids.add(r.chunk_id)
                final_results.append(r)
            if len(final_results) >= plan.num_chunks:
                break
        
        # Send sources
        sources = [
            {
                "index": i + 1,
                "document_id": r.document_id,
                "document_title": r.document_title,
                "page_number": r.page_number,
                "section_heading": r.section_heading,
                "relevance_score": round(r.score, 3),
            }
            for i, r in enumerate(final_results)
        ]
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        
        # Build prompt and stream
        messages = self.prompt_builder.build(
            question=plan.rewritten_query,
            search_results=final_results,
            chat_history=chat_history,
        )
        
        full_response = []
        async for token in self.llm.stream(
            messages=messages,
            temperature=plan.temperature,
            max_tokens=settings.llm_max_response_tokens,
        ):
            full_response.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        
        # Save to history
        complete_answer = "".join(full_response)
        await self.conversation_svc.add_message(
            conversation=conversation, role="user", content=question,
        )
        await self.conversation_svc.add_message(
            conversation=conversation, role="assistant",
            content=complete_answer, sources_used=len(final_results),
            model_used=settings.llm_model,
        )
        await self.db.commit()
        
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id)})}\n\n"
