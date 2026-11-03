"""B7: building the system prompt every turn without redoing the slow parts.

- A missing file fails at once instead of sleeping through the lock retry
  (it cost 100 ms on every turn: an agent folder without agent.json).
- get_paths reuses its result for a couple of seconds (every read_prompt
  calls it; ~7 ms each), and a plugin change drops that copy at once.
- The tool list reads its ~30 files with the prompt folders looked up once,
  with the same result as agent.read_prompt.
"""

from __future__ import annotations

import time

import pytest

from helpers import files, plugins, subagents


def test_a_missing_file_fails_at_once(tmp_path):
    started = time.perf_counter()
    with pytest.raises(FileNotFoundError):
        files.read_file(str(tmp_path / "nope" / "agent.json"))
    assert time.perf_counter() - started < 0.04  # no 2 x 50 ms retry sleeps


def test_a_locked_file_is_still_retried():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked by the indexer")
        return "ok"

    assert files._read_with_lock_retry(flaky, delay_seconds=0) == "ok" and len(calls) == 3


def test_paths_are_reused_briefly_then_looked_up_again(monkeypatch):
    lookups = []
    original = files.exists

    def counting_exists(*args, **kwargs):
        lookups.append(1)
        return original(*args, **kwargs)

    subagents.clear_recent_paths()
    monkeypatch.setattr(files, "exists", counting_exists)
    first = subagents.get_paths(None, "prompts")
    after_first = len(lookups)
    assert subagents.get_paths(None, "prompts") == first
    assert len(lookups) == after_first  # reused: no path checks at all

    monkeypatch.setattr(subagents, "PATHS_TTL_SECONDS", 0.0)
    subagents.get_paths(None, "prompts")
    assert len(lookups) > after_first  # expired: looked up again


def test_a_plugin_change_drops_the_reused_paths(monkeypatch):
    subagents.clear_recent_paths()
    subagents.get_paths(None, "prompts")
    assert subagents._recent_paths
    monkeypatch.setattr(plugins, "send_frontend_reload_notification", lambda *a, **k: None, raising=False)
    plugins.clear_plugin_cache(None)
    assert not subagents._recent_paths


def test_the_tool_list_reads_files_like_agent_read_prompt(monkeypatch):
    from extensions.python.system_prompt import _11_tools_prompt as ext

    seen = []

    def fake_read_prompt_file(name, _directories=None, _agent=None, **kwargs):
        seen.append((name, tuple(_directories), kwargs))
        return f"## {name}"

    monkeypatch.setattr(files, "read_prompt_file", fake_read_prompt_file)
    text = ext._read_tool_prompt(object(), ["dir-a", "dir-b"], "agent.system.tool.x.md", {"flag": 1})
    assert text == "## agent.system.tool.x.md"
    assert seen == [("agent.system.tool.x.md", ("dir-a", "dir-b"), {"flag": 1})]
