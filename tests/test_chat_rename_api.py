"""Tests for api/chat_rename.py.

Chats are already named automatically after the first exchange; this
endpoint is the manual override. The interesting cases are the ones that
would corrupt the sidebar or silently do the wrong thing: blank names,
multi-line paste, over-long input, and an unknown context id.
"""

from __future__ import annotations

import pytest

from api import chat_rename


class _FakeContext:
    def __init__(self, name="Original"):
        self.name = name


def _handler():
    return chat_rename.RenameChat(app=None, thread_lock=None)  # type: ignore[arg-type]


@pytest.fixture
def ctx(monkeypatch):
    """A single known context, with persistence and broadcast stubbed."""
    context = _FakeContext()
    monkeypatch.setattr(
        chat_rename.AgentContext, "get", staticmethod(
            lambda ctxid: context if ctxid == "abc" else None
        )
    )
    saved: list = []
    monkeypatch.setattr(chat_rename.persist_chat, "save_tmp_chat", saved.append)
    import helpers.state_monitor_integration as smi

    monkeypatch.setattr(smi, "mark_dirty_all", lambda **k: None)
    context.saved = saved  # type: ignore[attr-defined]
    return context


@pytest.mark.asyncio
async def test_renames_and_persists(ctx):
    result = await _handler().process(
        {"context": "abc", "name": "Tunnel setup"}, None  # type: ignore[arg-type]
    )
    assert result == {"ok": True, "name": "Tunnel setup"}
    assert ctx.name == "Tunnel setup"
    # A name that is not written to disk is lost on restart.
    assert ctx.saved == [ctx]


@pytest.mark.asyncio
async def test_whitespace_is_collapsed(ctx):
    """A pasted multi-line name would otherwise break the sidebar row."""
    result = await _handler().process(
        {"context": "abc", "name": "  Tunnel\n\tsetup   notes  "}, None  # type: ignore[arg-type]
    )
    assert result["name"] == "Tunnel setup notes"


@pytest.mark.asyncio
async def test_long_names_are_truncated_like_the_auto_namer(ctx):
    result = await _handler().process(
        {"context": "abc", "name": "x" * 200}, None  # type: ignore[arg-type]
    )
    assert result["name"] == "x" * chat_rename.MAX_NAME_LENGTH + "..."


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   ", "\n\t "])
async def test_blank_names_are_refused_not_applied(ctx, name):
    """Clearing the name would leave an unidentifiable row; a blank input
    is a mistake rather than an instruction."""
    result = await _handler().process(
        {"context": "abc", "name": name}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert ctx.name == "Original"
    assert ctx.saved == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"context": "abc"},                       # no name
    {"context": "abc", "name": 123},          # wrong type
    {"name": "x"},                            # no context
    {},
])
async def test_malformed_requests_are_refused(ctx, payload):
    result = await _handler().process(payload, None)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert ctx.name == "Original"


@pytest.mark.asyncio
async def test_unknown_context_is_reported(ctx):
    result = await _handler().process(
        {"context": "nope", "name": "x"}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert "nope" in result["error"]


@pytest.mark.asyncio
async def test_lookup_does_not_switch_the_active_chat(monkeypatch, ctx):
    """AgentContext.use() sets the current context as a side effect;
    renaming a background chat must not steal focus from the open one."""
    used: list = []
    monkeypatch.setattr(
        chat_rename.AgentContext, "use", staticmethod(lambda i: used.append(i))
    )
    await _handler().process(
        {"context": "abc", "name": "Renamed"}, None  # type: ignore[arg-type]
    )
    assert used == []
