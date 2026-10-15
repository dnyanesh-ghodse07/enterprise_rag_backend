"""
HyDE — Hypothetical Document Embeddings.

CONCEPT:
Instead of embedding the QUESTION and searching for similar documents,
we generate a HYPOTHETICAL ANSWER and search for documents similar to it.

WHY THIS WORKS:
The hypothetical answer uses the same language patterns as real documents.
"Revenue grew by 3% in Q4" is more similar to actual document text
than "What was the revenue growth?" is.

WHEN TO USE:
- Vague or abstract queries ("tell me about growth trends")
- Queries that use question language, not document language
- When standard search returns low-quality results

WHEN NOT TO USE:
- Specific factual queries ("What was Q4 revenue?")
- Already high-quality search results
- Meta questions ("What documents do I have?")

COST:
- One additional LLM call (gpt-4o-mini): ~$0.0005
- One additional embedding call: ~$0.00001
- Total: ~$0.0005 per query

REFERENCE:
  Paper: "Precise Zero-Shot Dense Retrieval without Relevance Labels"
  Authors: Gao et al., 2022 (Carnegie Mellon University)
"""

import logging

from app.core.embeddings import EmbeddingService
from app.core.llm import LLMMessage, OpenAIClient

logger = logging.getLogger(__name__)


class HyDEGenerator:
    """Generates hypothetical document embeddings for better retrieval."""
    
    def __init__(self):
        self.llm = OpenAIClient(model="gpt-4o-mini")
        self.embedder = EmbeddingService()
    
    async def generate_hypothetical_answer(self, query: str) -> str:
        """
        Generate a hypothetical answer to the query.
        
        The answer doesn't need to be factually correct.
        It just needs to USE THE SAME LANGUAGE as real documents.
        """
        prompt = f"""Write a brief passage that would answer this question. 
The passage should sound like it comes from a professional business document.
Write 2-3 sentences using specific, document-like language.
Do NOT say "I don't know" — write what a real document WOULD say.

Question: {query}

Passage:"""
        
        try:
            response = await self.llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,  # Slightly creative for diverse language
                max_tokens=150,
            )
            
            hypothetical = response.content.strip()
            logger.info(f"HyDE generated: '{hypothetical[:100]}...'")
            return hypothetical
        
        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}")
            return query  # Fallback to original query
    
    async def get_hyde_embedding(self, query: str) -> list[float]:
        """
        Generate a HyDE embedding:
        1. Generate hypothetical answer
        2. Embed the hypothetical answer
        3. Return the embedding (used instead of query embedding)
        """
        hypothetical = await self.generate_hypothetical_answer(query)
        embedding = await self.embedder.embed_text(hypothetical)
        return embedding
