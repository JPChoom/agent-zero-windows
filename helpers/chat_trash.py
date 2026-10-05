"""Chat trash: deleted chats are moved here instead of being erased.

A trashed chat is its whole folder from ``usr/chats/<id>/`` moved to
``usr/chats/.trash/<trash_id>/`` plus a small ``trash.json`` describing it.
It can be restored (folder moved back and the context loaded again) or
purged for good. Entries older than ``RETENTION_DAYS`` are purged lazily,
whenever the trash is listed or a chat is trashed.

The startup loader only loads ``usr/chats/*/chat.json``, so ``.trash`` is
never loaded as a chat. Provider-side stored responses are deleted only on
purge, so a restored chat can still continue its conversation.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from helpers import files, persist_chat

TRASH_FOLDER = f"{persist_chat.CHATS_FOLDER}/.trash"
TRASH_META_FILE = "trash.json"
RETENTION_DAYS = 30

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.RLock()


class TrashError(Exception):
    pass


def _trash_path(trash_id: str, *parts: str) -> str:
    if not _SAFE_ID.match(trash_id or ""):
        raise TrashError("Invalid trash id.")
    return files.get_abs_path(TRASH_FOLDER, trash_id, *parts)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: str) -> dict[str, Any]:
    try:
        data = json.loads(files.read_file(path))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def trash_chat(ctxid: str, context: Any = None) -> str | None:
    """Move a chat's folder into the trash. Returns the trash id, or None
    when the chat was never saved (an empty, unsaved chat has nothing to
    keep). Call before the context is reset so the latest state is kept."""
    if not _SAFE_ID.match(ctxid or ""):
        return None
    with _lock:
        folder = persist_chat.get_chat_folder_path(ctxid)
        if not files.exists(folder):
            return None
        if context is not None:
            try:
                persist_chat.save_tmp_chat(context)
            except Exception:
                pass  # keep the last saved state
        chat = _read_json(files.get_abs_path(folder, persist_chat.CHAT_FILE_NAME))
        dest = files.move_dir_safe(folder, files.get_abs_path(TRASH_FOLDER, ctxid))
        trash_id = files.basename(dest)
        meta = {
            "id": ctxid,
            "name": chat.get("name") or "",
            "created_at": chat.get("created_at") or "",
            "deleted_at": _now().isoformat(),
        }
        files.write_file(_trash_path(trash_id, TRASH_META_FILE), json.dumps(meta))
    purge_expired()
    return trash_id


def list_trash() -> list[dict[str, Any]]:
    purge_expired()
    entries = []
    with _lock:
        for trash_id in files.list_files(TRASH_FOLDER, "*"):
            if not _SAFE_ID.match(trash_id):
                continue
            meta = _read_json(_trash_path(trash_id, TRASH_META_FILE))
            deleted_at = _parse_time(meta.get("deleted_at"))
            entries.append(
                {
                    "trash_id": trash_id,
                    "id": meta.get("id") or trash_id,
                    "name": meta.get("name") or "",
                    "created_at": meta.get("created_at") or "",
                    "deleted_at": deleted_at.isoformat() if deleted_at else "",
                    "expires_at": (deleted_at + timedelta(days=RETENTION_DAYS)).isoformat()
                    if deleted_at
                    else "",
                }
            )
    entries.sort(key=lambda e: e["deleted_at"], reverse=True)
    return entries


def restore_chat(trash_id: str) -> str:
    """Move a trashed chat back and load it. Returns the restored context
    id (a new one if the original id is taken)."""
    from agent import AgentContext

    with _lock:
        folder = _trash_path(trash_id)
        chat_file = _trash_path(trash_id, persist_chat.CHAT_FILE_NAME)
        if not files.exists(chat_file):
            raise TrashError("This chat is no longer in the trash.")
        data = _read_json(chat_file)
        if not data:
            raise TrashError("The trashed chat file could not be read.")

        ctxid = str(data.get("id") or "")
        id_free = (
            bool(_SAFE_ID.match(ctxid))
            and AgentContext.get(ctxid) is None
            and not files.exists(persist_chat.get_chat_folder_path(ctxid))
        )
        if not id_free:
            data.pop("id", None)  # deserialize assigns a fresh id

        files.delete_file(_trash_path(trash_id, TRASH_META_FILE))
        context = persist_chat._deserialize_context(data)
        files.move_dir(folder, persist_chat.get_chat_folder_path(context.id))
        if not id_free:
            persist_chat.save_tmp_chat(context)  # rewrite chat.json with the new id
        persist_chat.mark_chat_saved(context)
        return context.id


def purge(trash_id: str) -> None:
    with _lock:
        folder = _trash_path(trash_id)
        if not files.exists(folder):
            return
        data = _read_json(_trash_path(trash_id, persist_chat.CHAT_FILE_NAME))
        if data:
            try:
                persist_chat.delete_provider_responses_for_data(data)
            except Exception:
                pass
        files.delete_dir(folder)


def empty_trash() -> int:
    with _lock:
        ids = [t for t in files.list_files(TRASH_FOLDER, "*") if _SAFE_ID.match(t)]
    for trash_id in ids:
        purge(trash_id)
    return len(ids)


def purge_expired() -> int:
    cutoff = _now() - timedelta(days=RETENTION_DAYS)
    expired = []
    with _lock:
        for trash_id in files.list_files(TRASH_FOLDER, "*"):
            if not _SAFE_ID.match(trash_id):
                continue
            deleted_at = _parse_time(_read_json(_trash_path(trash_id, TRASH_META_FILE)).get("deleted_at"))
            if deleted_at and deleted_at < cutoff:
                expired.append(trash_id)
    for trash_id in expired:
        purge(trash_id)
    return len(expired)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
