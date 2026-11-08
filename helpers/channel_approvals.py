"""Answer approval questions from the phone.

A permission, safety-policy or safety-check question in a chat that came in
over a messaging channel used to appear only in the WebUI, so someone on
their phone could only wait for it to time out. Now the question also goes to
the channel with a short code, and a reply such as `yes 7KQ2` or `no 7KQ2`
answers it without reaching the agent.

Who can answer: only senders the channel already accepts (its allowlist is
checked before a message gets this far), and only on channels in
APPROVAL_CHANNELS whose allowlist is not empty. Email is never one of them:
a sender address is easy to fake. The code is tied to one pending question
in one chat and is dropped once answered.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import secrets
from typing import Any

APPROVAL_CHANNELS = {"telegram", "whatsapp", "discord", "slack"}
CODES_KEY = "_channel_approval_codes"  # chat data, in memory: {code: approval_id}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
REPLY_RE = re.compile(r"^\s*(yes|y|allow|approve|ok|no|n|deny|block)\s+([A-Za-z0-9]{4})\s*[.!]?\s*$", re.IGNORECASE)
YES_WORDS = {"yes", "y", "allow", "approve", "ok"}

# channel -> (module, send function(context, text, attachments) -> error or "")
SENDERS = {
    "telegram": ("plugins._telegram_integration.helpers.handler", "send_telegram_reply"),
    "whatsapp": ("plugins._whatsapp_integration.helpers.handler", "send_wa_reply"),
    "email": ("plugins._email_integration.helpers.handler", "send_email_reply"),
    "discord": ("plugins._discord_integration.helpers.bot", "send_reply"),
    "slack": ("plugins._slack_integration.helpers.bot", "send_reply"),
}

_tasks: set = set()


async def send(context, text: str, attachments: list[str] | None = None) -> str:
    """Send a message to the channel this chat came from. Returns "" or an error."""
    from helpers import channels

    channel = channels.channel_of(context)
    target = SENDERS.get(channel)
    if not target:
        return f"no sender for channel '{channel or 'webui'}'"
    try:
        function = getattr(importlib.import_module(target[0]), target[1])
        error = await function(context, text, attachments or [])
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return str(error or "")


def _channel_allowlist_set(context, channel: str) -> bool:
    """Does the channel's bot/handler for this chat have a non-empty allowlist?
    Plugins expose it through `channel_allowlist_set(context)`; one that does
    not counts as open, so it gets no phone approvals."""
    plugin = {"telegram": "_telegram_integration", "whatsapp": "_whatsapp_integration",
              "discord": "_discord_integration", "slack": "_slack_integration"}.get(channel)
    if not plugin:
        return False
    try:
        module = importlib.import_module(f"plugins.{plugin}.helpers.allowlist")
        return bool(module.channel_allowlist_set(context))
    except Exception:
        return False


def _governing(agent):
    from helpers import channels, parallel_tools

    context, _orphaned = parallel_tools.governing_context(getattr(agent, "context", None))
    context = context or getattr(agent, "context", None)
    return context, channels.channel_of(context)


def can_answer_by_phone(agent) -> bool:
    context, channel = _governing(agent)
    return context is not None and channel in APPROVAL_CHANNELS and _channel_allowlist_set(context, channel)


def announce(agent, approval_id: str, question: str) -> str:
    """Send the question to the chat's channel with a reply code. Returns the
    code, or "" when this chat cannot be answered by phone. Never raises."""
    try:
        context, channel = _governing(agent)
        if context is None or channel not in APPROVAL_CHANNELS or not _channel_allowlist_set(context, channel):
            return ""
        codes = context.get_data(CODES_KEY) or {}
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        while code in codes:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        codes[code] = approval_id
        context.set_data(CODES_KEY, codes)
        text = (f"Approval needed: {str(question).strip()[:1500]}\n\n"
                f"Reply  yes {code}  to allow or  no {code}  to refuse.")
        task = asyncio.get_running_loop().create_task(send(context, text))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return code
    except Exception:
        return ""


def forget(agent, approval_id: str) -> None:
    """Drop the code once the question is answered any other way."""
    try:
        context, _ = _governing(agent)
        codes = context.get_data(CODES_KEY) or {}
        for code, value in list(codes.items()):
            if value == approval_id:
                codes.pop(code)
        context.set_data(CODES_KEY, codes)
    except Exception:
        pass


def try_answer(context, message: Any) -> str | None:
    """If `message` answers a pending question of this chat, resolve it and
    return the confirmation to send back; else None (a normal message)."""
    from helpers import channels

    text = str(getattr(message, "message", message) or "")
    match = REPLY_RE.match(text)
    if not match or channels.channel_of(context) not in APPROVAL_CHANNELS:
        return None
    codes = context.get_data(CODES_KEY) or {}
    code = match.group(2).upper()
    approval_id = codes.get(code)
    if not approval_id:
        return f"No open question with code {code}." if len(codes) else None
    approved = match.group(1).lower() in YES_WORDS
    from plugins._safety_policy.helpers import approval_registry

    resolved = approval_registry.resolve(approval_id, approved)
    codes.pop(code, None)
    context.set_data(CODES_KEY, codes)
    if not resolved:
        return f"That question ({code}) was already answered or timed out."
    return ("Allowed." if approved else "Refused.") + f" ({code})"
