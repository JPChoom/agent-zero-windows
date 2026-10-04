"""Per-chat permission mode, held in memory only.

The mode used to be one global value persisted in this plugin's config file:
every chat shared it, it survived restarts, and editing config.json could
switch on "bypass". Now:

- Each chat (AgentContext id) has its own mode. Subordinate agents share
  their parent's context, so they follow the same mode.
- Nothing is persisted. After a restart every chat starts at the default
  mode again; a new chat starts at the default; switching a chat to a
  different project resets it to the default.
- The default comes from the `permissions_default_mode` setting
  (Settings > Security). It can never be "bypass".
- "bypass" additionally expires after `bypass_auto_off_hours` (0 = never by
  time; it still ends on restart / new chat / project switch). Unlocking it
  requires the Bypass password - that check lives in the API, not here.
"""

from __future__ import annotations

import threading
import time

from plugins._permissions.helpers import rules

SAFE_FALLBACK = "manual"

_lock = threading.Lock()
# context id -> {"mode", "project", "bypass_until" (epoch or 0), "unlocked_at"}
_entries: dict[str, dict] = {}


def default_mode() -> str:
    try:
        from helpers.settings import get_settings

        mode = str(get_settings().get("permissions_default_mode", SAFE_FALLBACK) or "").strip().lower()
    except Exception:
        mode = SAFE_FALLBACK
    if mode not in rules.MODES or mode == "bypass":
        return SAFE_FALLBACK
    return mode


def bypass_hours() -> float:
    try:
        from helpers.settings import get_settings

        hours = float(get_settings().get("bypass_auto_off_hours", 4.0) or 0)
    except Exception:
        hours = 4.0
    return max(0.0, hours)


def get_mode(context_id: str | None, project: str = "", now: float | None = None) -> dict:
    """Effective mode for a chat: {"mode", "bypass_until", "unlocked_at",
    "expired"}. `expired` is True exactly once, on the call that noticed a
    timed-out bypass, so the caller can tell the user."""
    now = time.time() if now is None else now
    default = default_mode()
    if not context_id:
        return {"mode": default, "bypass_until": 0, "unlocked_at": 0, "expired": False}

    with _lock:
        entry = _entries.get(context_id)
        expired = False
        if entry is not None and entry.get("project", "") != (project or ""):
            _entries.pop(context_id, None)  # project switched: back to default
            entry = None
        if (
            entry is not None
            and entry["mode"] == "bypass"
            and entry.get("bypass_until")
            and now >= entry["bypass_until"]
        ):
            _entries.pop(context_id, None)
            entry = None
            expired = True

    if entry is None:
        return {"mode": default, "bypass_until": 0, "unlocked_at": 0, "expired": expired}
    return {
        "mode": entry["mode"],
        "bypass_until": entry.get("bypass_until", 0),
        "unlocked_at": entry.get("unlocked_at", 0),
        "expired": False,
    }


def set_mode(context_id: str, mode: str, project: str = "", now: float | None = None) -> dict:
    """Set a chat's mode. Callers must have verified the Bypass password
    before passing "bypass". Raises ValueError for unknown modes."""
    normalized = str(mode or "").strip().lower()
    if normalized not in rules.MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(rules.MODES)}")
    if not context_id:
        raise ValueError("no chat selected")
    now = time.time() if now is None else now
    entry = {"mode": normalized, "project": project or "", "bypass_until": 0, "unlocked_at": 0}
    if normalized == "bypass":
        hours = bypass_hours()
        entry["unlocked_at"] = now
        entry["bypass_until"] = now + hours * 3600 if hours > 0 else 0
    with _lock:
        if normalized == default_mode():
            _entries.pop(context_id, None)
        else:
            _entries[context_id] = entry
    return get_mode(context_id, project, now=now)


def forget(context_id: str) -> None:
    with _lock:
        _entries.pop(context_id, None)


def clear_all() -> None:
    with _lock:
        _entries.clear()


def context_project(context) -> str:
    try:
        from helpers import projects

        return projects.get_context_project_name(context) or ""
    except Exception:
        return ""
