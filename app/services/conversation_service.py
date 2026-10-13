"""
Conversation service — manages chat history and conversation state.

RESPONSIBILITIES:
- Create and load conversations
- Add messages to conversations
- Retrieve conversation history for the prompt builder
- Auto-generate conversation titles from first question
- Trim history to fit token budgets
"""

import logging
from uuid import UUID

import tiktoken
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.llm.base import LLMMessage
from app.models.conversation import Conversation, Message

settings = get_settings()
logger = logging.getLogger(__name__)


class ConversationService:
    """Manages conversation history for RAG chat."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        try:
            self.encoding = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    async def get_or_create(
        self,
        conversation_id: UUID | None,
        user_id: UUID,
        tenant_id: UUID,
    ) -> Conversation:
        """
        Get an existing conversation or create a new one.
        
        If conversation_id is None, creates a new conversation.
        If conversation_id is provided, loads it (with access check).
        """
        if conversation_id:
            result = await self.db.execute(
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
            conversation = result.scalar_one_or_none()
            
            if conversation:
                return conversation
            
            logger.warning(
                f"Conversation {conversation_id} not found for user {user_id}"
            )
        
        # Create new conversation
        conversation = Conversation(
            user_id=user_id,
            tenant_id=tenant_id,
            title="New Conversation",
            messages=[],  # Initialize empty collection to avoid MissingGreenlet on later access
        )
        self.db.add(conversation)
        await self.db.flush()  # Get the ID without committing
        
        return conversation
    
    async def add_message(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        sources_used: int = 0,
        model_used: str | None = None,
    ) -> Message:
        """Add a message to a conversation."""
        token_count = len(self.encoding.encode(content))
        
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            token_count=token_count,
            sources_used=sources_used,
            model_used=model_used,
        )
        self.db.add(message)
        
        # Update conversation metadata
        conversation.message_count = (conversation.message_count or 0) + 1
        
        # Auto-title from first user message
        if role == "user" and conversation.title == "New Conversation":
            # Use first 80 chars of first question as title
            conversation.title = content[:80].strip()
            if len(content) > 80:
                conversation.title += "..."
        
        return message
    
    def get_history_as_messages(
        self,
        conversation: Conversation,
    ) -> list[LLMMessage]:
        """
        Convert conversation history to LLMMessage format.
        
        Returns messages suitable for the prompt builder.
        Only includes user and assistant messages (not system).
        """
        if not conversation.messages:
            return []
        
        return [
            LLMMessage(role=msg.role, content=msg.content)
            for msg in conversation.messages
            if msg.role in ("user", "assistant")
        ]
    
    async def list_conversations(
        self,
        user_id: UUID,
        tenant_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """List conversations for a user."""
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.tenant_id == tenant_id,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        conversations = result.scalars().all()
        
        return [
            {
                "id": str(conv.id),
                "title": conv.title,
                "message_count": conv.message_count,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }
            for conv in conversations
        ]
    
    async def get_conversation_messages(
        self,
        conversation_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> list[dict]:
        """Get all messages for a conversation."""
        result = await self.db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            return []
        
        return [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
                "token_count": msg.token_count,
                "sources_used": msg.sources_used,
                "model_used": msg.model_used,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in conversation.messages
        ]
