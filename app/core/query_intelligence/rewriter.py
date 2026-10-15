"""
Query rewriter — transforms vague queries into search-friendly ones.

PROBLEM:
  User: "How does that compare?"
  → "that" = ??? "compare to what" = ???
  → Vector search gets garbage results.

SOLUTION:
  Use the LLM to rewrite the query:
  - Resolve pronouns using conversation history
  - Add specific entities (company names, dates)
  - Expand abbreviations
  - Make the query self-contained

THIS IS ONE OF THE HIGHEST-ROI TECHNIQUES IN RAG.
Simple to implement, massive quality improvement.
"""

import logging

from app.core.llm import LLMMessage, OpenAIClient

logger = logging.getLogger(__name__)


class QueryRewriter:
    """Rewrites user queries for better retrieval."""
    
    def __init__(self):
        # Use gpt-4o-mini for cost efficiency (rewriting is simple)
        self.llm = OpenAIClient(model="gpt-4o-mini")
    
    async def rewrite(
        self,
        query: str,
        chat_history: list[LLMMessage] | None = None,
    ) -> str:
        """
        Rewrite a query to be more search-friendly.
        
        WHEN TO REWRITE:
        - Query contains pronouns (it, that, this, they)
        - Query is very short (< 5 words)
        - Query has conversation history (follow-up question)
        
        WHEN NOT TO REWRITE:
        - Query is already specific and detailed
        - No conversation history (first question)
        - Query is a greeting or meta question
        """
        # Skip rewriting if query is already detailed (> 15 words)
        if len(query.split()) > 15 and not chat_history:
            return query
        
        # Skip if no history and no pronouns
        pronouns = {"it", "that", "this", "they", "them", "its", "those", "these"}
        query_words = set(query.lower().split())
        has_pronouns = bool(query_words & pronouns)
        
        if not has_pronouns and not chat_history:
            return query
        
        # Build rewriting prompt
        history_text = ""
        if chat_history:
            # Include last 4 messages for context
            recent = chat_history[-4:]
            history_text = "\n".join(
                f"{m.role.upper()}: {m.content}" for m in recent
            )
        
        prompt = f"""Rewrite the following query to be self-contained and search-friendly.

Rules:
1. Resolve all pronouns (it, that, this, they) using the conversation history.
2. Include specific entities (names, dates, numbers) from context.
3. Keep the rewritten query concise (under 30 words).
4. If the query is already clear and specific, return it unchanged.
5. Return ONLY the rewritten query, nothing else.

{f"Conversation history:{chr(10)}{history_text}{chr(10)}" if history_text else ""}
Original query: {query}

Rewritten query:"""
        
        try:
            response = await self.llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.0,
                max_tokens=100,
            )
            
            rewritten = response.content.strip().strip('"').strip("'")
            
            # Safety: if rewriting failed or produced something weird, use original
            if len(rewritten) < 3 or len(rewritten) > 500:
                return query
            
            logger.info(f"Query rewritten: '{query}' → '{rewritten}'")
            return rewritten
        
        except Exception as e:
            logger.warning(f"Query rewriting failed: {e}, using original")
            return query
