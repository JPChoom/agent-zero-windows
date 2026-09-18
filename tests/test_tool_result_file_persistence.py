import os
from types import SimpleNamespace

from agent import AgentContextType
from extensions.python.hist_add_tool_result._90_save_tool_call_file import SaveToolCallFile


def test_tool_result_file_persistence_does_not_list_the_directory(tmp_path, monkeypatch) -> None:
    """The regression: this used to call os.listdir(msgs_folder) just to
    number the next file, an O(n) scan on every large tool result that
    turns into O(n^2) work over a chat's lifetime. A unique filename
    needs no scan at all."""
    target = tmp_path / "messages"
    agent = SimpleNamespace(
        context=SimpleNamespace(id="ctx-1", type=AgentContextType.USER)
    )

    monkeypatch.setattr(
        "extensions.python.hist_add_tool_result._90_save_tool_call_file.persist_chat.get_chat_msg_files_folder",
        lambda _ctxid: str(target),
    )

    original_listdir = os.listdir
    calls = []

    def spying_listdir(path):
        calls.append(path)
        return original_listdir(path)

    monkeypatch.setattr(
        "extensions.python.hist_add_tool_result._90_save_tool_call_file.os.listdir",
        spying_listdir,
    )

    data = {"tool_result": "x" * 501}
    SaveToolCallFile(agent=agent).execute(data=data)

    assert calls == [], "the directory must not be scanned to pick a filename"
    assert "file" in data
    assert os.path.exists(data["file"])


def test_tool_result_file_persistence_gives_each_call_a_distinct_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "messages"
    agent = SimpleNamespace(
        context=SimpleNamespace(id="ctx-2", type=AgentContextType.USER)
    )
    ext = SaveToolCallFile(agent=agent)

    monkeypatch.setattr(
        "extensions.python.hist_add_tool_result._90_save_tool_call_file.persist_chat.get_chat_msg_files_folder",
        lambda _ctxid: str(target),
    )

    saved_paths = set()
    for i in range(20):
        data = {"tool_result": f"result-{i}-" + "x" * 501}
        ext.execute(data=data)
        saved_paths.add(data["file"])

    assert len(saved_paths) == 20, "each save must get its own file, no collisions"
    for path in saved_paths:
        assert os.path.exists(path)


def test_tool_result_file_persistence_skips_background_context(tmp_path, monkeypatch) -> None:
    target = tmp_path / "messages"
    agent = SimpleNamespace(
        context=SimpleNamespace(id="background-worker", type=AgentContextType.BACKGROUND)
    )
    data = {"tool_result": "x" * 501}

    monkeypatch.setattr(
        "extensions.python.hist_add_tool_result._90_save_tool_call_file.persist_chat.get_chat_msg_files_folder",
        lambda _ctxid: str(target),
    )

    SaveToolCallFile(agent=agent).execute(data=data)

    assert "file" not in data
    assert not target.exists()
