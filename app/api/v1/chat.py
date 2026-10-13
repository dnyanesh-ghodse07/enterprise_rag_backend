"""
Chat API endpoints.

ENDPOINTS:
  POST /api/v1/chat/ask              → Ask a question (complete or streamed)
  GET  /api/v1/chat/conversations     → List user's conversations
  GET  /api/v1/chat/conversations/{id} → Get conversation messages
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.schemas.chat import ChatRequest, ChatResponse, ConversationListItem
from app.services.conversation_service import ConversationService
from app.services.rag_service import RAGService

router = APIRouter()


@router.post(
    "/ask",
    summary="Ask Cognix AI a question",
    description=(
        "Ask a question about your documents. "
        "Cognix searches your knowledge base, retrieves relevant context, "
        "and generates a grounded answer with source citations."
    ),
)
async def ask_question(
    request: ChatRequest,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
):
    """
    Ask a question and get an answer grounded in your documents.
    
    MODES:
    - stream=false (default): Returns complete JSON response
    - stream=true: Returns Server-Sent Events (SSE) stream
    
    EXAMPLE (non-streaming):
    POST /api/v1/chat/ask
    {
        "question": "What was Q4 revenue?",
        "stream": false
    }
    
    RESPONSE:
    {
        "answer": "According to the Q4 Financial Report (page 7)...",
        "conversation_id": "uuid",
        "sources": [
            {"index": 1, "document_title": "Q4 Report", "page_number": 7}
        ],
        "metadata": {"model": "gpt-4o", "total_tokens": 3200}
    }
    
    EXAMPLE (streaming):
    POST /api/v1/chat/ask
    {
        "question": "What was Q4 revenue?",
        "stream": true
    }
    
    RESPONSE (SSE):
    data: {"type": "sources", "sources": [...]}
    data: {"type": "token", "content": "According"}
    data: {"type": "token", "content": " to"}
    data: {"type": "token", "content": " the"}
    ...
    data: {"type": "done", "conversation_id": "uuid"}
    """
    rag = RAGService(db)
    
    if request.stream:
        # ─── Streaming mode ──────────────────────────────────
        return StreamingResponse(
            rag.ask_stream(
                question=request.question,
                user_id=user.id,
                tenant_id=user.tenant_id,
                conversation_id=request.conversation_id,
                document_ids=request.document_ids,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )
    
    # ─── Complete mode ────────────────────────────────────────
    result = await rag.ask(
        question=request.question,
        user_id=user.id,
        tenant_id=user.tenant_id,
        conversation_id=request.conversation_id,
        document_ids=request.document_ids,
    )
    
    return result


@router.get(
    "/conversations",
    response_model=list[ConversationListItem],
    summary="List conversations",
)
async def list_conversations(
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> list[ConversationListItem]:
    """List the current user's conversations, most recent first."""
    service = ConversationService(db)
    conversations = await service.list_conversations(
        user_id=user.id,
        tenant_id=user.tenant_id,
        limit=limit,
        offset=offset,
    )
    return [ConversationListItem(**conv) for conv in conversations]


@router.get(
    "/conversations/{conversation_id}",
    summary="Get conversation messages",
)
async def get_conversation(
    conversation_id: UUID,
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Get all messages in a conversation."""
    service = ConversationService(db)
    return await service.get_conversation_messages(
        conversation_id=conversation_id,
        user_id=user.id,
        tenant_id=user.tenant_id,
    )
