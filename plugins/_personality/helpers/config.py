"""Personality list storage.

The list of personalities (name + system-prompt text) is global config,
shared across every chat - like model presets. Which personality is
*active* for a given chat is not stored here at all: it lives on that
chat's own AgentContext (context.data["personality"]), the same way the
agent profile selection does, so different chats can have different
personalities active at once.
"""

from __future__ import annotations

import uuid

DEFAULT_ID = "default"


def _default_personalities() -> list[dict]:
    return [
        {"id": DEFAULT_ID, "name": "Default", "prompt": "", "builtin": True},
    ]


def get_personalities() -> list[dict]:
    from helpers import plugins

    cfg = plugins.get_plugin_config("_personality") or {}
    items = cfg.get("personalities")
    if not isinstance(items, list) or not items:
        return _default_personalities()

    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        out.append({
            "id": str(item["id"]),
            "name": str(item.get("name") or item["id"]),
            "prompt": str(item.get("prompt") or ""),
            "builtin": bool(item.get("builtin", False)),
        })

    if not any(p["id"] == DEFAULT_ID for p in out):
        out.insert(0, _default_personalities()[0])

    return out


def get_personality(personality_id: str) -> dict | None:
    for p in get_personalities():
        if p["id"] == personality_id:
            return p
    return None


def _save(items: list[dict]) -> None:
    from helpers import plugins

    plugins.save_plugin_config("_personality", "", "", {"personalities": items})


def save_personality(personality_id: str | None, name: str, prompt: str) -> dict:
    """Create a personality (personality_id is None/unknown) or update one
    (personality_id matches an existing entry, including a builtin - only
    deleting a builtin is blocked, not editing it)."""

    name = str(name or "").strip()
    if not name:
        raise ValueError("name is required")
    prompt = str(prompt or "")

    items = get_personalities()
    existing = next((p for p in items if p["id"] == personality_id), None) if personality_id else None

    if existing:
        existing["name"] = name
        existing["prompt"] = prompt
        result = existing
    else:
        new_id = uuid.uuid4().hex[:12]
        result = {"id": new_id, "name": name, "prompt": prompt, "builtin": False}
        items.append(result)

    _save(items)
    return result


def delete_personality(personality_id: str) -> None:
    if personality_id == DEFAULT_ID:
        raise ValueError("the Default personality cannot be deleted")

    items = get_personalities()
    remaining = [p for p in items if p["id"] != personality_id]
    if len(remaining) == len(items):
        raise ValueError(f"no personality with id {personality_id!r}")

    _save(remaining)
