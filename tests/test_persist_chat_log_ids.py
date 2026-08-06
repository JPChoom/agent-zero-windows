from __future__ import annotations

import json
from types import SimpleNamespace


def test_deserialize_log_preserves_item_id() -> None:
    from helpers.log import Log
    from helpers.persist_chat import _deserialize_log, _serialize_log

    log = Log()
    log.log(type="user", heading="User message", content="hello", id="msg-123")
    log.log(type="assistant", heading="Assistant", content="hi")

    serialized = _serialize_log(log)
    restored = _deserialize_log(serialized)

    assert restored.logs[0].type == "user"
    assert restored.logs[0].id == "msg-123"
    assert restored.logs[1].type == "assistant"
    assert restored.logs[1].id is None


def test_load_tmp_chats_skips_directories_without_chat_json(monkeypatch, capsys) -> None:
    from helpers import persist_chat

    monkeypatch.setattr(persist_chat, "_convert_v080_chats", lambda: None)
    monkeypatch.setattr(
        persist_chat.files,
        "get_abs_path",
        lambda *parts: "/" + "/".join(str(part).strip("/") for part in parts if part),
    )
    monkeypatch.setattr(
        persist_chat.files,
        "list_files",
        lambda folder, pattern="*": ["orphan", "valid"],
    )
    monkeypatch.setattr(
        persist_chat.files,
        "exists",
        lambda path: str(path).endswith("/valid/chat.json"),
    )
    monkeypatch.setattr(
        persist_chat.files,
        "read_file",
        lambda path: json.dumps({"id": "valid"}),
    )
    monkeypatch.setattr(
        persist_chat,
        "_deserialize_context",
        lambda data: SimpleNamespace(id=data["id"], data={}),
    )

    assert persist_chat.load_tmp_chats() == ["valid"]
    assert "Error loading chat" not in capsys.readouterr().out
