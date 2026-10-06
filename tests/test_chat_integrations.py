"""Discord and Slack integrations: shared plumbing (helpers/chat_channels.py),
who gets answered, formatting, and a simulated inbound message for each.
No network: clients are faked."""

from __future__ import annotations

import asyncio

import pytest

from helpers import chat_channels


# -- shared plumbing ---------------------------------------------------------------

def test_empty_allowlist_means_nobody():
    assert not chat_channels.is_allowed([], "123")
    assert not chat_channels.is_allowed(None, "123")


@pytest.mark.parametrize("allowed,uid,names,ok", [
    (["123"], "123", [], True),
    ([123], "123", [], True),
    (["@Alice"], "999", ["alice"], True),
    (["alice"], "999", ["Bob"], False),
    (["U0ABC"], "U0abc", [], True),
])
def test_allowlist_matches_ids_and_names(allowed, uid, names, ok):
    assert chat_channels.is_allowed(allowed, uid, names) is ok


def test_split_text_respects_limit_and_boundaries():
    text = ("word " * 900).strip()
    chunks = chat_channels.split_text(text, 2000)
    assert all(len(c) <= 2000 for c in chunks) and len(chunks) == 3
    assert " ".join(chunks) == text
    assert chat_channels.split_text("", 100) == []


def test_channel_state_round_trip(tmp_path, monkeypatch):
    state = chat_channels.ChannelState("_x")
    state.path = str(tmp_path / "state.json")
    state.set("bot:1:2", "ctx-a")
    assert state.get("bot:1:2") == "ctx-a"
    state.drop("bot:1:2")
    assert state.get("bot:1:2") == ""


@pytest.mark.asyncio
async def test_bot_thread_runs_work_on_its_own_loop():
    stop = {}

    async def main(thread):
        stop["event"] = asyncio.Event()
        thread.ready.set()
        await stop["event"].wait()

    t = chat_channels.BotThread("test", main)
    t.start()
    assert t.ready.wait(5)

    async def where():
        return asyncio.get_running_loop()

    assert await t.run(where()) is t.loop
    t.loop.call_soon_threadsafe(stop["event"].set)
    t._thread.join(5)
    assert not t.alive


class _FakeClient:
    started = 0

    def __init__(self, name, cfg):
        self.cfg = cfg
        self.thread = type("T", (), {"ended_at": None})()
        self._alive = False

    def start(self):
        _FakeClient.started += 1
        self._alive = True

    def stop(self):
        self._alive = False

    @property
    def alive(self):
        return self._alive


def test_sync_starts_stops_restarts_and_backs_off(monkeypatch):
    monkeypatch.setattr(chat_channels, "RUNNING", {})
    monkeypatch.setattr(chat_channels, "_BACKOFF", {})
    fp = lambda c: (c.get("token"),)
    _FakeClient.started = 0

    chat_channels.sync_clients("t", {"a": {"token": "1"}}, fp, _FakeClient)
    assert _FakeClient.started == 1 and "t:a" in chat_channels.RUNNING

    # died a moment ago: no immediate restart (backoff)
    client = chat_channels.RUNNING["t:a"]
    client._alive = False
    client.thread.ended_at = __import__("time").monotonic()
    chat_channels.sync_clients("t", {"a": {"token": "1"}}, fp, _FakeClient)
    assert _FakeClient.started == 1

    # changed token: restarted at once
    chat_channels.sync_clients("t", {"a": {"token": "2"}}, fp, _FakeClient)
    assert _FakeClient.started == 2 and chat_channels.RUNNING["t:a"].cfg["token"] == "2"

    # removed from config: stopped and forgotten
    chat_channels.sync_clients("t", {}, fp, _FakeClient)
    assert "t:a" not in chat_channels.RUNNING


# -- Discord ---------------------------------------------------------------------------

from plugins._discord_integration.helpers import bot as dbot
from plugins._discord_integration.helpers import constants as DC


@pytest.mark.parametrize("is_dm,mentioned,mode,channel,allowed,ok", [
    (True, False, "off", "1", [], True),          # DMs always considered
    (False, True, "mention", "1", [], True),
    (False, False, "mention", "1", [], False),
    (False, False, "all", "1", [], True),
    (False, True, "off", "1", [], False),
    (False, True, "mention", "1", ["2"], False),  # channel not allowed
    (False, True, "mention", "2", ["2"], True),
])
def test_discord_answer_rules(is_dm, mentioned, mode, channel, allowed, ok):
    assert dbot.should_answer(is_dm=is_dm, mentioned=mentioned, server_mode=mode,
                              channel_id=channel, allowed_channels=allowed) is ok


def test_discord_mentions_are_stripped():
    assert dbot.strip_mentions("<@123> hi <@!456>") == "hi"


class _Ctx:
    def __init__(self):
        self.id = "ctx-1"
        self.data = {}
        self.agent0 = self

    def read_prompt(self, name, **kw):
        return f"[{name}] {kw.get('sender')}: {kw.get('body')}"


@pytest.fixture
def captured(monkeypatch):
    seen = {"created": [], "delivered": [], "sent": []}
    ctx = _Ctx()

    def fake_context(state, key, name, data, project=""):
        ctx.data.update(data)
        seen["created"].append((key, name, data))
        return ctx

    def fake_deliver(context, text, attachments, source):
        seen["delivered"].append((text, attachments, source))
        return ""

    monkeypatch.setattr(chat_channels, "get_or_create_context", fake_context)
    monkeypatch.setattr(chat_channels, "deliver", fake_deliver)
    return seen, ctx


