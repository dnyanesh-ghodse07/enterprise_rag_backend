"""
Abstract base class for LLM clients.

WHY ABSTRACTION:
Today we use OpenAI GPT-4o. Tomorrow we might use:
- Anthropic Claude (better for long documents)
- Google Gemini (better multimodal)
- Local Llama (zero cost, data privacy)
- Azure OpenAI (enterprise compliance)

The application code says: llm.generate(prompt)
It never knows which model is behind the scenes.

This is the STRATEGY PATTERN (same pattern as file storage in Day 3):
  Interface → OpenAIClient, AnthropicClient, LocalClient
  
  The RAG chain calls the interface.
  Configuration determines which implementation is used.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMMessage:
    """
    A single message in a conversation.
    
    Roles:
    - "system": Instructions for the LLM (how to behave)
    - "user": The human's message
    - "assistant": The LLM's previous response
    """
    role: str   # "system", "user", or "assistant"
    content: str


@dataclass
class LLMResponse:
    """
    Response from the LLM.
    
    Contains the generated text and usage statistics
    for cost tracking and debugging.
    """
    content: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""  # "stop", "length", "content_filter"
    
    @property
    def cost_estimate(self) -> float:
        """Estimate cost in USD (GPT-4o pricing)."""
        input_cost = self.input_tokens * 2.50 / 1_000_000
        output_cost = self.output_tokens * 10.00 / 1_000_000
        return input_cost + output_cost


class BaseLLMClient(ABC):
    """
    Abstract interface for LLM clients.
    
    All implementations must support:
    - generate(): Complete response (wait for full output)
    - stream(): Token-by-token streaming
    """
    
    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        """
        Generate a complete response.
        
        Used when:
        - You need the full response before processing
        - Background tasks (no user waiting)
        - Testing and evaluation
        """
        ...
    
    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens one at a time.
        
        Used when:
        - User is waiting for an answer (real-time UX)
        - The API endpoint returns SSE
        
        Yields individual tokens (or small chunks) as strings.
        """
        ...
