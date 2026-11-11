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


def test_utility_block_reads_another_config(tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"chat_model": {"provider": "llama_cpp", "name": "big"},
                                "utility_model": {"provider": "lm_studio", "name": "small", "api_base": "http://203.0.113.5:1234/v1"}}),
                    encoding="utf-8")
    assert bench.utility_block(str(path))["name"] == "small"
    path.write_text(json.dumps({"chat_model": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        bench.utility_block(str(path))


def test_the_utility_options_exclude_each_other():
    import asyncio

    with pytest.raises(SystemExit):
        asyncio.run(bench.main(["--utility-as-main", "--utility-from", "x.json", "--list"]))


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


def test_reports_are_written_as_the_run_goes(tmp_path):
    import json

    out = tmp_path / "r.json"
    header = {"when": "t", "model": "m", "planned_runs": 2}
    bench.write_report(out, header, [bench.Result("a", "coding", completed=True)], complete=False)
    partial = json.loads(out.read_text(encoding="utf-8"))
    assert partial["complete"] is False and len(partial["results"]) == 1 and partial["planned_runs"] == 2
    bench.write_report(out, header, [bench.Result("a", "coding"), bench.Result("b", "coding")], complete=True)
    assert json.loads(out.read_text(encoding="utf-8"))["complete"] is True


# -- the hard tier -------------------------------------------------------------------

def _hard(task_id, tmp_path):
    task = next(t for t in bench.TASKS if t.id == task_id)
    folder = _folder(tmp_path, task)
    task.setup(folder)
    return task, folder


def test_the_hard_tier_is_separate_and_named_tasks_still_run():
    standard = bench.select(bench.TASKS, set(), set(), with_apps=False)
    hard = bench.select(bench.TASKS, set(), set(), with_apps=False, tier="hard")
    assert hard and all(t.tier == "hard" for t in hard) and all(t.tier == "standard" for t in standard)
    assert len(bench.select(bench.TASKS, set(), set(), False, "all")) == len(standard) + len(hard)
    assert [t.id for t in bench.select(bench.TASKS, set(), {"hard_refactor"}, False)] == ["hard_refactor"]
    assert len(hard) >= 6 and {t.category for t in hard} >= {"coding", "subagents", "windows"}


def test_a_refactor_that_misses_the_lazy_import_fails(tmp_path):
    task, folder = _hard("hard_refactor", tmp_path)
    task.solve(folder, bench.Run())
    assert task.check(folder, bench.Run())
    (folder / "pkg" / "extra.py").write_text(bench.REFACTOR_FILES["pkg/extra.py"], encoding="utf-8")  # still imports utils inside late()
    assert not task.check(folder, bench.Run())


def test_a_refactor_that_keeps_utils_fails(tmp_path):
    task, folder = _hard("hard_refactor", tmp_path)
    task.solve(folder, bench.Run())
    (folder / "utils.py").write_text(bench.UTILS_PY, encoding="utf-8")
    assert not task.check(folder, bench.Run())


def test_fixing_only_the_visible_bug_fails(tmp_path):
    task, folder = _hard("hard_two_bugs", tmp_path)
    (folder / "inventory.py").write_text(bench.INVENTORY_BUGGY.replace("), 1)", "), 2)"), encoding="utf-8")
    assert bench._unittest_passes(folder) and not task.check(folder, bench.Run())


def test_changing_the_tests_or_readme_fails(tmp_path):
    task, folder = _hard("hard_two_bugs", tmp_path)
    task.solve(folder, bench.Run())
    (folder / "test_inventory.py").write_text(bench.INVENTORY_TEST + "\n# edited\n", encoding="utf-8")
    assert not task.check(folder, bench.Run())


def test_the_build_shortcut_of_editing_build_py_fails(tmp_path):
    task, folder = _hard("hard_dead_end", tmp_path)
    (folder / "build.py").write_text(
        'from pathlib import Path\nPath("dist").mkdir(exist_ok=True)\nPath("dist/out.txt").write_text("demo v1.4.2\n")\nprint("built")\n',
        encoding="utf-8")
    assert not task.check(folder, bench.Run())  # the output is right but build.py was rewritten


def test_a_review_that_finds_only_one_planted_bug_fails(tmp_path):
    task, folder = _hard("hard_review_planted", tmp_path)
    for one in ("Bug: SQL injection, use a parameterized query.", "Bug: range(1, ...) is an off-by-one that skips the first row."):
        assert not task.check(folder, bench.Run(responses=[one]))
    assert not task.check(folder, bench.Run(responses=["Looks fine to me."]))
    both = bench.Run()
    task.solve(folder, both)
    assert task.check(folder, both)
    (folder / "change.diff").write_text("changed", encoding="utf-8")  # a review that edits the file
    assert not task.check(folder, both)


def test_wrong_children_totals_fail(tmp_path):
    import json

    task, folder = _hard("hard_children_work", tmp_path)
    task.solve(folder, bench.Run())
    assert task.check(folder, bench.Run())
    good = json.loads((folder / "totals.json").read_text(encoding="utf-8"))
    (folder / "totals.json").write_text(json.dumps({**good, "total": good["total"] + 1}), encoding="utf-8")
    assert not task.check(folder, bench.Run())
    (folder / "totals.json").write_text("not json", encoding="utf-8")
    assert not task.check(folder, bench.Run())


def test_the_codeword_must_come_from_the_child():
    task = next(t for t in bench.TASKS if t.id == "hard_resume_child")
    assert "{word}" in task.prompts[0] and task.expect_tools == ("child_agent",)


def test_ledger_traps(tmp_path):
    task, folder = _hard("hard_messy_ledger", tmp_path)
    for total, skipped in (("2510.50", "4,6"), ("1255.25", "4,6"), ("1255.25", "6,8"), ("1267.75", "4,6,8"), ("1255.25", "4,6,8,9")):
        (folder / "total.txt").write_text(total, encoding="utf-8")
        (folder / "skipped.txt").write_text(skipped, encoding="utf-8")
        assert not task.check(folder, bench.Run()), (total, skipped)
    (folder / "total.txt").write_text("1255.25", encoding="utf-8")
    (folder / "skipped.txt").write_text("4, 6, 8", encoding="utf-8")
    assert task.check(folder, bench.Run())


def test_the_ledger_answer_is_what_the_file_says():
    """Independent of the task's own solution: only dated rows count (not the blank line, the n/a row or TOTAL)."""
    import csv
    import io
    import re

    lines = bench.LEDGER.lstrip("﻿").split("\n")[:-1]
    total, skipped = 0.0, []
    for number, line in enumerate(lines[1:], start=2):
        row = next(csv.reader(io.StringIO(line)), [])
        try:
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", row[0]):
                raise ValueError("not a dated row")
            total += float(row[2].replace("$", "").replace(",", ""))
        except (IndexError, ValueError):
            skipped.append(number)
    assert f"{total:.2f}" == "1255.25" and skipped == [4, 6, 8]
