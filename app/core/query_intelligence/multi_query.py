"""
Multi-query retrieval — generate multiple search queries for broader coverage.

PROBLEM:
A single query might miss relevant chunks that use different terminology.
"What caused revenue growth?" misses chunks about "market expansion" or
"new product launch" that don't mention "revenue growth" directly.

SOLUTION:
Generate 3-5 different phrasings of the same question.
Search with ALL of them. Union the results. Deduplicate.

This casts a wider retrieval net without sacrificing precision.
"""

import json
import logging

from app.core.llm import LLMMessage, OpenAIClient

logger = logging.getLogger(__name__)


class MultiQueryGenerator:
    """Generates multiple search queries from a single question."""
    
    def __init__(self):
        self.llm = OpenAIClient(model="gpt-4o-mini")
    
    async def generate_queries(
        self,
        query: str,
        num_queries: int = 3,
    ) -> list[str]:
        """
        Generate multiple search queries for broader retrieval.
        
        Given a user question, generates different phrasings that
        might match different relevant chunks.
        
        Args:
            query: The original user question
            num_queries: Number of alternative queries to generate
        
        Returns:
            List of queries (including the original)
        """
        prompt = f"""Generate {num_queries} different search queries that would help find information to answer this question. 
Each query should approach the topic from a different angle or use different keywords.

Original question: {query}

Return ONLY a JSON array of strings, like:
["query 1", "query 2", "query 3"]"""
        
        try:
            response = await self.llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.4,
                max_tokens=200,
            )
            
            # Parse the JSON array
            queries = json.loads(response.content)
            
            if not isinstance(queries, list):
                return [query]
            
            # Always include the original query
            all_queries = [query] + [q for q in queries if q != query]
            
            logger.info(
                f"Multi-query: '{query}' → {len(all_queries)} queries"
            )
            
            return all_queries[:num_queries + 1]  # Cap at num_queries + original
        
        except Exception as e:
            logger.warning(f"Multi-query generation failed: {e}")
            return [query]
