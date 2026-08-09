"""End-to-end integration test for the completion gate's checkpoint/
rollback wiring (Phase C): runs the real CodingCompletionGate.execute()
across three simulated turns against a real git repo, with the quality
gate itself faked (so the test controls exactly which fingerprint each
turn produces) but file checkpoint/restore going through the real
checkpoint.py + git on disk - the actual thing this phase is meant to
prove works, not just that the pure helper functions are individually
correct.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers.errors import RepairableException
from plugins._coding_controller.extensions.python.tool_execute_after import _80_completion_gate as gate_ext
from plugins._coding_controller.helpers import gate_controller, session_state


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)


class _FakeAgent:
    def __init__(self):
        self.data = {}
        self.history = SimpleNamespace(output_text=lambda: "")


def _fake_result(passed: bool, codes: list[str]) -> dict:
    return {
        "passed": passed,
        "skipped": False,
        "stages": [
            {
                "name": "test",
                "passed": passed,
                "exit_code": 0 if passed else 1,
                "timed_out": False,
                "diagnostics": [
                    {"file": "a.ps1", "code": code, "message": "boom", "severity": "error", "line": 1, "column": 1}
                    for code in codes
                ],
                "stderr_tail": "",
                "stdout_tail": "",
            }
        ],
    }


@pytest.mark.asyncio
async def test_worsening_repair_attempt_is_rolled_back_on_disk(tmp_path: Path, monkeypatch):
    target = tmp_path / "a.ps1"
    target.write_text("safe baseline content\n", encoding="utf-8", newline="")
    _init_repo(tmp_path)
    root = str(tmp_path)

    cfg = {
        "enforce_completion_gate": True,
        "max_repair_attempts": 2,
        "enable_independent_review": False,
        "enable_diagnostician": False,
    }
    monkeypatch.setattr(gate_ext, "get_config", lambda agent: cfg)

    # Turn-by-turn scripted gate results: (turn 1) first failure -> baseline;
    # (turn 2) a new failure beyond baseline -> repair requested, checkpoint
    # saved; (turn 3) worse than the checkpoint -> rollback, gate re-run
    # against the restored content -> back to the turn-2 fingerprint ->
    # another repair requested (attempt 2/2, not yet given up).
    results = iter([
        _fake_result(False, ["CS0001"]),          # turn 1: becomes baseline
        _fake_result(False, ["CS0001", "CS0002"]),  # turn 2: new finding CS0002
        _fake_result(False, ["CS0001", "CS0002", "CS0003"]),  # turn 3: worse (CS0003 added)
        _fake_result(False, ["CS0001", "CS0002"]),  # turn 3 recheck after rollback: back to turn-2 state
    ])

    async def _fake_run_gate_for_root(root_, kind_, cfg_):
        return next(results)

    monkeypatch.setattr(gate_controller, "run_gate_for_root", _fake_run_gate_for_root)

    agent = _FakeAgent()

    # --- turn 1: first failure becomes baseline, no exception ---
    session_state.mark_dirty_for_path(agent, str(target))
    response1 = SimpleNamespace(message="done")
    gate1 = gate_ext.CodingCompletionGate(agent)
    await gate1.execute(response=response1, tool_name="response")
    assert session_state.get_baseline(agent, root) is not None

    # --- turn 2: new finding beyond baseline -> repair requested, checkpoint saved ---
    target.write_text("attempt 1 content\n", encoding="utf-8", newline="")
    session_state.mark_dirty_for_path(agent, str(target))
    response2 = SimpleNamespace(message="done")
    gate2 = gate_ext.CodingCompletionGate(agent)
    with pytest.raises(RepairableException):
        await gate2.execute(response=response2, tool_name="response")

    checkpoint_after_turn2 = session_state.get_checkpoint(agent, root)
    assert checkpoint_after_turn2 is not None
    assert checkpoint_after_turn2.file_snapshots.get("a.ps1") == b"attempt 1 content\n"

    # --- turn 3: a worse attempt -> must be rolled back to turn 2's content ---
    target.write_text("attempt 2 content - broke more things\n", encoding="utf-8", newline="")
    session_state.mark_dirty_for_path(agent, str(target))
    response3 = SimpleNamespace(message="done")
    gate3 = gate_ext.CodingCompletionGate(agent)
    with pytest.raises(RepairableException) as exc_info:
        await gate3.execute(response=response3, tool_name="response")

    # The actual proof: the file on disk was reverted, not left as the
    # worse attempt-2 content.
    assert target.read_text(encoding="utf-8") == "attempt 1 content\n"
    assert "rolled back" in response3.message
    assert session_state.get_repair_attempts(agent, root) == 2
    assert "repair attempt 2/2" in str(exc_info.value)
