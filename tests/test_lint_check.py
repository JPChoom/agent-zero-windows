"""Lint check after a Python edit (plugins/_coding_controller/helpers/lint_check.py)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from plugins._coding_controller.helpers import lint_check as lc

RUFF_JSON = json.dumps([
    {"code": "F821", "message": "Undefined name `x`", "location": {"row": 6, "column": 12}},
    {"code": "F811", "message": "Redefinition of unused `f` from line 1", "location": {"row": 9, "column": 5}},
])


def test_parse_reads_ruffs_json():
    assert lc.parse(RUFF_JSON) == [
        {"code": "F821", "message": "Undefined name `x`", "line": 6},
        {"code": "F811", "message": "Redefinition of unused `f` from line 1", "line": 9},
    ]
    assert lc.parse("not json") == [] and lc.parse("") == [] and lc.parse('{"a": 1}') == []


def test_only_problems_the_edit_added_count_even_when_lines_move():
    before = [{"code": "F821", "message": "Undefined name `old`", "line": 3}]
    after = [{"code": "F821", "message": "Undefined name `old`", "line": 10},  # moved down, not new
             {"code": "F821", "message": "Undefined name `new`", "line": 4}]
    assert lc.new_problems(before, after) == [after[1]]
    twice = [{"code": "F821", "message": "Undefined name `old`", "line": n} for n in (3, 8)]
    assert lc.new_problems(before, twice) == [twice[1]]  # a second copy of an old problem is new
    assert lc.new_problems(after, before) == []


def test_the_report_is_short_and_capped():
    assert lc.report("a.py", []) == ""
    problems = [{"code": "F821", "message": f"Undefined name `n{i}`", "line": i} for i in range(1, 9)]
    text = lc.report("a.py", problems)
    assert "added 8 problems" in text and "line 1: F821" in text and "and 3 more" in text and "Fix them" in text
    assert text.count("\n- line") == lc.MAX_REPORTED


def test_no_ruff_means_no_result(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "ruff_path", lambda: "")
    path = tmp_path / "a.py"
    path.write_text("x = y\n", encoding="utf-8")
    assert lc.run(str(path)) is None


@pytest.mark.parametrize("name", ["a.js", "a.txt", "missing.py"])
def test_other_files_and_missing_files_are_not_checked(monkeypatch, tmp_path, name):
    monkeypatch.setattr(lc, "ruff_path", lambda: "ruff")
    if name != "missing.py":
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert lc.run(str(tmp_path / name)) is None


@pytest.mark.parametrize("returncode,expected", [(0, []), (1, "parsed"), (2, None)])
def test_ruffs_exit_codes(monkeypatch, tmp_path, returncode, expected):
    monkeypatch.setattr(lc, "ruff_path", lambda: "ruff")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=returncode, stdout=RUFF_JSON if returncode == 1 else "[]", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    result = lc.run(str(path))
    assert result == (lc.parse(RUFF_JSON) if expected == "parsed" else expected)
    assert "--isolated" in seen["cmd"] and ",".join(lc.RULES) in seen["cmd"]


def test_a_hanging_ruff_says_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "ruff_path", lambda: "ruff")

    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 8)

    monkeypatch.setattr(lc.subprocess, "run", slow)
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    assert lc.run(str(path)) is None


@pytest.mark.skipif(not lc.ruff_path(), reason="ruff is not installed")
def test_real_ruff_finds_run_time_mistakes_but_not_unfinished_code(tmp_path):
    path = tmp_path / "probe.py"
    path.write_text("import os\n\n\ndef f(a):\n    unused = 1\n    return a + missing_name\n", encoding="utf-8")
    codes = {p["code"] for p in lc.run(str(path))}
    assert codes == {"F821"}  # not F401 (unused import) or F841 (unused variable)


# -- the two hooks together --------------------------------------------------------

def _agent(path, action="patch"):
    return SimpleNamespace(loop_data=SimpleNamespace(params_temporary={}, current_tool=SimpleNamespace(args={"path": path, "action": action})))


def _hooks(monkeypatch, results):
    import importlib

    before = importlib.import_module("plugins._coding_controller.extensions.python.tool_execute_before._70_lint_before")
    after = importlib.import_module("plugins._coding_controller.extensions.python.tool_execute_after._72_lint_check")
    for module in (before, after):
        monkeypatch.setattr(module, "get_config", lambda agent: {"lint_check": True})
    monkeypatch.setattr(lc, "ruff_path", lambda: "ruff")
    monkeypatch.setattr(lc, "run", lambda path: results.pop(0))
    return before.LintBeforeEdit, after.LintCheckAfterEdit


def test_the_hooks_report_only_what_the_edit_added(monkeypatch, tmp_path):
    path = str(tmp_path / "a.py")
    old = {"code": "F821", "message": "Undefined name `old`", "line": 2}
    new = {"code": "F821", "message": "Undefined name `typo`", "line": 7}
    Before, After = _hooks(monkeypatch, [[old], [old, new]])
    agent = _agent(path)
    asyncio.run(Before(agent=agent).execute(tool_name="text_editor", tool_args={"path": path, "action": "patch"}))
    response = SimpleNamespace(message="Patched.")
    asyncio.run(After(agent=agent).execute(response=response, tool_name="text_editor"))
    assert "added 1 problem" in response.message and "typo" in response.message and "`old`" not in response.message


def test_the_hooks_stay_quiet_after_a_syntax_error_and_for_reads(monkeypatch, tmp_path):
    path = str(tmp_path / "a.py")
    Before, After = _hooks(monkeypatch, [[], [{"code": "F821", "message": "x", "line": 1}]])
    agent = _agent(path)
    asyncio.run(Before(agent=agent).execute(tool_name="text_editor", tool_args={"path": path, "action": "write"}))
    broken = SimpleNamespace(message="Written.\n\nSyntax check: a.py no longer parses (line 1).")
    asyncio.run(After(agent=agent).execute(response=broken, tool_name="text_editor"))
    assert "Lint check" not in broken.message
    read = _agent(path, action="read")
    response = SimpleNamespace(message="contents")
    asyncio.run(After(agent=read).execute(response=response, tool_name="text_editor"))
    assert response.message == "contents"


def test_the_setting_is_on_by_default(monkeypatch):
    from plugins._coding_controller.helpers import config

    monkeypatch.setattr(config.plugins, "get_plugin_config", lambda *a, **k: {})
    assert config.get_config(None)["lint_check"] is True
    monkeypatch.setattr(config.plugins, "get_plugin_config", lambda *a, **k: {"lint_check": False})
    assert config.get_config(None)["lint_check"] is False
