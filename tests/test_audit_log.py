"""Tests for the core hash-chained audit log (helpers/audit_log.py,
Phase D of the hand-off roadmap) and its tool_execute_before/after
capture+write extension pair.
"""

import json

import pytest

from helpers import audit_log
from extensions.python.tool_execute_before import _95_audit_log_capture
from extensions.python.tool_execute_after import _95_audit_log


@pytest.fixture(autouse=True)
def _redirect_audit_log(tmp_path, monkeypatch):
    log_path = tmp_path / "audit_log.jsonl"
    monkeypatch.setattr(audit_log, "get_audit_log_path", lambda: str(log_path))
    return log_path


class _FakeContext:
    id = "ctx-123"


class _FakeConfig:
    profile = "agent0"


class _FakeAgent:
    def __init__(self):
        self.data = {}
        self.context = _FakeContext()
        self.config = _FakeConfig()


class _FakeResponse:
    def __init__(self, message="ok"):
        self.message = message
        self.break_loop = False


# ------------------------------------------------------------------
# append_record / verify_chain
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_record_writes_one_json_line(_redirect_audit_log):
    entry = await audit_log.append_record({"tool": "text_editor"})

    lines = _redirect_audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["tool"] == "text_editor"
    assert stored["prev_hash"] is None
    assert stored["hash"] == entry["hash"]


@pytest.mark.asyncio
async def test_append_record_chains_hashes(_redirect_audit_log):
    first = await audit_log.append_record({"tool": "a"})
    second = await audit_log.append_record({"tool": "b"})

    assert second["prev_hash"] == first["hash"]
    assert second["hash"] != first["hash"]


@pytest.mark.asyncio
async def test_append_record_never_raises_on_unwritable_path(monkeypatch):
    monkeypatch.setattr(audit_log, "get_audit_log_path", lambda: "Z:\\nonexistent\\path\\audit.jsonl")

    result = await audit_log.append_record({"tool": "a"})  # must not raise

    assert result == {}


def test_verify_chain_true_for_empty_or_missing_log(_redirect_audit_log):
    ok, reason = audit_log.verify_chain(str(_redirect_audit_log))

    assert ok is True
    assert reason == ""


@pytest.mark.asyncio
async def test_verify_chain_true_for_untampered_log(_redirect_audit_log):
    await audit_log.append_record({"tool": "a"})
    await audit_log.append_record({"tool": "b"})
    await audit_log.append_record({"tool": "c"})

    ok, reason = audit_log.verify_chain(str(_redirect_audit_log))

    assert ok is True
    assert reason == ""


@pytest.mark.asyncio
async def test_verify_chain_detects_edited_line(_redirect_audit_log):
    await audit_log.append_record({"tool": "a"})
    await audit_log.append_record({"tool": "b"})

    lines = _redirect_audit_log.read_text(encoding="utf-8").strip().splitlines()
    tampered = json.loads(lines[0])
    tampered["tool"] = "tampered-value"  # content changed, hash not recomputed
    lines[0] = json.dumps(tampered)
    _redirect_audit_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, reason = audit_log.verify_chain(str(_redirect_audit_log))

    assert ok is False
    assert "hash does not match" in reason


@pytest.mark.asyncio
async def test_verify_chain_detects_deleted_line(_redirect_audit_log):
    await audit_log.append_record({"tool": "a"})
    await audit_log.append_record({"tool": "b"})
    await audit_log.append_record({"tool": "c"})

    lines = _redirect_audit_log.read_text(encoding="utf-8").strip().splitlines()
    del lines[1]  # remove the middle record
    _redirect_audit_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, reason = audit_log.verify_chain(str(_redirect_audit_log))

    assert ok is False
    assert "prev_hash mismatch" in reason


def test_verify_chain_detects_invalid_json_line(_redirect_audit_log):
    _redirect_audit_log.write_text("not json at all\n", encoding="utf-8")

    ok, reason = audit_log.verify_chain(str(_redirect_audit_log))

    assert ok is False
    assert "not valid JSON" in reason


# ------------------------------------------------------------------
# capture + write extension pair
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_editor_write_is_logged(_redirect_audit_log):
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    await before.execute(tool_args={"action": "write", "path": "foo.py"}, tool_name="text_editor")

    after = _95_audit_log.AuditLog(agent)
    await after.execute(response=_FakeResponse(), tool_name="text_editor")

    lines = _redirect_audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "text_editor"
    assert entry["files_changed"] == ["foo.py"]
    assert entry["task_id"] == "ctx-123"
    assert entry["agent_role"] == "agent0"


