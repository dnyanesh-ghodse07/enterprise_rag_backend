"""
Embedding service — converts text into vectors using OpenAI.

WHAT THIS MODULE DOES:
- Takes text (a chunk or a question) and returns a vector
- Handles batching (send 100 texts at once, not 1 at a time)
- Handles rate limiting (don't exceed OpenAI's API limits)
- Handles errors (retries on transient failures)

WHY OPENAI EMBEDDINGS:
- text-embedding-3-small is the best price/performance
- 1536 dimensions is standard and well-supported
- $0.02 per 1M tokens (embedding 10,000 chunks ≈ $0.10)
- Consistent quality across languages

ALTERNATIVE: Run embeddings locally
- sentence-transformers (e.g., all-MiniLM-L6-v2)
- No API cost, but requires GPU for production speed
- Lower quality for multilingual text
- We may switch to local embeddings in Day 14 (cost optimization)
"""

import logging
from typing import Sequence

from openai import AsyncOpenAI

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings using OpenAI's API.
    
    USAGE:
        service = EmbeddingService()
        vector = await service.embed_text("What is machine learning?")
        vectors = await service.embed_batch(["text1", "text2", ...])
    """
    
    def __init__(self):
        """Initialize the OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
    
    async def embed_text(self, text: str) -> list[float]:
        """
        Embed a single text string.
        
        Used for:
        - Embedding a user's search query
        - Embedding a single chunk (testing)
        
        Returns a list of floats (the embedding vector).
        """
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise
    
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed multiple texts in batches.
        
        WHY BATCHING:
        - OpenAI's API accepts up to 2048 inputs per request
        - Sending 100 texts in one request is 100x faster than one-by-one
        - We batch by self.batch_size (default: 100)
        
        Rate limiting:
        - OpenAI allows ~3000 RPM (requests per minute) for embedding
        - With batch_size=100, that's 300,000 texts per minute
        - More than enough for our use case
        
        Returns a list of embedding vectors (same order as input).
        """
        if not texts:
            return []
        
        # Filter empty texts (keep track of indices)
        valid_texts = []
        valid_indices = []
        for i, text in enumerate(texts):
            if text.strip():
                valid_texts.append(text)
                valid_indices.append(i)
        
        if not valid_texts:
            return [[] for _ in texts]
        
        # Process in batches
        all_embeddings: list[list[float]] = [[] for _ in texts]
        
        for batch_start in range(0, len(valid_texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(valid_texts))
            batch = valid_texts[batch_start:batch_end]
            
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions,
                )
                
                # Map batch results back to original indices
                for j, embedding_data in enumerate(response.data):
                    original_idx = valid_indices[batch_start + j]
                    all_embeddings[original_idx] = embedding_data.embedding
                
                logger.info(
                    f"Embedded batch {batch_start // self.batch_size + 1}: "
                    f"{len(batch)} texts, "
                    f"{response.usage.total_tokens} tokens"
                )
            
            except Exception as e:
                logger.error(f"Batch embedding failed at index {batch_start}: {e}")
                raise
        
        return all_embeddings
    
    async def embed_query(self, query: str) -> list[float]:
        """
        Embed a search query.
        
        WHY A SEPARATE METHOD:
        Some embedding models have different modes for
        "document" vs "query" embedding.
        
        For text-embedding-3-small, they're the same.
        But for other models (e.g., E5), you'd prepend
        "query: " to the query text.
        
        Having a separate method lets us change the behavior
        without modifying search code.
        """
        return await self.embed_text(query)
