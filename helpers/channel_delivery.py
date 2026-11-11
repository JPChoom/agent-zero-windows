"""Reliable delivery of agent replies to messaging channels.

A reply used to get one attempt. Discord and Slack logged a failure and
dropped the reply, Telegram reported a failed send as a success, WhatsApp
and email asked the language model to resend (twice), and nothing survived
a restart. Now every channel sends through `deliver`:

1. Retry in line on a temporary failure (network trouble, a timeout, 429,
   5xx, a bot that is restarting), a few seconds apart, waiting at least as
   long as the service asks (`retry after N`).
2. A failure that cannot get better (bot blocked, chat or channel gone,
   bad credentials, a 4xx other than 429) is not retried or queued: the
   caller gets it back as `permanent`.
3. A reply still failing after the in-line retries is queued in
   `usr/channel_outbox.json` and retried by the job loop (`drain`, about
   once a minute, with growing gaps) until it is delivered, turns out to be
   permanent, or is `QUEUE_MAX_AGE` old. The queue survives a restart.

Delivery is at-least-once: when a send succeeded but its confirmation was
lost (a timeout), the retry can deliver the reply twice. A queued reply is
replayed as plain text and attachments; a Telegram keyboard is not kept.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from helpers import files
from helpers.print_style import PrintStyle

OUTBOX_FILE = "usr/channel_outbox.json"
RETRY_DELAYS = (2.0, 6.0, 20.0)  # in-line, per reply
RETRY_AFTER_CAP = 60.0  # longest wait an in-line retry honours; longer goes to the queue
QUEUE_DELAYS = (60.0, 180.0, 600.0, 1800.0, 3600.0)  # then hourly
QUEUE_MAX_AGE = 24 * 3600.0
QUEUE_MAX_ATTEMPTS = 12
QUEUE_MAX_ENTRIES = 200

_PERMANENT = (
    "forbidden", "bot was blocked", "blocked by the user", "chat not found", "user is deactivated",
    "unauthorized", "invalid token", "authentication", "not authorized", "missing permissions", "missing access",
    "unknown channel", "channel_not_found", "not_in_channel", "is_archived", "account_inactive",
    "file not found", "no chat_id", "no chat id", "no telegram bot configured", "no whatsapp chat",
    "bad request", "http 400", "http 401", "http 403", "http 404",
    " 535", " 550", " 551", " 553", " 554",
)
_TRANSIENT = (
    "timeout", "timed out", "connection", "network", "temporarily", "try again", "retry after", "too many requests",
    "rate limit", "ratelimited", "http 429", "http 500", "http 502", "http 503", "http 504", "server error",
    "service unavailable", "bad gateway", "gateway", "not running", "not connected", "refused", "reset by peer",
    "eof", "ssl", " 421", " 450", " 451", " 452",
)
_RETRY_AFTER = re.compile(r"retry[ _-]?after\D{0,12}(\d+(?:\.\d+)?)", re.IGNORECASE)

SendFunc = Callable[[Any, str, "list[str]"], Awaitable[Any]]
_store_lock = threading.Lock()


@dataclass
class Delivery:
    ok: bool
    error: str = ""
    kind: str = ""  # "permanent" or "transient" when not ok
    queued: bool = False
    attempts: int = 1


def _text_of(error: Any) -> str:
    if isinstance(error, BaseException):
        return f"{type(error).__name__}: {error}"
    return str(error or "")


def classify(error: Any) -> str:
    """"permanent" for a failure that retrying cannot fix, else "transient"
    (also for an error nobody recognises: retries are bounded)."""
    text = " " + _text_of(error).lower()  # the leading space lets " 550" match a message that starts with it
    name = type(error).__name__.lower() if isinstance(error, BaseException) else ""
    if name in ("telegramretryafter", "telegramnetworkerror", "telegramservererror", "timeouterror"):
        return "transient"
    if name in ("telegramforbiddenerror", "telegramunauthorizederror", "telegramnotfound"):
        return "permanent"
    if any(mark in text for mark in _TRANSIENT):
        return "transient"
    if any(mark in text for mark in _PERMANENT):
        return "permanent"
    return "transient"


def retry_after(error: Any) -> float:
    """Seconds the service asked us to wait, or 0."""
    value = getattr(error, "retry_after", None) if isinstance(error, BaseException) else None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    match = _RETRY_AFTER.search(_text_of(error))
    return float(match.group(1)) if match else 0.0


def sender_for(channel: str) -> SendFunc | None:
    """The channel's send function (context, text, attachments) -> error."""
    import importlib

    from helpers import channel_approvals

    target = channel_approvals.SENDERS.get(channel)
    if not target:
        return None
    try:
        return getattr(importlib.import_module(target[0]), target[1])
    except Exception:
        return None


async def _attempt(send: SendFunc, context, text: str, attachments: list[str]) -> str:
    """One send. Returns "" on success, else the error text."""
    from helpers.errors import format_error

    try:
        error = await send(context, text, attachments)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return format_error(exc) or _text_of(exc)
    return str(error or "")


def _note(context, kind: str, heading: str, content: str) -> None:
    try:
        context.log.log(type=kind, heading=heading, content=content)
    except Exception:
        pass


