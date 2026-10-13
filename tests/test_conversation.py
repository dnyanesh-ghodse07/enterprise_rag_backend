from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.conversation import Conversation
from app.services.conversation_service import ConversationService


@pytest.mark.asyncio
async def test_get_or_create_new_conversation():
    db = MagicMock()
    db.execute = AsyncMock()
    # conversation_id is None -> no select query executed
    db.add = MagicMock()
    db.flush = AsyncMock()

    user_id = uuid4()
    tenant_id = uuid4()

    service = ConversationService(db)
    conv = await service.get_or_create(
        conversation_id=None,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    assert conv is not None
    assert conv.user_id == user_id
    assert conv.tenant_id == tenant_id
    assert conv.title == "New Conversation"
    assert conv.messages == []
    db.add.assert_called_once_with(conv)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_message_and_auto_title():
    db = MagicMock()
    db.add = MagicMock()

    user_id = uuid4()
    tenant_id = uuid4()
    conv = Conversation(
        id=uuid4(),
        user_id=user_id,
        tenant_id=tenant_id,
        title="New Conversation",
        messages=[],
    )

    service = ConversationService(db)
    user_msg = await service.add_message(
        conversation=conv,
        role="user",
        content="What is Cognix RAG platform?",
    )

    assert user_msg.conversation_id == conv.id
    assert user_msg.role == "user"
    assert user_msg.content == "What is Cognix RAG platform?"
    assert conv.title == "What is Cognix RAG platform?"
    assert conv.message_count == 1
    db.add.assert_called_once_with(user_msg)

    asst_msg = await service.add_message(
        conversation=conv,
        role="assistant",
        content="Cognix is an enterprise RAG platform.",
        sources_used=3,
        model_used="gpt-4o",
    )

    assert asst_msg.conversation_id == conv.id
    assert asst_msg.role == "assistant"
    assert asst_msg.sources_used == 3
    assert asst_msg.model_used == "gpt-4o"
    assert conv.message_count == 2