@pytest.mark.asyncio
async def test_text_editor_read_is_not_logged(_redirect_audit_log):
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    await before.execute(tool_args={"action": "read", "path": "foo.py"}, tool_name="text_editor")

    after = _95_audit_log.AuditLog(agent)
    await after.execute(response=_FakeResponse(), tool_name="text_editor")

    assert not _redirect_audit_log.exists() or _redirect_audit_log.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_unrelated_tool_is_not_logged(_redirect_audit_log):
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    await before.execute(tool_args={"query": "x"}, tool_name="search_engine")

    after = _95_audit_log.AuditLog(agent)
    await after.execute(response=_FakeResponse(), tool_name="search_engine")

    assert not _redirect_audit_log.exists() or _redirect_audit_log.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_code_execution_tool_is_logged_with_program_and_cwd(_redirect_audit_log):
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    await before.execute(
        tool_args={"runtime": "terminal", "code": "echo hi", "cwd": "C:\\proj"},
        tool_name="code_execution_tool",
    )

    after = _95_audit_log.AuditLog(agent)
    await after.execute(response=_FakeResponse(), tool_name="code_execution_tool")

    entry = json.loads(_redirect_audit_log.read_text(encoding="utf-8").strip())
    assert entry["program"] == "terminal"
    assert entry["arguments"]["code"] == "echo hi"
    assert entry["working_directory"] == "C:\\proj"


@pytest.mark.asyncio
async def test_call_subordinate_is_logged(_redirect_audit_log):
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    await before.execute(tool_args={"profile": "coding-implementer", "message": "do x"}, tool_name="call_subordinate")

    after = _95_audit_log.AuditLog(agent)
    await after.execute(response=_FakeResponse(), tool_name="call_subordinate")

    entry = json.loads(_redirect_audit_log.read_text(encoding="utf-8").strip())
    assert entry["tool"] == "call_subordinate"
    assert entry["arguments"]["profile"] == "coding-implementer"


@pytest.mark.asyncio
async def test_capture_stack_stays_balanced_across_multiple_calls(_redirect_audit_log):
    """Simulates a normal serial tool-call sequence (before1, after1,
    before2, after2, ...) - the stack must not grow unbounded or leak
    entries across calls."""
    agent = _FakeAgent()
    before = _95_audit_log_capture.AuditLogCapture(agent)
    after = _95_audit_log.AuditLog(agent)

    for i in range(5):
        await before.execute(tool_args={"action": "write", "path": f"f{i}.py"}, tool_name="text_editor")
        await after.execute(response=_FakeResponse(), tool_name="text_editor")

    assert agent.data["_audit_log_pending"] == []
    lines = _redirect_audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5


@pytest.mark.asyncio
async def test_after_hook_without_matching_before_does_not_raise(_redirect_audit_log):
    agent = _FakeAgent()
    after = _95_audit_log.AuditLog(agent)

    await after.execute(response=_FakeResponse(), tool_name="text_editor")  # must not raise

    assert not _redirect_audit_log.exists() or _redirect_audit_log.read_text(encoding="utf-8") == ""


# ------------------------------------------------------------------
# Cross-event-loop writers
# ------------------------------------------------------------------

def test_append_record_works_from_a_separate_event_loop(tmp_path, monkeypatch):
    """Writers do not all share one event loop: API handlers run on a
    different loop from the agent. An asyncio.Lock created at import time
    raised "bound to a different event loop" for any caller outside it,
    which made every audited action from the web UI a 500.
    """
    import asyncio

    from helpers import audit_log

    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log, "get_audit_log_path", lambda: str(path))

    # Two records written from two independently created loops, as the agent
    # and an API request would.
    for index in range(2):
        loop = asyncio.new_event_loop()
        try:
            entry = loop.run_until_complete(
                audit_log.append_record({"tool": "t", "n": index})
            )
        finally:
            loop.close()
        assert entry, "append_record returned nothing"

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    ok, reason = audit_log.verify_chain(str(path))
    assert ok, reason


def test_concurrent_threads_do_not_corrupt_the_chain(tmp_path, monkeypatch):
    """The lock must also hold across OS threads, since Flask serves
    requests from a thread pool."""
    import asyncio
    import threading

    from helpers import audit_log

    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log, "get_audit_log_path", lambda: str(path))

    def writer(n):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(audit_log.append_record({"tool": "t", "n": n}))
        finally:
            loop.close()

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 8
    ok, reason = audit_log.verify_chain(str(path))
    assert ok, reason
