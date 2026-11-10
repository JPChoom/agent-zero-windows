"""The capability benchmark's tasks score correctly (tests/manual/capability_benchmark.py).

The benchmark needs a real model, so it is run by hand. These tests check its
scoring without one: doing nothing must fail a task (or, for a refusal task,
pass it), a correct end state must pass, and the forbidden action of a
refusal task must fail it. Otherwise the benchmark would measure nothing or
reward the wrong thing.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "manual"))

import capability_benchmark as bench  # noqa: E402

OWN = [t for t in bench.TASKS if t.solve or t.violate]
REFUSALS = {"readonly_profile"}  # doing nothing is the correct outcome


@pytest.fixture(autouse=True)
def _no_grace(monkeypatch):
    monkeypatch.setattr(bench, "STOP_GRACE_SECONDS", 0)


def _run(task):
    return bench.Run(params=task.params() if task.params else {})


def _folder(tmp_path, task):
    folder = tmp_path / "work" / f"bench-{task.id}"
    folder.mkdir(parents=True)
    return folder


@pytest.mark.parametrize("task", OWN, ids=lambda t: t.id)
def test_scoring(task, tmp_path):
    if "git" in task.needs and not shutil.which("git"):
        pytest.skip("git not installed")
    folder = _folder(tmp_path, task)
    task.setup(folder)
    run = _run(task)
    try:
        assert task.check(folder, run) is (task.id in REFUSALS), "doing nothing scored wrong"
        if task.solve:
            task.solve(folder, run)
            assert task.check(folder, run), "a correct end state fails the check"
    finally:
        if task.teardown:
            task.teardown(folder)


@pytest.mark.parametrize("task", [t for t in OWN if t.violate], ids=lambda t: t.id)
def test_the_forbidden_action_fails(task, tmp_path):
    folder = _folder(tmp_path, task)
    task.setup(folder)
    run = _run(task)
    try:
        task.violate(folder, run)
        assert not task.check(folder, run)
    finally:
        if task.teardown:
            task.teardown(folder)


def test_partial_fixes_fail(tmp_path):
    """Changing the tests, or special-casing the visible test, is not a fix."""
    task = next(t for t in bench.TASKS if t.id == "coding_fix_bug")
    folder = _folder(tmp_path, task)
    task.setup(folder)
    (folder / "test_stats.py").write_text(bench.STATS_TEST.replace("2.5", "3"), encoding="utf-8")
    assert not task.check(folder, bench.Run())
    task.setup(folder)
    (folder / "stats.py").write_text(bench.STATS_BUGGY.replace("    ordered = sorted", "    if values == [4, 1, 3, 2]:\n        return 2.5\n    ordered = sorted"), encoding="utf-8")
    assert not task.check(folder, bench.Run())


def test_a_rename_that_misses_a_caller_fails(tmp_path):
    task = next(t for t in bench.TASKS if t.id == "coding_rename")
    folder = _folder(tmp_path, task)
    task.setup(folder)
    task.solve(folder, bench.Run())
    (folder / "report.py").write_text(bench.RENAME_FILES["report.py"], encoding="utf-8")
    assert not task.check(folder, bench.Run())


def test_every_task_is_scored_and_every_row_is_covered():
    ids = [t.id for t in bench.TASKS]
    assert len(ids) == len(set(ids))
    for task in bench.TASKS:
        assert task.category in bench.CATEGORIES
        assert task.solve or task.violate or task.category in ("windows", "permissions"), task.id
    assert {t.category for t in bench.TASKS} == set(bench.CATEGORIES)


def test_outside_changes_respect_allowed_prefixes(tmp_path):
    before = {str(tmp_path / "a.txt"): 1.0}
    after = {str(tmp_path / "a.txt"): 1.0, str(tmp_path / ".worktrees" / "x" / "f.py"): 2.0, str(tmp_path / "b.txt"): 3.0}
    assert bench._outside_changes(before, after, tmp_path, (".worktrees",)) == [str(tmp_path / "b.txt")]


def test_tools_used_reads_the_log():
    class Item:
        def __init__(self, type, kvps):
            self.type, self.kvps = type, kvps

    class Ctx:
        class log:
            logs = [Item("tool", {"_tool_name": "child_agent"}), Item("agent", {}), Item("tool", {"_tool_name": "response"})]

    assert bench.tools_used(Ctx) == ["child_agent", "response"]


def test_recorded_tool_calls_win_over_the_log(monkeypatch):
    class Ctx:
        id = "ctx-1"

        class log:
            logs = []

    monkeypatch.setitem(bench._TOOL_CALLS, "ctx-1", ["child_agent", "code_execution_tool", "response"])
    assert bench.tools_used(Ctx) == ["child_agent", "code_execution_tool", "response"]


def test_the_date_check_accepts_the_agents_timezone(tmp_path, monkeypatch):
    from datetime import date

    task = next(t for t in bench.TASKS if t.id == "memory_preference")
    run = bench.Run(params={"word": "kiwi71"})
    monkeypatch.setattr(bench, "_agent_today", lambda: date(2026, 11, 10))
    (tmp_path / "date.txt").write_text("2026kiwi7111kiwi7110", encoding="utf-8")
    assert task.check(tmp_path, run)
    (tmp_path / "date.txt").write_text("2026-11-10", encoding="utf-8")
    assert not task.check(tmp_path, run)


def test_summary_and_compare():
    results = [bench.Result("coding_fix_bug", "coding", completed=True, seconds=10, used_expected=None),
               bench.Result("coding_worktree", "coding", completed=False, seconds=30, used_expected=False),
               bench.Result("children_parallel", "subagents", completed=True, seconds=20, used_expected=True)]
    summary = bench.summarize(results)
    assert summary["by_category"]["coding"]["completion_rate"] == 0.5
    assert summary["by_category"]["coding"]["used_expected_rate"] == 0.0
    assert summary["by_category"]["subagents"]["used_expected_rate"] == 1.0
    assert summary["per_task"]["coding_worktree"] == {"category": "coding", "runs": 1, "completed": 0}
    report = {"when": "t", "model": "m", "summary": summary}
    assert "coding" in bench.compare(report, report)


def test_selection():
    picked = bench.select(bench.TASKS, {"coding"}, set(), with_apps=False)
    assert picked and all(t.category == "coding" for t in picked)
    assert not any("apps" in t.needs for t in bench.select(bench.TASKS, set(), set(), with_apps=False))


def test_fresh_memory_is_per_run_and_removed(tmp_path, monkeypatch):
    memory = pytest.importorskip("plugins._memory.helpers.memory")
    monkeypatch.setattr(memory, "abs_db_dir", lambda subdir: str(tmp_path / subdir))
    original = memory.get_agent_memory_subdir
    with bench._FreshMemory(True, "memory_preference-abc123") as fresh:
        assert memory.get_agent_memory_subdir(object()) == "benchmark/memory_preference-abc123"
        (tmp_path / fresh.subdir).mkdir(parents=True)
    assert memory.get_agent_memory_subdir is original
    assert not (tmp_path / "benchmark" / "memory_preference-abc123").exists()
    with bench._FreshMemory(False, "x"):
        assert memory.get_agent_memory_subdir is original
