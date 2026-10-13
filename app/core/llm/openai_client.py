"""
OpenAI GPT client implementation.

USES:
- GPT-4o for high-quality RAG answers
- Async API for non-blocking requests
- Streaming for real-time responses

COST AWARENESS:
  GPT-4o: $2.50/M input, $10.00/M output
  A typical RAG query uses ~6000 input + ~500 output tokens
  Cost per query: ~$0.02 (2 cents)
  
  GPT-4o-mini: $0.15/M input, $0.60/M output
  Same query: ~$0.001 (0.1 cents) — 20x cheaper!
  Quality: ~90% of GPT-4o for most RAG tasks
  
  STRATEGY: Use GPT-4o-mini for most queries,
  GPT-4o for complex reasoning or when quality matters.
"""

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import get_settings
from app.core.llm.base import BaseLLMClient, LLMMessage, LLMResponse

settings = get_settings()
logger = logging.getLogger(__name__)


class OpenAIClient(BaseLLMClient):
    """
    OpenAI GPT client for text generation.
    
    Supports both complete generation and streaming.
    """
    
    def __init__(self, model: str | None = None):
        """Initialize the OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.llm_model
    
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        """
        Generate a complete response from OpenAI.
        
        Waits for the full response before returning.
        Used for background processing and testing.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": m.role, "content": m.content}
                    for m in messages
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=settings.llm_top_p,
            )
            
            choice = response.choices[0]
            usage = response.usage
            
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                finish_reason=choice.finish_reason or "",
            )
        
        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            raise
    
    async def stream(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from OpenAI.
        
        HOW OPENAI STREAMING WORKS:
        1. We call the API with stream=True
        2. OpenAI returns chunks as they're generated
        3. Each chunk contains 1-3 tokens
        4. We yield each token to the caller
        5. Caller sends tokens to the client via SSE
        
        The async for loop receives chunks in real-time.
        """
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": m.role, "content": m.content}
                    for m in messages
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=settings.llm_top_p,
                stream=True,
            )
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        
        except Exception as e:
            logger.error(f"OpenAI streaming failed: {e}")
            raise