@pytest.mark.asyncio
async def test_discord_dm_from_an_allowed_user_reaches_the_agent(captured, monkeypatch):
    import discord

    seen, ctx = captured

    class FakeDM:
        id = 555

        def typing(self):
            class _T:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
            return _T()

    monkeypatch.setattr(discord, "DMChannel", FakeDM)

    class Author:
        id, name, global_name, bot = 42, "alice", "Alice", False

    class Msg:
        author, channel, content, mentions, attachments, id = Author(), FakeDM(), "hello <@1>", [], [], 7

    b = dbot.DiscordBot("main", {"allowed_users": ["42"], "server_mode": "mention"})

    class Client:
        user = type("U", (), {"id": 1})()

    b.client = Client()
    monkeypatch.setattr(dbot, "current_cfg", lambda name: {})
    await b._on_message(Msg())
    key, _, data = seen["created"][0]
    assert key == "main:42:555" and data[DC.CTX_CHANNEL] == "555"
    assert seen["delivered"][0][0].endswith("alice: hello") and seen["delivered"][0][2] == "discord"


@pytest.mark.asyncio
async def test_discord_ignores_users_not_on_the_allowlist(captured, monkeypatch):
    import discord

    seen, _ = captured
    monkeypatch.setattr(discord, "DMChannel", object)
    b = dbot.DiscordBot("main", {"allowed_users": []})
    b.client = type("C", (), {"user": None})()
    monkeypatch.setattr(dbot, "current_cfg", lambda name: {})

    class Msg:
        author = type("A", (), {"id": 9, "name": "mallory", "global_name": "", "bot": False})()
        channel = type("Ch", (), {"id": 77})()
        content, mentions, attachments, id = "hi", [], [], 1

    await b._on_message(Msg())
    assert seen["created"] == [] and seen["delivered"] == []


@pytest.mark.asyncio
async def test_discord_reply_without_a_running_bot_reports_an_error():
    ctx = _Ctx()
    ctx.data[DC.CTX_BOT] = "not-running"
    assert "not running" in await dbot.send_reply(ctx, "hi", [])


# -- Slack -------------------------------------------------------------------------------

from plugins._slack_integration.helpers import bot as sbot
from plugins._slack_integration.helpers import constants as SC


@pytest.mark.parametrize("event,mode,allowed,kind", [
    ({"type": "message", "channel_type": "im", "user": "U1", "text": "hi"}, "off", [], "dm"),
    ({"type": "app_mention", "user": "U1", "channel": "C1", "text": "<@UB> hi"}, "mention", [], "mention"),
    ({"type": "message", "channel_type": "channel", "user": "U1", "channel": "C1", "text": "hi"}, "mention", [], ""),
    ({"type": "message", "channel_type": "channel", "user": "U1", "channel": "C1", "text": "hi"}, "all", [], "channel"),
    ({"type": "message", "channel_type": "channel", "user": "U1", "channel": "C1", "text": "<@UB> hi"}, "all", [], ""),
    ({"type": "app_mention", "user": "U1", "channel": "C1"}, "mention", ["C2"], ""),
    ({"type": "message", "channel_type": "im", "user": "UB", "text": "echo"}, "mention", [], ""),
    ({"type": "message", "channel_type": "im", "bot_id": "B1", "user": "U1"}, "mention", [], ""),
    ({"type": "message", "channel_type": "im", "subtype": "message_changed", "user": "U1"}, "mention", [], ""),
])
def test_slack_event_filtering(event, mode, allowed, kind):
    assert sbot.classify_event(event, "UB", mode, allowed) == kind


def test_markdown_becomes_slack_mrkdwn_outside_code():
    out = sbot.to_mrkdwn("# Title\n**bold** ~~gone~~ [site](https://example.com) `**keep**`\n```\n**keep**\n```")
    assert out.startswith("*Title*") and "*bold*" in out and "~gone~" in out
    assert "<https://example.com|site>" in out and "`**keep**`" in out and "```\n**keep**\n```" in out


@pytest.mark.asyncio
async def test_slack_channel_mention_is_threaded_and_reaches_the_agent(captured, monkeypatch):
    seen, ctx = captured
    reactions = []

    class Web:
        async def reactions_add(self, **kw): reactions.append(kw)

    b = sbot.SlackBot("ws", {"allowed_users": ["U1"], "channel_mode": "mention"})
    b.web, b.bot_user_id = Web(), "UB"
    monkeypatch.setattr(sbot, "current_cfg", lambda name: {})
    await b._on_event({"type": "app_mention", "user": "U1", "channel": "C9", "ts": "111.2", "text": "<@UB> build it"})
    key, _, data = seen["created"][0]
    assert key == "ws:U1:C9:111.2" and data[SC.CTX_CHANNEL] == "C9"
    assert ctx.data[SC.CTX_THREAD] == "111.2"
    assert seen["delivered"][0][0].endswith("U1: build it")
    assert reactions and reactions[0]["name"] == SC.WORKING_REACTION


@pytest.mark.asyncio
async def test_slack_ignores_members_not_on_the_allowlist(captured, monkeypatch):
    seen, _ = captured
    b = sbot.SlackBot("ws", {"allowed_users": ["U1"]})
    b.bot_user_id = "UB"
    monkeypatch.setattr(sbot, "current_cfg", lambda name: {})
    await b._on_event({"type": "message", "channel_type": "im", "user": "U2", "channel": "D1", "text": "hi"})
    assert seen["created"] == []


# -- permission cap marker -------------------------------------------------------------------

def test_both_integrations_set_the_permission_cap_marker():
    from plugins._permissions.helpers import config as perm_config

    assert perm_config.CHANNEL_MARKERS["discord"] == DC.CTX_CHANNEL
    assert perm_config.CHANNEL_MARKERS["slack"] == SC.CTX_CHANNEL
