"""
Query classifier — determines the type of user question.

THE CLASSIFIER DECIDES HOW THE RAG CHAIN BEHAVES:
- Factual → minimal retrieval, extraction-focused
- Analytical → broad retrieval, reasoning-focused
- Comparison → multi-document retrieval
- Summary → comprehensive retrieval
- Conversational → skip retrieval entirely
- Meta → database query instead of document search

TWO APPROACHES:
1. Rule-based (keywords + patterns): Fast, no API cost, ~80% accuracy
2. LLM-based: Slower, costs ~$0.001 per query, ~95% accuracy

WE USE: Rule-based FIRST, LLM as fallback for ambiguous cases.
This saves API costs for obvious cases (greetings, simple facts)
while using the LLM for nuanced classification.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum

from app.core.llm import LLMMessage, OpenAIClient

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """Classification of user queries."""
    FACTUAL = "factual"             # "What was X?" "How much?"
    ANALYTICAL = "analytical"       # "Why?" "How does X work?"
    COMPARISON = "comparison"       # "Compare X and Y"
    SUMMARIZATION = "summarization" # "Summarize" "Overview"
    CONVERSATIONAL = "conversational"  # "Hello" "Thanks"
    META = "meta"                   # "What documents?" "How many files?"


@dataclass
class QueryClassification:
    """Result of query classification."""
    query_type: QueryType
    confidence: float       # 0.0 - 1.0
    reasoning: str          # Why this classification
    suggested_chunks: int   # Recommended number of chunks
    suggested_temperature: float  # Recommended LLM temperature


# ─── Rule-Based Classification ──────────────────────────────

# Patterns for each query type (checked in order)
CONVERSATIONAL_PATTERNS = [
    r"^(hi|hello|hey|good\s*(morning|afternoon|evening))",
    r"^(thanks|thank\s*you|thx|ty)",
    r"^(bye|goodbye|see\s*you)",
    r"^(how\s*are\s*you|what\'?s\s*up)",
    r"^(ok|okay|sure|great|nice|cool|got\s*it)",
]

META_PATTERNS = [
    r"(what|which|how many)\s*(documents?|files?|pages?)\s*(do|have|are)",
    r"(list|show)\s*(my|all|the)?\s*(documents?|files?|collections?)",
    r"(uploaded|stored|available)\s*(documents?|files?)",
]

COMPARISON_PATTERNS = [
    r"(compare|contrast|versus|vs\.?|difference|differ)",
    r"(better|worse|higher|lower)\s*(than|compared)",
    r"(pros?\s*and\s*cons?|advantages?\s*and\s*disadvantages?)",
]

SUMMARIZATION_PATTERNS = [
    r"(summarize|summary|overview|key\s*points?|main\s*(points?|ideas?|findings?))",
    r"(brief|short|quick)\s*(summary|overview|recap)",
    r"(what\s*are\s*the\s*(main|key|important))",
    r"(give\s*me\s*(a|an)?\s*(overview|summary|recap))",
    r"(tl;?dr|tldr)",
]

ANALYTICAL_PATTERNS = [
    r"^why\s",
    r"^how\s+(does|do|did|can|could|would|should|is|are)",
    r"(explain|describe|elaborate|analyze|discuss)",
    r"(cause[sd]?|reason|because|factor|impact|effect|result|consequence)",
    r"(what\s*(led|caused|resulted|contributed))",
    r"(implications?|significance|importance)",
]


def classify_query(query: str) -> QueryClassification:
    """
    Classify a query using rule-based pattern matching.
    
    Checks patterns in priority order:
    1. Conversational (skip search entirely)
    2. Meta (database query)
    3. Comparison (multi-document)
    4. Summarization (broad retrieval)
    5. Analytical (reasoning)
    6. Factual (default — simple extraction)
    
    Returns classification with confidence and recommendations.
    """
    query_lower = query.lower().strip()
    
    # Check each type in priority order
    for pattern in CONVERSATIONAL_PATTERNS:
        if re.search(pattern, query_lower):
            return QueryClassification(
                query_type=QueryType.CONVERSATIONAL,
                confidence=0.95,
                reasoning="Matched conversational pattern",
                suggested_chunks=0,
                suggested_temperature=0.7,
            )
    
    for pattern in META_PATTERNS:
        if re.search(pattern, query_lower):
            return QueryClassification(
                query_type=QueryType.META,
                confidence=0.90,
                reasoning="Question about documents/system, not content",
                suggested_chunks=0,
                suggested_temperature=0.3,
            )
    
    for pattern in COMPARISON_PATTERNS:
        if re.search(pattern, query_lower):
            return QueryClassification(
                query_type=QueryType.COMPARISON,
                confidence=0.85,
                reasoning="Contains comparison keywords",
                suggested_chunks=8,
                suggested_temperature=0.1,
            )
    
    for pattern in SUMMARIZATION_PATTERNS:
        if re.search(pattern, query_lower):
            return QueryClassification(
                query_type=QueryType.SUMMARIZATION,
                confidence=0.90,
                reasoning="Requesting summary or overview",
                suggested_chunks=10,
                suggested_temperature=0.3,
            )
    
    for pattern in ANALYTICAL_PATTERNS:
        if re.search(pattern, query_lower):
            return QueryClassification(
                query_type=QueryType.ANALYTICAL,
                confidence=0.80,
                reasoning="Requires reasoning or explanation",
                suggested_chunks=8,
                suggested_temperature=0.2,
            )
    
    # Default: factual
    return QueryClassification(
        query_type=QueryType.FACTUAL,
        confidence=0.70,
        reasoning="Default classification (simple factual query)",
        suggested_chunks=3,
        suggested_temperature=0.0,
    )


async def classify_query_llm(query: str) -> QueryClassification:
    """
    Classify a query using the LLM (for ambiguous cases).
    
    More accurate than rule-based but costs ~$0.001 per call.
    Used when rule-based confidence is below threshold.
    """
    llm = OpenAIClient(model="gpt-4o-mini")
    
    prompt = f"""Classify this user query into exactly one category.

Categories:
- factual: Simple fact extraction (what, when, who, how much)
- analytical: Requires reasoning (why, how, explain, analyze)
- comparison: Comparing two or more things
- summarization: Requesting a summary or overview
- conversational: Greetings, thanks, small talk (NOT document questions)
- meta: Questions about documents/system themselves

Query: "{query}"

Respond with ONLY a JSON object:
{{"type": "category_name", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""
    
    try:
        response = await llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=100,
        )
        
        import json
        result = json.loads(response.content)
        query_type = QueryType(result["type"])
        
        # Map to chunk recommendations
        chunk_map = {
            QueryType.FACTUAL: (3, 0.0),
            QueryType.ANALYTICAL: (8, 0.2),
            QueryType.COMPARISON: (8, 0.1),
            QueryType.SUMMARIZATION: (10, 0.3),
            QueryType.CONVERSATIONAL: (0, 0.7),
            QueryType.META: (0, 0.3),
        }
        chunks, temp = chunk_map.get(query_type, (5, 0.1))
        
        return QueryClassification(
            query_type=query_type,
            confidence=result.get("confidence", 0.8),
            reasoning=result.get("reasoning", "LLM classification"),
            suggested_chunks=chunks,
            suggested_temperature=temp,
        )
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}, using rule-based")
        return classify_query(query)