async def deliver(
    context,
    text: str,
    attachments: list[str] | None = None,
    *,
    send: SendFunc | None = None,
    queue: bool = True,
    delays: tuple[float, ...] | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
) -> Delivery:
    """Send `text` (and `attachments`) to the channel `context` came from.

    `send` defaults to the channel's own sender. With `queue` off (approval
    questions, which expire) a still-failing reply is only reported."""
    from helpers import channels

    attachments = list(attachments or [])
    channel = channels.channel_of(context)
    send = send or sender_for(channel)
    if send is None:
        return Delivery(False, f"no sender for channel '{channel or 'webui'}'", "permanent")
    delays = RETRY_DELAYS if delays is None else delays
    sleep = sleep or asyncio.sleep
    error, kind, attempts = "", "", 0
    for index in range(len(delays) + 1):
        attempts += 1
        error = await _attempt(send, context, text, attachments)
        if not error:
            return Delivery(True, attempts=attempts)
        kind = classify(error)
        if kind == "permanent" or index == len(delays):
            break
        wait = max(delays[index], retry_after(error))
        if wait > max(RETRY_AFTER_CAP, delays[index]):
            break  # the service asked for a long pause: let the queue handle it
        await sleep(wait)
    if kind == "permanent":
        return Delivery(False, error, "permanent", attempts=attempts)
    if not queue:
        return Delivery(False, error, "transient", attempts=attempts)
    queued = enqueue(context, channel, text, attachments, error)
    if queued:
        PrintStyle.warning(f"{channel}: reply not delivered ({error}); queued for retry")
        _note(context, "warning", f"{channel.capitalize()} reply queued",
              f"It could not be sent ({error}). It will be retried automatically for up to "
              f"{int(QUEUE_MAX_AGE // 3600)} hours, also after a restart.")
    return Delivery(False, error, "transient", queued=queued, attempts=attempts)


# ---------------------------------------------------------------- the queue

def _path() -> str:
    return files.get_abs_path(OUTBOX_FILE)


def _read() -> list[dict]:
    path = _path()
    if not os.path.isfile(path):
        return []
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        try:
            os.replace(path, path + ".bad")  # keep the unreadable file, start a new queue
        except OSError:
            pass
        return []


def _write(entries: list[dict]) -> None:
    files.write_file_atomic(_path(), json.dumps(entries, indent=1, ensure_ascii=False))


def pending() -> list[dict]:
    with _store_lock:
        return _read()


def enqueue(context, channel: str, text: str, attachments: list[str], error: str, now: float | None = None) -> bool:
    """Queue a reply for retry. False when it is already queued."""
    now = time.time() if now is None else now
    with _store_lock:
        entries = _read()
        if any(e.get("context_id") == context.id and e.get("text") == text and e.get("attachments") == attachments
               for e in entries):
            return False
        entries.append({
            "id": uuid.uuid4().hex[:12], "channel": channel, "context_id": context.id, "text": text,
            "attachments": attachments, "created": now, "attempts": 0, "next_try": now + QUEUE_DELAYS[0],
            "last_error": str(error)[:500],
        })
        if len(entries) > QUEUE_MAX_ENTRIES:
            entries = sorted(entries, key=lambda e: e.get("created", 0))[-QUEUE_MAX_ENTRIES:]
        try:
            _write(entries)
        except OSError as exc:
            PrintStyle.error(f"Channel outbox could not be saved: {exc}")
            return False
    return True


def _delay_for(attempts: int) -> float:
    return QUEUE_DELAYS[min(attempts, len(QUEUE_DELAYS) - 1)]


async def drain(now: float | None = None, send: SendFunc | None = None) -> dict[str, int]:
    """Retry every queued reply that is due. Run by the job loop."""
    from agent import AgentContext

    stats = {"delivered": 0, "dropped": 0, "waiting": 0}
    now = time.time() if now is None else now
    with _store_lock:
        entries = _read()
    due = [e for e in entries if e.get("next_try", 0) <= now]
    if not due:
        return {**stats, "waiting": len(entries)}
    finished: dict[str, dict | None] = {}  # id -> replacement entry, or None to remove
    for entry in sorted(due, key=lambda e: e.get("created", 0)):
        context = AgentContext.get(entry.get("context_id", ""))
        sender = send or sender_for(entry.get("channel", ""))
        if context is None or sender is None:
            finished[entry["id"]] = None
            stats["dropped"] += 1
            continue
        attachments = [p for p in entry.get("attachments") or [] if os.path.isfile(files.fix_dev_path(p))]
        error = await _attempt(sender, context, entry.get("text", ""), attachments)
        if not error:
            finished[entry["id"]] = None
            stats["delivered"] += 1
            _note(context, "info", f"{entry['channel'].capitalize()} reply delivered", "A queued reply was sent.")
            continue
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = error[:500]
        expired = now - entry.get("created", now) > QUEUE_MAX_AGE or entry["attempts"] >= QUEUE_MAX_ATTEMPTS
        if classify(error) == "permanent" or expired:
            finished[entry["id"]] = None
            stats["dropped"] += 1
            _note(context, "error", f"{entry['channel'].capitalize()} reply could not be delivered",
                  f"Giving up after {entry['attempts']} retries: {error}")
            PrintStyle.error(f"{entry['channel']}: queued reply dropped: {error}")
        else:
            entry["next_try"] = now + max(_delay_for(entry["attempts"]), retry_after(error))
            finished[entry["id"]] = entry
    with _store_lock:
        current = _read()  # entries queued while we were sending are kept
        merged = []
        for item in current:
            if item.get("id") in finished:
                if finished[item["id"]] is not None:
                    merged.append(finished[item["id"]])
            else:
                merged.append(item)
        _write(merged)
        stats["waiting"] = len(merged)
    return stats
