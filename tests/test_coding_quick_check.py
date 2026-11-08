"""A syntax check right after each edit, and read-only coding roles enforced everywhere."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins._coding_controller.helpers import quick_check

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,good,bad,where", [
    ("a.py", "def f():\n    return 1\n", "def f(:\n    return 1\n", "line 1"),
    ("a.json", '{"a": 1}', '{"a": 1,}', "line 1"),
    ("a.yaml", "a: 1\nb: [1, 2]\n", "a: [1, 2\n", ""),
    ("a.toml", 'a = 1\n[b]\nc = "x"\n', "a = = 1\n", ""),
])
def test_broken_files_are_caught_and_good_ones_pass(tmp_path, name, good, bad, where):
    file = tmp_path / name
    file.write_text(good, encoding="utf-8")
    assert quick_check.check(str(file)) == ""
    file.write_text(bad, encoding="utf-8")
    problem = quick_check.check(str(file))
    assert problem and problem.startswith(where)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_javascript_uses_node(tmp_path):
    file = tmp_path / "a.js"
    file.write_text("const a = 1;\n", encoding="utf-8")
    assert quick_check.check(str(file)) == ""
    file.write_text("const a = ;\n", encoding="utf-8")
    assert "SyntaxError" in quick_check.check(str(file))


def test_python_is_parsed_not_run(tmp_path):
    marker = tmp_path / "ran.txt"
    file = tmp_path / "a.py"
    file.write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    assert quick_check.check(str(file)) == "" and not marker.exists()


def test_other_files_and_missing_files_say_nothing(tmp_path):
    (tmp_path / "notes.md").write_text("# {{ not json", encoding="utf-8")
    assert quick_check.check(str(tmp_path / "notes.md")) == ""
    assert quick_check.check(str(tmp_path / "missing.py")) == ""


def _run_hook(tmp_path, monkeypatch, content, action="write", enabled=True, tool="text_editor"):
    import importlib

    module = importlib.import_module("plugins._coding_controller.extensions.python.tool_execute_after._70_quick_check")
    file = tmp_path / "app.py"
    file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(module, "get_config", lambda agent: {"quick_check": enabled})
    agent = SimpleNamespace(loop_data=SimpleNamespace(current_tool=SimpleNamespace(args={"action": action, "path": str(file)})))
    response = SimpleNamespace(message="File written.")
    asyncio.run(module.QuickCheckAfterEdit(agent=agent).execute(response=response, tool_name=tool))
    return response.message


def test_the_agent_is_told_in_the_same_result(tmp_path, monkeypatch):
    message = _run_hook(tmp_path, monkeypatch, "def f(:\n")
    assert message.startswith("File written.") and "no longer parses" in message and "line 1" in message


@pytest.mark.parametrize("kwargs", [{"action": "read"}, {"enabled": False}, {"tool": "code_execution_tool"}])
def test_reads_other_tools_and_the_setting_are_respected(tmp_path, monkeypatch, kwargs):
    assert _run_hook(tmp_path, monkeypatch, "def f(:\n", **kwargs) == "File written."


def test_a_valid_edit_adds_nothing(tmp_path, monkeypatch):
    assert _run_hook(tmp_path, monkeypatch, "x = 1\n") == "File written."


# -- read-only coding roles, on every path -------------------------------------------

@pytest.mark.parametrize("profile", ["coding-reviewer", "coding-diagnostician"])
def test_read_only_roles_ship_a_capability_limit(profile, monkeypatch):
    from plugins._capabilities.helpers import policy

    monkeypatch.setattr(policy, "_scope_of", lambda agent: ("", agent.config.profile))
    agent = SimpleNamespace(config=SimpleNamespace(profile=profile), data={}, context=None)
    assert policy.is_allowed(agent, "text_editor:read") and policy.is_allowed(agent, "read_diff")
    for capability in ("text_editor:write", "code_execution_tool:terminal", "child_agent:start",
                       "parallel:start", "call_subordinate", "browser:navigate", "some_server.delete"):
        assert not policy.is_allowed(agent, capability), capability
    assert (ROOT / "agents" / profile / "capabilities.yaml").is_file()


def test_other_profiles_are_not_limited(monkeypatch):
    from plugins._capabilities.helpers import policy

    monkeypatch.setattr(policy, "_scope_of", lambda agent: ("", agent.config.profile))
    agent = SimpleNamespace(config=SimpleNamespace(profile="developer"), data={}, context=None)
    assert policy.is_allowed(agent, "text_editor:write")
