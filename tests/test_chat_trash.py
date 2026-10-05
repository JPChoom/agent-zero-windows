"""Tests for helpers/chat_trash.py and the trash path of api/chat_remove.py.

Deleted chats must be restorable: the folder moves to usr/chats/.trash
instead of being erased, restore brings the full chat back (under a new id
if the old one was taken meanwhile), purge/expiry erase it for good, and
provider-stored responses are only deleted on purge.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

import pytest

from agent import AgentContext
from helpers import chat_trash, files, persist_chat
from initialize import initialize_agent


@pytest.fixture
def chats_dir(tmp_path, monkeypatch):
    root = tmp_path / "chats"
    root.mkdir()
    monkeypatch.setattr(persist_chat, "CHATS_FOLDER", str(root))
    monkeypatch.setattr(chat_trash, "TRASH_FOLDER", str(root / ".trash"))
    purged_responses: list = []
    monkeypatch.setattr(persist_chat, "delete_provider_responses_for_data", purged_responses.append)
    return SimpleNamespace(root=root, purged_responses=purged_responses)


def _saved_context(name="Greeting"):
    ctx = AgentContext(config=initialize_agent(), name=name, set_current=False)
    persist_chat.save_tmp_chat(ctx)
    return ctx


def _cleanup(*ids):
    for ctxid in ids:
        AgentContext.remove(ctxid)


def test_trash_moves_folder_and_lists_it(chats_dir):
    ctx = _saved_context()
    try:
        trash_id = chat_trash.trash_chat(ctx.id, ctx)
        assert trash_id == ctx.id
        assert not (chats_dir.root / ctx.id).exists()
        assert (chats_dir.root / ".trash" / ctx.id / "chat.json").exists()

        items = chat_trash.list_trash()
        assert [i["name"] for i in items] == ["Greeting"]
        assert items[0]["expires_at"]
        assert chats_dir.purged_responses == []  # kept until purge
    finally:
        _cleanup(ctx.id)


def test_unsaved_chat_is_not_trashed(chats_dir):
    assert chat_trash.trash_chat("neverSaved1") is None
    assert chat_trash.list_trash() == []


def test_restore_brings_chat_back_with_same_id(chats_dir):
    ctx = _saved_context("Restore me")
    original_id = ctx.id
    trash_id = chat_trash.trash_chat(ctx.id, ctx)
    AgentContext.remove(original_id)
    try:
        restored_id = chat_trash.restore_chat(trash_id)
        assert restored_id == original_id
        restored = AgentContext.get(restored_id)
        assert restored is not None and restored.name == "Restore me"
        assert (chats_dir.root / original_id / "chat.json").exists()
        assert not (chats_dir.root / ".trash" / trash_id).exists()
        assert chat_trash.list_trash() == []
    finally:
        _cleanup(original_id)


def test_restore_uses_new_id_when_original_is_taken(chats_dir):
    ctx = _saved_context("Twin")
    trash_id = chat_trash.trash_chat(ctx.id, ctx)
    # ctx stays registered in memory, so its id is taken
    try:
        restored_id = chat_trash.restore_chat(trash_id)
        assert restored_id != ctx.id
        data = json.loads((chats_dir.root / restored_id / "chat.json").read_text(encoding="utf-8"))
        assert data["id"] == restored_id
    finally:
        _cleanup(ctx.id, restored_id)


def test_purge_and_empty_erase_and_delete_provider_responses(chats_dir):
    a, b = _saved_context("A"), _saved_context("B")
    try:
        ta = chat_trash.trash_chat(a.id, a)
        chat_trash.trash_chat(b.id, b)
        chat_trash.purge(ta)
        assert not (chats_dir.root / ".trash" / ta).exists()
        assert len(chats_dir.purged_responses) == 1
        assert chat_trash.empty_trash() == 1
        assert chat_trash.list_trash() == []
    finally:
        _cleanup(a.id, b.id)


def test_entries_past_retention_are_purged(chats_dir):
    ctx = _saved_context("Old")
    try:
        trash_id = chat_trash.trash_chat(ctx.id, ctx)
        meta_path = chats_dir.root / ".trash" / trash_id / chat_trash.TRASH_META_FILE
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["deleted_at"] = (
            datetime.now(timezone.utc) - timedelta(days=chat_trash.RETENTION_DAYS + 1)
        ).isoformat()
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        assert chat_trash.list_trash() == []
        assert not (chats_dir.root / ".trash" / trash_id).exists()
    finally:
        _cleanup(ctx.id)


def test_trash_ids_cannot_escape_the_trash_folder(chats_dir):
    for bad in ("../x", "..", "a/b", "a\\b", ""):
        with pytest.raises(chat_trash.TrashError):
            chat_trash.restore_chat(bad)
        with pytest.raises(chat_trash.TrashError):
            chat_trash.purge(bad)


def test_startup_loader_ignores_the_trash_folder(chats_dir):
    ctx = _saved_context("Trashed")
    try:
        chat_trash.trash_chat(ctx.id, ctx)
        assert persist_chat.saved_chat_ids() == set()
        assert files.exists(str(chats_dir.root / ".trash"))
    finally:
        _cleanup(ctx.id)
