"""Approval questions answered from the phone, and one allowlist rule for every channel."""

from __future__ import annotations

import asyncio
import importlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import channel_approvals as ca
from plugins._safety_policy.helpers import approval_registry

ROOT = Path(__file__).resolve().parents[1]


class _Context:
    def __init__(self, channel=""):
        self.data = {"channel_origin": channel} if channel else {}
        self.task = "existing task"

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value


@pytest.fixture
def phone(monkeypatch):
    sent = []

    async def fake_send(context, text, attachments=None):
        sent.append(text)
        return ""

    monkeypatch.setattr(ca, "send", fake_send)
    monkeypatch.setattr(ca, "_channel_allowlist_set", lambda context, channel: True)
    return sent


def _agent(context):
    return SimpleNamespace(context=context)


def test_a_question_goes_to_the_phone_with_a_code(phone):
    context = _Context("telegram")

    async def run():
        code = ca.announce(_agent(context), "approval-1", "code_execution_tool dir - needs approval")
        await asyncio.sleep(0)
        return code

    code = asyncio.run(run())
    assert len(code) == 4 and context.data[ca.CODES_KEY] == {code: "approval-1"}
    assert f"yes {code}" in phone[0] and "needs approval" in phone[0]


@pytest.mark.parametrize("channel", ["email", ""])
def test_email_and_the_webui_never_get_phone_approvals(phone, channel):
    async def run():
        return ca.announce(_agent(_Context(channel)), "approval-1", "q")

    assert asyncio.run(run()) == "" and phone == []


def test_a_channel_open_to_anyone_gets_no_phone_approvals(phone, monkeypatch):
    monkeypatch.setattr(ca, "_channel_allowlist_set", lambda context, channel: False)

    async def run():
        return ca.announce(_agent(_Context("whatsapp")), "approval-1", "q")

    assert asyncio.run(run()) == ""


def _register_on_own_loop(approval_id):
    """A pending approval on another thread's loop, like the agent's."""
    ready, holder = threading.Event(), {}

    def runner():
        async def wait():
            holder["future"] = approval_registry.register(approval_id)
            ready.set()
            holder["result"] = await asyncio.wait_for(holder["future"], timeout=5)

        asyncio.run(wait())

    thread = threading.Thread(target=runner)
    thread.start()
    ready.wait(5)
    return thread, holder


@pytest.mark.parametrize("reply,approved", [("yes {code}", True), ("NO {code}", False), ("allow {code}.", True), ("deny {code}", False)])
def test_a_phone_reply_answers_the_question(phone, reply, approved):
    context = _Context("telegram")
    thread, holder = _register_on_own_loop("approval-2")
    context.set_data(ca.CODES_KEY, {"K7QX": "approval-2"})
    confirmation = ca.try_answer(context, SimpleNamespace(message=reply.format(code="k7qx")))
    thread.join(5)
    assert holder.get("result") is approved
    assert confirmation.startswith("Allowed." if approved else "Refused.")
    assert context.data[ca.CODES_KEY] == {}


def test_ordinary_messages_pass_through(phone):
    context = _Context("telegram")
    assert ca.try_answer(context, SimpleNamespace(message="yes please continue")) is None
    assert ca.try_answer(context, SimpleNamespace(message="yes ABCD")) is None  # nothing pending: a normal message


def test_a_wrong_code_is_reported_and_answers_nothing(phone):
    context = _Context("telegram")
    context.set_data(ca.CODES_KEY, {"K7QX": "approval-3"})
    assert "No open question" in ca.try_answer(context, SimpleNamespace(message="yes ZZZZ"))
    assert context.data[ca.CODES_KEY] == {"K7QX": "approval-3"}


def test_email_replies_never_answer(phone):
    context = _Context("email")
    context.set_data(ca.CODES_KEY, {"K7QX": "approval-4"})
    assert ca.try_answer(context, SimpleNamespace(message="yes K7QX")) is None


def test_a_late_answer_says_so(phone):
    context = _Context("slack")
    context.set_data(ca.CODES_KEY, {"K7QX": "approval-gone"})
    assert "already answered or timed out" in ca.try_answer(context, SimpleNamespace(message="no K7QX"))


def test_the_reply_never_reaches_the_agent(phone, monkeypatch):
    module = importlib.import_module(
        "extensions.python._functions.agent.AgentContext.communicate.start._05_channel_approval_reply")
    context = _Context("discord")
    monkeypatch.setattr(ca, "try_answer", lambda ctx, msg: "Allowed. (K7QX)")
    data = {"args": (context, SimpleNamespace(message="yes K7QX")), "kwargs": {}}
    module.ChannelApprovalReply(agent=None).execute(data=data)
    assert data["result"] == "existing task"
    monkeypatch.setattr(ca, "try_answer", lambda ctx, msg: None)
    normal = {"args": (context, SimpleNamespace(message="hello")), "kwargs": {}}
    module.ChannelApprovalReply(agent=None).execute(data=normal)
    assert "result" not in normal


def test_every_kind_of_question_is_announced():
    for path in ("plugins/_permissions/helpers/ask.py",
                 "plugins/_safety_policy/extensions/python/tool_execute_before/_05_command_policy.py",
                 "plugins/_infection_check/helpers/checker.py"):
        assert "channel_approvals.announce(" in (ROOT / path).read_text(encoding="utf-8"), path


# -- one allowlist rule: empty = nobody -------------------------------------------

def test_telegram_empty_allowlist_answers_nobody():
    """Just the function: the handler module needs aiogram, which tests lack."""
    import ast

    source = (ROOT / "plugins/_telegram_integration/helpers/handler.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_is_allowed")
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "handler", "exec"), scope)
    assert scope["_is_allowed"]({"allowed_users": []}, 123, "someone") is False
    assert scope["_is_allowed"]({"allowed_users": ["123"]}, 123, "someone") is True
    assert scope["_is_allowed"]({"allowed_users": ["@someone"]}, 9, "someone") is True


def test_email_and_whatsapp_refuse_with_an_empty_list():
    email = (ROOT / "plugins/_email_integration/helpers/handler.py").read_text(encoding="utf-8")
    whatsapp = (ROOT / "plugins/_whatsapp_integration/helpers/handler.py").read_text(encoding="utf-8")
    assert "allowed senders is empty, so no email is answered" in email
    assert "allowed numbers is empty, so no message is answered" in whatsapp


@pytest.mark.parametrize("plugin,cfg,expected", [
    ("_discord_integration", {"allowed_users": ["1"]}, True),
    ("_discord_integration", {"allowed_users": []}, False),
    ("_slack_integration", {"allowed_users": ["U1"]}, True),
])
def test_closed_channels_are_told_apart(plugin, cfg, expected):
    module = importlib.import_module(f"plugins.{plugin}.helpers.allowlist")
    key = importlib.import_module(f"plugins.{plugin}.helpers.constants").CTX_BOT_CFG
    assert module.channel_allowlist_set(SimpleNamespace(data={key: cfg})) is expected


def test_the_resolve_is_safe_across_threads():
    thread, holder = _register_on_own_loop("approval-cross")
    assert approval_registry.resolve("approval-cross", True) is True
    thread.join(5)
    assert holder.get("result") is True
