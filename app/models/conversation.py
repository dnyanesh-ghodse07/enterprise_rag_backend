"""
Conversation and message models for chat history.

DESIGN:
- A Conversation belongs to a user within a tenant
- A Conversation has many Messages
- Messages are ordered by created_at
- We store the full conversation for audit and analytics

WHY STORE IN DATABASE:
1. Audit trail (compliance — who asked what, when)
2. Analytics (what are users asking about?)
3. Persistence (conversation survives server restart)
4. Searchability (find conversations about a topic)
"""

from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Conversation(BaseModel):
    """A conversation (chat session) between a user and Cognix AI."""
    __tablename__ = "conversations"
    
    # ─── Owner ────────────────────────────────────────────────
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # ─── Metadata ─────────────────────────────────────────────
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="New Conversation",
        comment="Auto-generated from first question",
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Total messages in this conversation",
    )
    
    # ─── Relationships ────────────────────────────────────────
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    
    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title='{self.title}')>"


class Message(BaseModel):
    """A single message within a conversation."""
    __tablename__ = "messages"
    
    # ─── Parent Conversation ──────────────────────────────────
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # ─── Content ──────────────────────────────────────────────
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'user' or 'assistant'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message text content",
    )
    
    # ─── Metadata ─────────────────────────────────────────────
    token_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Number of tokens in this message",
    )
    
    # ─── RAG Metadata (for assistant messages) ────────────────
    sources_used: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Number of source chunks used",
    )
    model_used: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="LLM model used for this response",
    )
    
    # ─── Relationships ────────────────────────────────────────
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )
    
    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Message(role={self.role}, '{preview}')>"
