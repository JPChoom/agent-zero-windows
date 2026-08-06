from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import threading

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import AgentContext
from initialize import initialize_agent


class _CompletedTask:
    async def result(self):
        return "ok"


@pytest.mark.asyncio
async def test_api_message_persists_lifetime_hours_in_context_data(monkeypatch):
    from api.api_message import ApiMessage
    from helpers import persist_chat

    monkeypatch.setattr(AgentContext, "communicate", lambda self, msg: _CompletedTask())

    handler = ApiMessage(app=None, thread_lock=threading.RLock())  # type: ignore[arg-type]
    output = await handler.process(
        {
            "message": "hello",
            "lifetime_hours": 1,
        },
        request=None,  # type: ignore[arg-type]
    )

    context_id = output["context_id"]  # type: ignore[index]
    context = AgentContext.get(context_id)
    restored = None
    try:
        assert context is not None
        assert context.get_data("lifetime_hours") == 1.0

        serialized = json.loads(persist_chat.export_json_chat(context))
        assert serialized["data"]["lifetime_hours"] == 1.0

        AgentContext.remove(context_id)
        restored = persist_chat._deserialize_context(serialized)
        assert restored.get_data("lifetime_hours") == 1.0
    finally:
        AgentContext.remove(context_id)
        if restored:
            AgentContext.remove(restored.id)


@pytest.mark.asyncio
async def test_job_loop_removes_expired_lifetime_chat(monkeypatch):
    from extensions.python.job_loop._20_cleanup_expired_api_chats import (
        CleanupExpiredApiChats,
    )
    import extensions.python.job_loop._20_cleanup_expired_api_chats as cleanup_module

    removed_chats = []
    dirty_reasons = []
    monkeypatch.setattr(cleanup_module.persist_chat, "remove_chat", removed_chats.append)
    monkeypatch.setattr(
        cleanup_module,
        "mark_dirty_all",
        lambda reason: dirty_reasons.append(reason),
    )

    context = AgentContext(
        config=initialize_agent(),
        last_message=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    context.set_data("lifetime_hours", 1)
    CleanupExpiredApiChats._last_check = None

    await CleanupExpiredApiChats(agent=None).execute()

    assert AgentContext.get(context.id) is None
    assert removed_chats == [context.id]
    assert dirty_reasons == ["job_loop.CleanupExpiredApiChats"]
