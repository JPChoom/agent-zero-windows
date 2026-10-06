"""Shared plumbing for chat-app integrations (Discord, Slack).

Each integration plugin owns its client library and message format; this
module owns what they have in common:

- `is_allowed`: the sender allowlist. Empty means *nobody* - a chat bridge
  into an agent that runs on the user's PC must be opted into per user.
- `ChannelState`: persistent "conversation key -> chat context id" map.
- `get_or_create_context`: one Agent Zero chat per conversation, carrying the
  integration's context-data marker (which `_permissions` uses to cap the
  chat's permission mode).
- `deliver`: hand a message to the agent, or queue it while a run is active.
- `BotThread`: run a client's own asyncio loop in a dedicated daemon thread,
  so its connection survives independently of Agent Zero's job loop, and
  let agent-side code (another loop) schedule sends on it.
- `last_response`, `split_text`, `download_path`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Awaitable, Callable

from helpers import files
from helpers.print_style import PrintStyle

DOWNLOAD_FOLDER = "usr/uploads"

# Running clients, keyed "<integration>:<bot name>". Kept here, in a core
# module, because plugin modules are re-imported when plugin files change:
# a registry inside the plugin would be lost while its threads kept running,
# and the next sync would start duplicate bots.
RUNNING: dict[str, Any] = {}

# Restart backoff per client key: a bad token or a network outage must not
# reconnect on every job-loop tick. Grows 30 s -> 30 min, reset by a
# successful connection or a config change.
_BACKOFF: dict[str, float] = {}


def restart_allowed(key: str, thread: "BotThread") -> bool:
    if thread.ended_at is None:
        return True
    delay = _BACKOFF.get(key, 30.0)
    if time.monotonic() - thread.ended_at < delay:
        return False
    _BACKOFF[key] = min(delay * 2, 1800.0)
    return True


def mark_healthy(key: str) -> None:
    _BACKOFF.pop(key, None)


def sync_clients(prefix: str, wanted: dict[str, dict], fingerprint: Callable[[dict], tuple],
                 factory: Callable[[str, dict], Any]) -> None:
    """Make RUNNING["<prefix>:<name>"] match `wanted` (name -> config).

    A client whose connection settings changed is restarted at once; a client
    that died with unchanged settings is restarted only after its backoff.
    Clients must expose `cfg`, `thread` (BotThread), `alive`, `start()` and `stop()`.
    """
    for key in [k for k in RUNNING if k.startswith(f"{prefix}:")]:
        client = RUNNING[key]
        cfg = wanted.get(key.split(":", 1)[1])
        if cfg is None or fingerprint(cfg) != fingerprint(client.cfg):
            client.stop()
            RUNNING.pop(key, None)
            _BACKOFF.pop(key, None)
        elif not client.alive and restart_allowed(key, client.thread):
            RUNNING.pop(key, None)
    for name, cfg in wanted.items():
        key = f"{prefix}:{name}"
        if key not in RUNNING:
            client = factory(name, cfg)
            RUNNING[key] = client
            client.start()


def is_allowed(allowed: list | None, user_id: str, names: list[str] | tuple[str, ...] = ()) -> bool:
    """True if the sender is on the allowlist (by id or, case-insensitively, by name)."""
    entries = [str(e).strip().lstrip("@").lower() for e in (allowed or []) if str(e).strip()]
    if not entries:
        return False
    candidates = {str(user_id).strip().lower()} | {str(n).strip().lstrip("@").lower() for n in names if n}
    return any(entry in candidates for entry in entries)


class ChannelState:
    """`usr/plugins/<plugin>/state.json`: conversation key -> context id."""

    def __init__(self, plugin_name: str):
        self.path = files.get_abs_path("usr", "plugins", plugin_name, "state.json")
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def get(self, key: str) -> str:
        with self.lock:
            return str(self._load().get("chats", {}).get(key, "") or "")

    def set(self, key: str, context_id: str) -> None:
        with self.lock:
            data = self._load()
            data.setdefault("chats", {})[key] = context_id
            self._save(data)

    def drop(self, key: str) -> None:
        with self.lock:
            data = self._load()
            if data.get("chats", {}).pop(key, None) is not None:
                self._save(data)


def get_or_create_context(state: ChannelState, key: str, name: str, data: dict, project: str = ""):
    """Existing context for this conversation, or a new one stamped with `data`."""
    from agent import AgentContext
    from helpers import projects
    from initialize import initialize_agent

    ctx_id = state.get(key)
    if ctx_id:
        ctx = AgentContext.get(ctx_id)
        if ctx:
            ctx.data.update({k: v for k, v in data.items() if not k.startswith("_")})
            return ctx
        state.drop(key)

    ctx = AgentContext(initialize_agent(), name=name)
    ctx.data.update(data)
    if project:
        try:
            projects.activate_project(ctx.id, project)
        except Exception as e:
            PrintStyle.error(f"{name}: could not activate project {project!r}: {e}")
    state.set(key, ctx.id)
    return ctx


def deliver(context, text: str, attachments: list[str], source: str) -> str:
    """Send to the agent; returns "" when started, or a queue notice."""
    from agent import UserMessage
    from helpers import message_queue as mq
    from helpers.persist_chat import save_tmp_chat

    if context.is_running():
        item = mq.add(context, text, attachments)
        save_tmp_chat(context)
        seq = item.get("seq", len(mq.get_queue(context)))
        return f"Queued message #{seq}. Send /send to run it now, or /steer <message> to interrupt the current run."

    msg_id = str(uuid.uuid4())
    mq.log_user_message(context, text, attachments, message_id=msg_id, source=f" ({source})")
    context.communicate(UserMessage(message=text, attachments=attachments, id=msg_id))
    save_tmp_chat(context)
    return ""


def last_response(context) -> str:
    with context.log._lock:
        logs = list(context.log.logs)
    for item in reversed(logs):
        if item.type == "response":
            return item.content or ""
    return ""


def split_text(text: str, limit: int) -> list[str]:
    """Split on paragraph, then line, then space boundaries; never mid-word if avoidable."""
    text = str(text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"))
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut < limit // 3:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def download_path(prefix: str, filename: str) -> tuple[str, str]:
    """(path to write, same path) for an incoming attachment in usr/uploads."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(str(filename or "file")))[-120:] or "file"
    folder = files.get_abs_path(DOWNLOAD_FOLDER)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{prefix}_{uuid.uuid4().hex[:8]}_{safe}")
    return path, path


class BotThread:
    """A dedicated thread + event loop for one long-lived chat-app client."""

    def __init__(self, label: str, main: Callable[["BotThread"], Awaitable[None]]):
        self.label = label
        self._main = main
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ready = threading.Event()
        self.error: str = ""
        self.ended_at: float | None = None
        self._thread = threading.Thread(target=self._run, name=f"chat-{label}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main(self))
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
            PrintStyle.error(f"{self.label}: stopped: {self.error}")
        finally:
            try:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            self.loop.close()
            self.ended_at = time.monotonic()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, coro) -> Future:
        if not self.loop or not self.alive:
            coro.close()
            raise RuntimeError(f"{self.label} is not running")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def run(self, coro, timeout: float = 120) -> Any:
        """Await `coro` on this thread's loop from any other loop."""
        return await asyncio.wait_for(asyncio.wrap_future(self.submit(coro)), timeout)
