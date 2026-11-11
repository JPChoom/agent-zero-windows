"""The channel admin boundary (audit 2026-11-10): who may switch what from a chat channel.

- F1: Telegram's /sessions lists and adopts only the user's own chats.
- F2: /agent and /project cannot change what the channel's settings pin.
- F4: an email account can require a sender the mail server verified.
(F3, Discord display names, is tested in test_chat_integrations.py.)
"""

from __future__ import annotations

import email
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import AgentContextType
from helpers import channel_locks, integration_commands

ROOT = Path(__file__).resolve().parents[1]
session_scope = pytest.importorskip("plugins._telegram_integration.helpers.session_scope")


def ctx(cid="c1", kind=AgentContextType.USER, **data):
    return SimpleNamespace(id=cid, type=kind, data=data, name=cid)


def telegram(cid, bot="main", user=1, **extra):
    return ctx(cid, telegram_bot=bot, telegram_user_id=user, telegram_chat_id=user, **extra)


# -- F1: sessions are scoped ------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    """Control the live channel settings the scope reads."""
    state = {"cfg": {}}
    monkeypatch.setattr(channel_locks, "channel_config", lambda context: (state["cfg"], ""))
    return state


def test_a_user_sees_their_own_telegram_chats_only(cfg):
    me = telegram("me")
    assert session_scope.visible(me, me)
    assert session_scope.visible(me, telegram("mine-too"))
    assert not session_scope.visible(me, telegram("other-user", user=2))
    assert not session_scope.visible(me, telegram("other-bot", bot="second"))


def test_webui_chats_need_the_setting(cfg):
    me, webui = telegram("me"), ctx("webui")
    assert not session_scope.visible(me, webui)
    cfg["cfg"] = {"allow_webui_sessions": True}
    assert session_scope.visible(me, webui)


@pytest.mark.parametrize("candidate", [
    ctx("discord", discord_channel_id="1"),
    ctx("email", email_sender="a@example.com"),
    ctx("child", child_of="parent"),
    ctx("job", kind=AgentContextType.BACKGROUND),
    ctx("task", kind=AgentContextType.TASK),
])
def test_some_chats_are_never_offered(cfg, candidate):
    cfg["cfg"] = {"allow_webui_sessions": True}
    assert not session_scope.visible(telegram("me"), candidate)


def test_the_sessions_text_lists_only_visible_chats(cfg, monkeypatch):
    from agent import AgentContext

    me, other = telegram("me"), telegram("other", user=2)
    other.name = "Secret project plan"
    me.output = other.output = lambda: {"last_message": ""}
    me.is_running = other.is_running = lambda: False
    monkeypatch.setattr(AgentContext, "all", staticmethod(lambda: [me, other]))
    text = integration_commands._handle_sessions(me)
    assert "me" in text and "Secret project plan" not in text


def test_the_picker_uses_the_scope():
    source = (ROOT / "plugins/_telegram_integration/helpers/command_ui.py").read_text(encoding="utf-8")
    assert "session_scope.visible(context, item)" in source
    assert source.count("_session_items(context)") == 2 and "_session_items()" not in source


# -- F2: pinned profile and project --------------------------------------------------------

def _plugins(monkeypatch, plugin, config):
    monkeypatch.setattr(channel_locks.plugins, "get_plugin_config", lambda name, *a, **k: config if name == plugin else {})


def test_a_pinned_profile_and_project_are_locked(monkeypatch):
    _plugins(monkeypatch, "_telegram_integration", {"bots": [{"name": "main", "agent_profile": "researcher", "default_project": "notes"}]})
    assert channel_locks.pinned(telegram("c")) == {"profile": True, "project": True}


def test_nothing_is_locked_without_a_pin(monkeypatch):
    _plugins(monkeypatch, "_telegram_integration", {"bots": [{"name": "main", "agent_profile": "", "default_project": ""}]})
    assert channel_locks.pinned(telegram("c")) == {"profile": False, "project": False}


def test_allow_switching_unlocks(monkeypatch):
    _plugins(monkeypatch, "_telegram_integration",
             {"bots": [{"name": "main", "agent_profile": "researcher", "default_project": "notes", "allow_switching": True}]})
    assert channel_locks.pinned(telegram("c")) == {"profile": False, "project": False}


def test_a_per_user_project_pins_only_that_user(monkeypatch):
    _plugins(monkeypatch, "_discord_integration", {"bots": [{"name": "d", "user_projects": {"7": "work"}}]})
    mine = ctx("c", discord_channel_id="1", discord_bot="d", discord_user_id="7")
    other = ctx("c2", discord_channel_id="1", discord_bot="d", discord_user_id="8")
    assert channel_locks.pinned(mine) == {"profile": False, "project": True}
    assert channel_locks.pinned(other) == {"profile": False, "project": False}


