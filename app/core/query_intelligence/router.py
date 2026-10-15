"""
Query router — selects the appropriate RAG strategy based on query type.

THE ROUTER IS THE CONDUCTOR:
It doesn't play any instruments, but it tells each musician
(classifier, rewriter, search, compressor) when and how to play.

ROUTING TABLE:
  Query Type      → Pipeline Configuration
  ─────────────     ─────────────────────────
  conversational  → Direct response (no retrieval)
  meta            → Database query
  factual         → Rewrite → Search(top-3) → LLM
  analytical      → Rewrite → Multi-query → Search(top-8) → Compress → LLM
  comparison      → Rewrite → Multi-entity search → LLM
  summarization   → Search(top-10) → LLM with summary prompt
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.core.llm.base import LLMMessage
from app.core.query_intelligence.classifier import (
    QueryClassification,
    QueryType,
    classify_query,
)
from app.core.query_intelligence.rewriter import QueryRewriter
from app.core.query_intelligence.hyde import HyDEGenerator
from app.core.query_intelligence.multi_query import MultiQueryGenerator
from app.core.query_intelligence.compressor import ContextualCompressor

logger = logging.getLogger(__name__)


@dataclass
class QueryPlan:
    """
    Execution plan for a query.
    
    The router creates this plan, and the RAG service executes it.
    """
    original_query: str
    rewritten_query: str
    classification: QueryClassification
    search_queries: list[str] = field(default_factory=list)
    use_hyde: bool = False
    use_compression: bool = False
    use_multi_query: bool = False
    skip_retrieval: bool = False
    num_chunks: int = 5
    temperature: float = 0.1
    direct_response: str | None = None  # For conversational queries


class QueryRouter:
    """
    Routes queries to the appropriate RAG strategy.
    
    USAGE:
        router = QueryRouter()
        plan = await router.plan(query, chat_history)
        # Then execute the plan in the RAG service
    """
    
    def __init__(self):
        self.rewriter = QueryRewriter()
        self.hyde_generator = HyDEGenerator()
        self.multi_query_gen = MultiQueryGenerator()
    
    async def plan(
        self,
        query: str,
        chat_history: list[LLMMessage] | None = None,
    ) -> QueryPlan:
        """
        Analyze a query and create an execution plan.
        
        Steps:
        1. Classify the query
        2. Decide which techniques to apply
        3. Rewrite if needed
        4. Generate search queries
        5. Return the plan
        """
        # ─── Step 1: Classify ─────────────────────────────────
        classification = classify_query(query)
        
        logger.info(
            f"Query classified: type={classification.query_type.value}, "
            f"confidence={classification.confidence}"
        )
        
        # ─── Step 2: Handle non-retrieval types ───────────────
        if classification.query_type == QueryType.CONVERSATIONAL:
            return QueryPlan(
                original_query=query,
                rewritten_query=query,
                classification=classification,
                skip_retrieval=True,
                direct_response=self._get_conversational_response(query),
            )
        
        if classification.query_type == QueryType.META:
            return QueryPlan(
                original_query=query,
                rewritten_query=query,
                classification=classification,
                skip_retrieval=True,
                # Meta queries handled by the RAG service via DB
            )
        
        # ─── Step 3: Rewrite query ────────────────────────────
        rewritten = await self.rewriter.rewrite(query, chat_history)
        
        # ─── Step 4: Build plan based on type ─────────────────
        plan = QueryPlan(
            original_query=query,
            rewritten_query=rewritten,
            classification=classification,
            search_queries=[rewritten],
            num_chunks=classification.suggested_chunks,
            temperature=classification.suggested_temperature,
        )
        
        if classification.query_type == QueryType.ANALYTICAL:
            # Analytical: multi-query for broader coverage + compression
            plan.use_multi_query = True
            plan.use_compression = True
            multi_queries = await self.multi_query_gen.generate_queries(
                rewritten, num_queries=3
            )
            plan.search_queries = multi_queries
        
        elif classification.query_type == QueryType.COMPARISON:
            # Comparison: multi-query for different entities
            plan.use_multi_query = True
            multi_queries = await self.multi_query_gen.generate_queries(
                rewritten, num_queries=3
            )
            plan.search_queries = multi_queries
        
        elif classification.query_type == QueryType.SUMMARIZATION:
            # Summary: broad retrieval, no compression (need full context)
            plan.num_chunks = 10
        
        elif classification.query_type == QueryType.FACTUAL:
            # Factual: simple search, maybe HyDE for vague queries
            if len(query.split()) < 6:  # Short queries benefit from HyDE
                plan.use_hyde = True
        
        return plan
    
    def _get_conversational_response(self, query: str) -> str:
        """Generate a friendly response for conversational queries."""
        query_lower = query.lower().strip()
        
        if any(g in query_lower for g in ["hello", "hi", "hey"]):
            return (
                "Hello! I'm Cognix AI, your knowledge assistant. "
                "I can help you find information in your documents. "
                "What would you like to know?"
            )
        elif any(g in query_lower for g in ["thank", "thanks", "thx"]):
            return (
                "You're welcome! Let me know if you have any other "
                "questions about your documents."
            )
        elif any(g in query_lower for g in ["bye", "goodbye"]):
            return (
                "Goodbye! Feel free to come back anytime you need "
                "help with your documents."
            )
        else:
            return (
                "I'm here to help you find information in your documents. "
                "Feel free to ask me any question!"
            )
