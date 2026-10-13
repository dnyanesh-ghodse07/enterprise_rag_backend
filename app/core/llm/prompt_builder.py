"""
RAG prompt builder — constructs the perfect prompt for grounded answers.

THIS IS WHERE RAG QUALITY IS WON OR LOST.

The prompt builder:
1. Creates the system message (AI behavior instructions)
2. Formats retrieved chunks as numbered context
3. Manages conversation history within token budget
4. Constructs the final message list for the LLM

PROMPT STRUCTURE:
  [System]   → How to behave, citation format, guardrails
  [History]  → Previous messages (for follow-up context)
  [Context]  → Retrieved chunks with source metadata
  [Question] → The current user question

TOKEN BUDGETING:
  Total budget: ~8000 tokens
  System:  500 tokens (fixed)
  History: up to 2000 tokens (trimmed from oldest)
  Context: up to 4000 tokens (top-K chunks)
  Question: ~100 tokens
  Response: 1500 tokens (reserved for output)
"""

import logging

import tiktoken

from app.config import get_settings
from app.core.llm.base import LLMMessage
from app.core.vector_store.schemas import SearchResult

settings = get_settings()
logger = logging.getLogger(__name__)


# ─── System Prompt ────────────────────────────────────────────
SYSTEM_PROMPT = """You are Cognix AI, an intelligent knowledge assistant for enterprise organizations.

## Your Primary Directive
Answer questions accurately using ONLY the provided context documents. You are a research assistant, not an oracle.

## Rules
1. **Ground every answer in the context.** Only use information from the CONTEXT section below.
2. **Cite your sources.** Use numbered citations like [1], [2], etc. that correspond to the source numbers in the context.
3. **Acknowledge limitations.** If the context doesn't contain enough information to answer, say: "Based on the available documents, I don't have enough information to fully answer this question."
4. **Never fabricate information.** Do not invent statistics, dates, names, or facts not present in the context.
5. **Be concise but thorough.** Provide complete answers without unnecessary filler.
6. **Preserve nuance.** If the context contains caveats, conditions, or uncertainties, include them in your answer.
7. **Format clearly.** Use bullet points, numbered lists, or tables when they improve readability.

## Citation Format
- Inline: "Revenue was $50M [1]"
- End of response: List all sources with document title and page number

## When You Don't Know
Say: "I don't have enough information in the provided documents to answer this question. You may want to check [suggest relevant document type]."
Do NOT guess or extrapolate beyond what the context states."""