def test_flat_and_list_configs_are_found(monkeypatch):
    _plugins(monkeypatch, "_whatsapp_integration", {"agent_profile": "researcher", "project": ""})
    assert channel_locks.pinned(ctx("w", wa_chat_id="1")) == {"profile": True, "project": False}
    _plugins(monkeypatch, "_email_integration", {"handlers": [{"name": "support", "project": "inbox"}]})
    assert channel_locks.pinned(ctx("e", email_sender="a@b.c", email_handler="support")) == {"profile": False, "project": True}


def test_a_removed_bot_or_a_webui_chat_is_not_locked(monkeypatch):
    _plugins(monkeypatch, "_telegram_integration", {"bots": [{"name": "other", "agent_profile": "researcher"}]})
    assert channel_locks.pinned(telegram("c")) == {"profile": False, "project": False}
    assert channel_locks.pinned(ctx("webui")) == {"profile": False, "project": False}


def test_the_commands_refuse_when_pinned(monkeypatch):
    from helpers import projects, subagents

    monkeypatch.setattr(projects, "get_active_projects_list", lambda: [{"name": "other", "title": "Other"}])
    monkeypatch.setattr(subagents, "get_all_agents_list", lambda: [{"key": "developer", "label": "Developer"}])
    monkeypatch.setattr(channel_locks, "pinned", lambda context: {"profile": True, "project": True})
    context = SimpleNamespace(data={}, get_data=lambda key: None, agent0=SimpleNamespace(config=SimpleNamespace(profile="researcher")),
                              is_running=lambda: False)
    assert "set in the channel's settings" in integration_commands._handle_agent(context, "developer")
    assert "set in the channel's settings" in integration_commands._handle_project(context, "other")
    assert "set in the channel's settings" in integration_commands._handle_project(context, "none")
    # looking is still allowed
    assert "Current agent: researcher" in integration_commands._handle_agent(context, "")


def test_unpinned_chats_switch_as_before(monkeypatch):
    from helpers import subagents

    monkeypatch.setattr(subagents, "get_all_agents_list", lambda: [{"key": "developer", "label": "Developer"}])
    monkeypatch.setattr(channel_locks, "pinned", lambda context: {"profile": False, "project": False})
    context = SimpleNamespace(data={}, get_data=lambda key: None, agent0=SimpleNamespace(config=SimpleNamespace(profile="researcher")),
                              is_running=lambda: False)
    assert "was not found" in integration_commands._handle_agent(context, "nonexistent")


# -- F4: a verified sender ------------------------------------------------------------------

imap_client = pytest.importorskip("plugins._email_integration.helpers.imap_client", reason="imapclient is not installed")


def mail(*results, sender="Boss <boss@bank.example>"):
    headers = "".join(f"Authentication-Results: {r}\n" for r in results)
    return email.message_from_string(f"{headers}From: {sender}\nSubject: hi\n\nbody\n"), sender


@pytest.mark.parametrize("results,expected", [
    (["mx.google.com; dkim=pass header.i=@bank.example; spf=pass"], True),
    (["mx.google.com; dkim=pass header.d=bank.example"], True),
    (["mx.google.com; dkim=pass header.d=mail.bank.example"], True),  # a subdomain signs for the domain
    (["mx.example.net; spf=pass; dmarc=pass action=none header.from=bank.example"], True),
    (["mx.google.com; dkim=pass header.d=attacker.example"], False),  # a valid signature of another domain
    (["mx.google.com; dkim=fail header.d=bank.example"], False),
    (["mx.google.com; spf=pass"], False),
    ([], False),
    # the sender can add headers of its own below the server's: only the topmost counts
    (["mx.google.com; dkim=fail header.d=bank.example", "forged.example; dmarc=pass"], False),
    (["mx.google.com; dkim=pass header.d=bank.example", "forged.example; dkim=fail"], True),
])
def test_sender_authenticated(results, expected):
    message, sender = mail(*results)
    assert imap_client.sender_authenticated(message, sender) is expected


def test_require_dkim_drops_unverified_mail():
    from plugins._email_integration.helpers import handler

    unknown = imap_client.InboundMessage("a@b.c", "s", "b")  # e.g. an Exchange message
    verified = imap_client.InboundMessage("a@b.c", "s", "b", authenticated=True)
    forged = imap_client.InboundMessage("a@b.c", "s", "b", authenticated=False)
    assert unknown.authenticated is None
    assert not handler.unverified_sender({}, forged) and not handler.unverified_sender({"require_dkim": False}, forged)
    assert handler.unverified_sender({"require_dkim": True}, forged)
    assert handler.unverified_sender({"require_dkim": True}, unknown)
    assert not handler.unverified_sender({"require_dkim": True}, verified)
