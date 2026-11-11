"""Which chats a Telegram user may list and adopt with /sessions.

The picker used to offer every chat on the PC: WebUI chats, other users' and
other channels' chats, child-agent and background chats. With more than one
allowlisted user that shows one user's chat names to another and lets them
adopt the chat, read its history through the agent and take over its Telegram
session. A user now sees their own chats from this bot; the owner can add
plain WebUI chats with the bot's `allow_webui_sessions` setting. Chats of
other channels, of other Telegram users and bots, child agents and
background or scheduled contexts are never offered.
"""

from __future__ import annotations

from helpers import channel_locks, channels
from plugins._telegram_integration.helpers.constants import CTX_TG_BOT, CTX_TG_USER_ID

CHILD_OF_KEY = "child_of"  # helpers/child_agents.py


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def visible(context, candidate) -> bool:
    """May the Telegram chat `context` list and adopt `candidate`?"""
    from agent import AgentContextType

    if candidate is context or getattr(candidate, "id", None) == getattr(context, "id", ""):
        return True
    data = getattr(candidate, "data", None) or {}
    if getattr(candidate, "type", None) != AgentContextType.USER or data.get(CHILD_OF_KEY):
        return False
    mine = getattr(context, "data", None) or {}
    if data.get(CTX_TG_BOT):
        return _same(data.get(CTX_TG_BOT), mine.get(CTX_TG_BOT)) and _same(data.get(CTX_TG_USER_ID), mine.get(CTX_TG_USER_ID))
    if channels.channel_of(candidate):
        return False  # another channel's chat
    cfg, _user = channel_locks.channel_config(context)
    return bool(cfg.get("allow_webui_sessions"))
