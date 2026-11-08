"""A chat save can't leave a damaged file or put older state over newer.

Since v1.5.4 two threads can save one chat: a step's own save and the
background compression's. write_file empties the file and then writes it, so
an older snapshot could land last, and a crash or closed window mid-write left
a damaged chat.json, which the next start skips.
"""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from pathlib import Path

import pytest

from agent import AgentContextType
from helpers import files, persist_chat


class _Context:
    def __init__(self, state="first"):
        self.id = "chat-order"
        self.type = AgentContextType.USER
        self.data = {}
        self.state = state


@pytest.fixture
def chat(tmp_path, monkeypatch):
    path = tmp_path / "chats" / "chat-order" / "chat.json"
    monkeypatch.setattr(persist_chat, "_get_chat_file_path", lambda ctxid: str(path))
    monkeypatch.setattr(persist_chat, "_serialize_context", lambda context: {"state": context.state})
    monkeypatch.setattr(persist_chat, "_save_orders", {})
    return _Context(), path


def _state(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))["state"]


def test_a_save_lands_and_is_marked(chat):
    context, path = chat
    persist_chat.save_tmp_chat(context)
    assert _state(path) == "first" and context.data[persist_chat.SAVED_CHAT_CONTEXT_DATA_KEY]
    assert not Path(str(path) + ".tmp").exists()


def test_the_async_save_uses_the_same_path(chat):
    context, path = chat
    asyncio.run(persist_chat.save_tmp_chat_async(context))
    assert _state(path) == "first"


def test_an_older_snapshot_cannot_replace_a_newer_one(chat):
    context, path = chat
    older = persist_chat._prepare_chat_save(context)
    context.state = "newer"
    newer = persist_chat._prepare_chat_save(context)
    persist_chat._write_chat(context.id, *newer)
    persist_chat._write_chat(context.id, *older)  # the slow writer finishes last
    assert _state(path) == "newer"


def test_many_writers_in_any_order_leave_the_newest_whole(chat):
    context, path = chat
    snapshots = []
    for i in range(40):
        context.state = i
        snapshots.append(persist_chat._prepare_chat_save(context))
    random.Random(5).shuffle(snapshots)
    threads = [threading.Thread(target=persist_chat._write_chat, args=(context.id, *s)) for s in snapshots]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert _state(path) == 39


def test_chats_do_not_hold_each_other_back(chat):
    context, _ = chat
    other = _Context("other")
    other.id = "chat-other"
    assert persist_chat._prepare_chat_save(context)[2] == 1
    assert persist_chat._prepare_chat_save(other)[2] == 1
    assert persist_chat._save_order(context.id) is not persist_chat._save_order(other.id)


def test_a_failed_write_leaves_the_last_good_save(chat, monkeypatch):
    context, path = chat
    persist_chat.save_tmp_chat(context)
    context.state = "half written"

    def crash(fd):
        raise OSError("disk gone")

    monkeypatch.setattr(files.os, "fsync", crash)
    with pytest.raises(OSError):
        persist_chat.save_tmp_chat(context)
    assert _state(path) == "first"


def test_a_briefly_locked_file_is_retried(tmp_path, monkeypatch):
    target = tmp_path / "chat.json"
    target.write_text("old", encoding="utf-8")
    real = files.os.replace
    calls = []

    def locked_twice(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("held by the indexer")
        real(src, dst)

    monkeypatch.setattr(files.os, "replace", locked_twice)
    monkeypatch.setattr(files, "ATOMIC_REPLACE_DELAY_SECONDS", 0)
    files.write_file_atomic(str(target), "new")
    assert target.read_text(encoding="utf-8") == "new" and len(calls) == 3


def test_a_file_that_stays_locked_keeps_its_old_version(tmp_path, monkeypatch):
    target = tmp_path / "chat.json"
    target.write_text("old", encoding="utf-8")

    def locked(src, dst):
        raise PermissionError("held")

    monkeypatch.setattr(files.os, "replace", locked)
    monkeypatch.setattr(files, "ATOMIC_REPLACE_DELAY_SECONDS", 0)
    with pytest.raises(PermissionError):
        files.write_file_atomic(str(target), "new")
    assert target.read_text(encoding="utf-8") == "old"  # never half written
    assert Path(str(target) + ".tmp").read_text(encoding="utf-8") == "new"  # complete copy kept


def test_a_locked_chat_save_is_retried_and_lands(chat, monkeypatch):
    context, path = chat
    persist_chat.save_tmp_chat(context)
    real = files.write_file_atomic
    calls = []

    def locked_once(p, js):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("held by the indexer")
        real(p, js)

    monkeypatch.setattr(files, "write_file_atomic", locked_once)
    monkeypatch.setattr(persist_chat, "SAVE_RETRY_SECONDS", 0.05)
    context.state = "newer"
    persist_chat.save_tmp_chat(context)
    assert _state(path) == "first"  # the old save is still there meanwhile
    deadline = time.time() + 3
    while _state(path) != "newer" and time.time() < deadline:
        time.sleep(0.05)
    assert _state(path) == "newer" and len(calls) == 2


def test_a_retry_never_replaces_a_newer_save(chat, monkeypatch):
    context, path = chat
    older = persist_chat._prepare_chat_save(context)
    context.state = "newer"
    newer = persist_chat._prepare_chat_save(context)
    persist_chat._write_chat(context.id, *newer)
    persist_chat._write_chat(context.id, *older, retry=1)  # a late retry of the older one
    assert _state(path) == "newer"


def test_a_real_open_reader_keeps_the_old_file_until_it_lets_go(tmp_path, monkeypatch):
    target = tmp_path / "chat.json"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(files, "ATOMIC_REPLACE_DELAY_SECONDS", 0)
    with open(target, encoding="utf-8") as reader:
        try:
            files.write_file_atomic(str(target), "new")
            replaced = True  # this filesystem allows replacing an open file
        except PermissionError:
            replaced = False  # Windows: a plain reader blocks the replace
        assert reader.read() == "old"
    assert target.read_text(encoding="utf-8") == ("new" if replaced else "old")
    files.write_file_atomic(str(target), "new")  # the next save, once released
    assert target.read_text(encoding="utf-8") == "new"
    assert not Path(str(target) + ".tmp").exists()
