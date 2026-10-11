"""Parallel workers and scheduled tasks stay under their chat's permissions.

Enforcement audit finding E4 (2026-10-11): a parallel worker runs in its own
hidden context, so it got the default mode instead of its chat's mode and
messaging cap, and its approval cards went to a context the UI never shows
(they timed out). A task created from a messaging chat ran uncapped.
"""

from __future__ import annotations

import asyncio
import types

import pytest

import agent as agent_module
from helpers import channels, parallel_tools
from plugins._permissions.helpers import ask, config as perm_config, mode_state


class _Log:
    def __init__(self):
        self.items = []

    def log(self, **kw):
        item = types.SimpleNamespace(kvps=dict(kw.get("kvps", {})), update=lambda **k: None)
        self.items.append(kw)
        return item


def _context(cid, data=None):
    ctx = types.SimpleNamespace(id=cid, data=dict(data or {}), log=_Log())
    ctx.get_data = lambda key, _ctx=ctx: _ctx.data.get(key)
    ctx.set_data = lambda key, value, _ctx=ctx: _ctx.data.__setitem__(key, value)
    return ctx


def _agent(ctx):
    return types.SimpleNamespace(context=ctx, agent_name="A0", number=0)


@pytest.fixture
def contexts(monkeypatch):
    registry = {}
    monkeypatch.setattr(agent_module.AgentContext, "get", staticmethod(lambda cid: registry.get(cid)))
    monkeypatch.setattr(mode_state, "default_mode", lambda: "auto")
    monkeypatch.setattr(mode_state, "context_project", lambda context: "")
    monkeypatch.setattr(perm_config, "get_plugin_config", lambda *a, **k: {}, raising=False)
    from helpers import plugins

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {})
    mode_state.clear_all()
    yield registry
    mode_state.clear_all()


def _worker_of(parent_id):
    return _context("worker", {parallel_tools.PARALLEL_WORKER_PARENT_CONTEXT_KEY: parent_id})


def test_worker_uses_its_chats_mode(contexts):
    contexts["chat"] = _context("chat")
    mode_state.set_mode("chat", "plan")
    assert perm_config.get_config(_agent(_worker_of("chat")))["mode"] == "plan"


def test_worker_keeps_its_chats_messaging_cap(contexts):
    # Default mode Auto, but the chat came from Telegram (capped at Manual).
    contexts["chat"] = _context("chat", {channels.CHANNEL_MARKERS["telegram"]: 12345})
    cfg = perm_config.get_config(_agent(_worker_of("chat")))
    assert cfg["mode"] == "manual" and cfg["channel"] == "telegram"


def test_orphaned_worker_never_acts_above_manual(contexts):
    cfg = perm_config.get_config(_agent(_worker_of("deleted-chat")))
    assert cfg["mode"] == "manual"


def test_ordinary_chat_is_unchanged(contexts):
    contexts["chat"] = _context("chat")
    assert perm_config.get_config(_agent(contexts["chat"]))["mode"] == "auto"


def test_worker_approval_card_is_shown_in_its_chat(contexts, monkeypatch):
    chat = _context("chat")
    contexts["chat"] = chat
    worker = _worker_of("chat")
    loop = asyncio.new_event_loop()

    def register(approval_id):
        future = loop.create_future()
        future.set_result(True)
        return future

    monkeypatch.setattr(ask.approval_registry, "register", register)
    loop.run_until_complete(ask.request_approval(
        _agent(worker), "code_execution_tool", {"runtime": "terminal", "code": "dir"},
        reason="test", mode="manual", timeout=5,
    ))
    loop.close()
    assert any(i.get("type") == "permissions_approval_request" for i in chat.log.items)
    assert worker.log.items == []


def test_channel_origin_caps_but_never_impersonates_a_channel():
    data = {channels.CHANNEL_ORIGIN_KEY: "telegram"}
    assert channels.channel_of_data(data) == "telegram"
    assert channels.CHANNEL_MARKERS["telegram"] not in data  # no Telegram replies triggered
    assert channels.channel_of_data({channels.CHANNEL_ORIGIN_KEY: "not-a-channel"}) == ""


def test_task_chat_gets_the_channel_origin(monkeypatch):
    from helpers import task_scheduler

    ctx = _context("task-chat")

    async def unmarked(self, task):
        return ctx

    monkeypatch.setattr(task_scheduler.TaskScheduler, "_get_chat_context_unmarked", unmarked)
    task = types.SimpleNamespace(channel_origin="discord")
    scheduler = object.__new__(task_scheduler.TaskScheduler)
    result = asyncio.run(task_scheduler.TaskScheduler._get_chat_context(scheduler, task))
    assert channels.channel_of(result) == "discord"


def test_scheduler_tool_stamps_the_creating_chats_channel(contexts, monkeypatch):
    from tools import scheduler as scheduler_tool

    added = []

    class FakeScheduler:
        async def add_task(self, task):
            added.append(task)

    monkeypatch.setattr(scheduler_tool.TaskScheduler, "get", staticmethod(lambda: FakeScheduler()))
    chat = _context("chat", {channels.CHANNEL_MARKERS["slack"]: "C1"})
    contexts["chat"] = chat
    tool = object.__new__(scheduler_tool.SchedulerTool)
    tool.agent = _agent(_worker_of("chat"))  # even from a parallel job of that chat
    task = types.SimpleNamespace(channel_origin="")
    asyncio.run(tool._add_task(task))
    assert added and task.channel_origin == "slack"