class PromptBuilder:
    """
    Builds prompts for the RAG chain.
    
    USAGE:
        builder = PromptBuilder()
        messages = builder.build(
            question="What was Q4 revenue?",
            search_results=[...],
            chat_history=[...],
        )
    """
    
    def __init__(self):
        """Initialize with tokenizer for budget management."""
        try:
            self.encoding = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        return len(self.encoding.encode(text))
    
    def build(
        self,
        question: str,
        search_results: list[SearchResult],
        chat_history: list[LLMMessage] | None = None,
    ) -> list[LLMMessage]:
        """
        Build the complete prompt for the RAG chain.
        
        TOKEN BUDGET ALLOCATION:
        1. System prompt: ~500 tokens (fixed)
        2. Context: up to max_context_tokens (trimmed if needed)
        3. History: up to max_history_tokens (trimmed from oldest)
        4. Question: whatever the user typed
        5. Reserve max_response_tokens for the LLM's answer
        """
        messages: list[LLMMessage] = []
        
        # ─── 1. System Prompt ─────────────────────────────────
        messages.append(LLMMessage(role="system", content=SYSTEM_PROMPT))
        
        # ─── 2. Format Context ────────────────────────────────
        context_text = self._format_context(search_results)
        
        # ─── 3. Trim Chat History ─────────────────────────────
        if chat_history:
            trimmed_history = self._trim_history(chat_history)
            messages.extend(trimmed_history)
        
        # ─── 4. Build User Message ────────────────────────────
        if context_text:
            user_message = (
                f"## CONTEXT\n"
                f"Use the following sources to answer the question.\n\n"
                f"{context_text}\n\n"
                f"## QUESTION\n"
                f"{question}"
            )
        else:
            user_message = (
                f"## CONTEXT\n"
                f"No relevant documents were found.\n\n"
                f"## QUESTION\n"
                f"{question}"
            )
        
        messages.append(LLMMessage(role="user", content=user_message))
        
        # ─── Log token usage ──────────────────────────────────
        total_tokens = sum(self.count_tokens(m.content) for m in messages)
        logger.info(
            f"Prompt built: {total_tokens} tokens "
            f"({len(search_results)} sources, "
            f"{len(chat_history or [])} history messages)"
        )
        
        return messages
    
    def _format_context(self, results: list[SearchResult]) -> str:
        """
        Format search results as numbered context for the prompt.
        
        FORMAT:
          [1] Source: Q4 Financial Report | Page: 7 | Section: Revenue Analysis
          Q4 revenue was $50M, representing 3% growth over the previous quarter.
          
          [2] Source: Annual Summary | Page: 2 | Section: Overview
          Full year revenue reached $180M, a 5% increase year-over-year.
        
        TOKEN BUDGET:
          We stop adding context once we exceed max_context_tokens.
          This ensures we never overflow the context window.
        """
        if not results:
            return ""
        
        context_parts = []
        total_tokens = 0
        max_tokens = settings.max_context_tokens
        
        for i, result in enumerate(results, 1):
            # Build source header
            source_parts = []
            if result.document_title:
                source_parts.append(f"Source: {result.document_title}")
            if result.page_number:
                source_parts.append(f"Page: {result.page_number}")
            if result.section_heading:
                source_parts.append(f"Section: {result.section_heading}")
            
            source_header = " | ".join(source_parts) if source_parts else f"Source {i}"
            
            # Format the context entry
            entry = (
                f"[{i}] {source_header}\n"
                f"{result.content}\n"
            )
            
            # Check token budget
            entry_tokens = self.count_tokens(entry)
            if total_tokens + entry_tokens > max_tokens:
                logger.warning(
                    f"Context truncated at source {i}/{len(results)} "
                    f"({total_tokens}/{max_tokens} tokens)"
                )
                break
            
            context_parts.append(entry)
            total_tokens += entry_tokens
        
        return "\n".join(context_parts)
    
    def _trim_history(
        self,
        history: list[LLMMessage],
    ) -> list[LLMMessage]:
        """
        Trim conversation history to fit within token budget.
        
        STRATEGY: Keep the most RECENT messages.
        Old messages are less relevant for follow-up questions.
        
        We trim from the BEGINNING (oldest messages first)
        until the history fits within max_history_tokens.
        """
        max_tokens = settings.max_history_tokens
        max_messages = settings.max_history_messages
        
        # Limit number of messages first
        if len(history) > max_messages:
            history = history[-max_messages:]
        
        # Then trim by token count
        total_tokens = sum(self.count_tokens(m.content) for m in history)
        
        while total_tokens > max_tokens and len(history) > 2:
            # Remove oldest message (but keep at least one exchange)
            removed = history.pop(0)
            total_tokens -= self.count_tokens(removed.content)
        
        return history
    
    def build_summary_prompt(
        self,
        question: str,
        search_results: list[SearchResult],
    ) -> list[LLMMessage]:
        """
        Build a prompt specifically for document summarization.
        
        Different from Q&A — focuses on comprehensive coverage
        rather than specific answer extraction.
        """
        context_text = self._format_context(search_results)
        
        system = (
            "You are a document summarization assistant. "
            "Provide a comprehensive summary of the provided context. "
            "Organize the summary with clear headings and bullet points. "
            "Cite sources using [1], [2], etc."
        )
        
        user_msg = (
            f"## CONTEXT\n{context_text}\n\n"
            f"## TASK\n{question}"
        )
        
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user_msg),
        ]
