"""The bug class that motivated fixing the *_after bookkeeping extensions.

agent.py's process_tools() calls tool.execute() - the real effect (a file
write, a code run) already happens there - and only afterward runs
tool_execute_after / text_editor_write_after / etc. extensions for
bookkeeping (edit tracking, editor session sync, undo snapshots).
call_extensions_async has no per-extension error handling: before these
were fixed, one of those bookkeeping extensions raising would propagate
straight out of the whole tool-call block in agent.py, past
tool.after_execution(response) and past the `response.break_loop` check -
so the model would see a generic "Critical error, retrying" rather than
learn that its edit had, in fact, already succeeded. Retrying a
non-idempotent action (a write, a commit) on that false premise is the
concrete risk.

These tests reproduce the shape of agent.py's own call site: run the
extension against a config/state that makes its real logic raise, then
confirm the failure is caught and a value the caller can still act on
(None, same as every other best_effort target) comes back rather than an
exception.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins._coding_controller.extensions.python.text_editor_write_after import (
    _15_track_edit as track_write_mod,
)
from plugins._time_travel.extensions.python.text_editor_write_after import (
    _50_snapshot as snapshot_mod,
)


class _Log:
    def __init__(self):
        self.logs = []

    def log(self, **kw):
        self.logs.append(kw)
        return object()


class _Context:
    def __init__(self):
        self.log = _Log()


class _Agent:
    def __init__(self):
        self.context = _Context()
        self.data = {}


@pytest.mark.asyncio
async def test_a_broken_edit_tracker_does_not_lose_the_write(monkeypatch):
    """Simulates: the file write already succeeded (that happened in
    tool.execute(), before this extension runs at all); the completion-gate
    bookkeeping that follows it then breaks. The edit is not undone by
    this - it must not also take down the response telling the model the
    write worked."""

    def boom(agent, path):
        raise RuntimeError("project_detector blew up on a symlink")

    monkeypatch.setattr(track_write_mod.session_state, "mark_dirty_for_path", boom)
    monkeypatch.setattr(
        track_write_mod, "get_config", lambda agent: {"enforce_completion_gate": True}
    )

    agent = _Agent()
    ext = track_write_mod.CodingControllerTrackWrite(agent=agent)  # type: ignore[arg-type]

    # Must not raise - agent.py's process_tools would otherwise abort the
    # whole tool-call block here, discarding the write's own response.
    await ext.execute(data={"path": "C:\\a0\\usr\\workdir\\project\\main.py"})

    assert any(e["type"] == "warning" for e in agent.context.log.logs)


@pytest.mark.asyncio
async def test_a_broken_snapshot_does_not_lose_the_write(monkeypatch):
    """Same shape, the other real example: undo-snapshotting fails after a
    successful write. Losing the ability to undo *this one* edit is a far
    smaller cost than the model believing the edit itself failed."""

    def boom(agent, trigger, metadata):
        raise OSError("disk full while snapshotting")

    monkeypatch.setattr(snapshot_mod, "snapshot_for_agent", boom)

    agent = _Agent()
    ext = snapshot_mod.TimeTravelTextEditorWriteSnapshot(agent=agent)  # type: ignore[arg-type]

    await ext.execute(data={"path": "C:\\a0\\usr\\workdir\\project\\main.py"})

    assert any(e["type"] == "warning" for e in agent.context.log.logs)


@pytest.mark.asyncio
async def test_disabled_gate_still_skips_tracking_without_needing_the_guard(monkeypatch):
    """The guard must not change the ordinary opt-out path: when the
    completion gate is off, mark_dirty_for_path is never even called."""
    calls = []
    monkeypatch.setattr(
        track_write_mod.session_state,
        "mark_dirty_for_path",
        lambda agent, path: calls.append(path),
    )
    monkeypatch.setattr(
        track_write_mod, "get_config", lambda agent: {"enforce_completion_gate": False}
    )

    agent = _Agent()
    ext = track_write_mod.CodingControllerTrackWrite(agent=agent)  # type: ignore[arg-type]
    await ext.execute(data={"path": "C:\\a0\\usr\\workdir\\project\\main.py"})

    assert calls == []
    assert agent.context.log.logs == []
