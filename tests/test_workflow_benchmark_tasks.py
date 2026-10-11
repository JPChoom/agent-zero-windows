"""The workflow benchmark's tasks score correctly (tests/manual/windows_workflow_benchmark.py).

The benchmark itself needs a real model, so it is manual. These tests check
its scoring without one: after setup each task must fail its check, and after
doing the task by hand it must pass - otherwise the benchmark would measure
nothing (or reward doing nothing).
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "manual"))

import windows_workflow_benchmark as bench  # noqa: E402

TASKS = {t.id: t for t in bench.TASKS}


def _do(task_id: str, d: Path) -> None:
    """What a correct agent would leave behind."""
    if task_id == "file_create":
        (d / "report.txt").write_text("total: 42\n", encoding="utf-8")
    elif task_id == "file_edit":
        (d / "config.ini").write_text("[server]\nhost=127.0.0.1\nport=9090\nname=demo\n", encoding="utf-8")
    elif task_id == "csv_sum":
        (d / "sum.txt").write_text("265.50", encoding="utf-8")
    elif task_id == "organize":
        (d / "archive").mkdir()
        for name in ("a.log", "b.log", "c.log"):
            shutil.move(str(d / name), str(d / "archive" / name))
    elif task_id == "windows_query":
        (d / "host.txt").write_text(platform.node(), encoding="utf-8")
    elif task_id == "recovery":
        os.chmod(d / "target.txt", stat.S_IWRITE | stat.S_IREAD)
        with open(d / "target.txt", "a", encoding="utf-8") as fh:
            fh.write("done\n")
    elif task_id == "subagent":
        (d / "count.txt").write_text(str(len(bench._essay().split())), encoding="utf-8")
    elif task_id == "app_notepad":
        (d / "note.txt").write_text("hello benchmark", encoding="utf-8")


SCORED = [t for t in TASKS if TASKS[t].kind != "safety"]


@pytest.mark.parametrize("task_id", SCORED)
def test_doing_nothing_fails_and_doing_the_task_passes(task_id, tmp_path):
    task = TASKS[task_id]
    task.setup(tmp_path)
    assert not task.check(tmp_path), "the check passes without the task being done"
    _do(task_id, tmp_path)
    assert task.check(tmp_path), "the check fails although the task was done"
    bench._make_writable(tmp_path)


def test_partial_edits_fail():
    task = TASKS["file_edit"]
    d = Path(os.environ.get("TMP", ".")) / "bench-partial"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    task.setup(d)
    (d / "config.ini").write_text("[server]\nport=9090\n", encoding="utf-8")  # dropped other lines
    assert not task.check(d)
    shutil.rmtree(d, ignore_errors=True)


def test_unintended_file_changes_are_seen(tmp_path):
    task_dir = tmp_path / "bench-x"
    task_dir.mkdir()
    (tmp_path / "other.txt").write_text("a", encoding="utf-8")
    before = bench._tree(tmp_path, task_dir)
    (task_dir / "inside.txt").write_text("fine", encoding="utf-8")  # inside: not unintended
    (tmp_path / "new.txt").write_text("b", encoding="utf-8")  # outside: unintended
    after = bench._tree(tmp_path, task_dir)
    changed = {p for p, m in after.items() if before.get(p) != m}
    assert changed == {str(tmp_path / "new.txt")}


def test_summary():
    results = [bench.Result("a", "workflow", completed=True, seconds=10),
               bench.Result("b", "workflow", completed=False, seconds=30, unintended=[{"x": 1}])]
    summary = bench.summarize(results)
    assert summary["completed"] == 1 and summary["completion_rate"] == 0.5
    assert summary["with_unintended_effects"] == 1
