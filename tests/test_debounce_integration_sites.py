"""Integration tests for the four call sites wired to helpers.debounced
this turn (items 9 and 10 of the improvements list):

- _75_include_workdir_extras.py (file_tree.file_tree)
- _13_skills_prompt.py (skills_helper.list_skills)
- _16_promptinclude.py (scan_promptinclude_files, non-dev/Windows branch)
- persist_chat.save_tmp_chat_async (the disk write, not the debounce
  helper - it uses asyncio.to_thread directly since a single write never
  needs the shared-cache/thundering-herd behaviour debounced.py gives the
  three scans above)

Each debounced.py mechanic already has its own thorough unit tests in
test_debounced.py; the point here is narrower - proving each real call
site is actually wired to it (repeated calls within the TTL do not
re-invoke the underlying scan) rather than re-testing the mechanic.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import debounced


@pytest.fixture(autouse=True)
def _clear_debounce_cache():
    debounced.clear()
    yield
    debounced.clear()


# ---------------------------------------------------------------------
# _75_include_workdir_extras.py
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workdir_extras_does_not_rewalk_within_ttl(monkeypatch):
    from extensions.python.message_loop_prompts_after import (
        _75_include_workdir_extras as wd_mod,
    )

    calls = []

    def fake_file_tree(scan_path, **kwargs):
        calls.append(1)
        return "TREE"

    monkeypatch.setattr(wd_mod.file_tree, "file_tree", fake_file_tree)
    monkeypatch.setattr(wd_mod.projects, "get_context_project_name", lambda ctx: None)
    monkeypatch.setattr(
        wd_mod.settings,
        "get_settings",
        lambda: {
            "workdir_show": True,
            "workdir_max_depth": 2,
            "workdir_max_files": 10,
            "workdir_max_folders": 10,
            "workdir_max_lines": 100,
            "workdir_gitignore": "",
            "workdir_path": "usr/workdir",
        },
    )
    monkeypatch.setattr(wd_mod.runtime, "is_development", lambda: False)
    monkeypatch.setattr(wd_mod.files, "get_abs_path_development", lambda p: "C:\\fake\\workdir")
    monkeypatch.setattr(wd_mod.files, "create_dir", lambda p: None)

    class _Agent:
        def read_prompt(self, name, **k):
            return f"PROMPT:{k.get('file_structure')}"

        context = SimpleNamespace()

    ext = wd_mod.IncludeWorkdirExtras(agent=_Agent())  # type: ignore[arg-type]

    loop_data = SimpleNamespace(extras_temporary={})
    await ext.execute(loop_data=loop_data)
    await ext.execute(loop_data=loop_data)

    assert len(calls) == 1, "a second call within the TTL must reuse the cached walk"
    assert "TREE" in loop_data.extras_temporary["project_file_structure"]


@pytest.mark.asyncio
async def test_workdir_extras_cache_key_changes_with_max_depth(monkeypatch):
    """A settings change must not be served a result computed under the
    previous limits."""
    from extensions.python.message_loop_prompts_after import (
        _75_include_workdir_extras as wd_mod,
    )

    calls = []

    def fake_file_tree(scan_path, **kwargs):
        calls.append(kwargs["max_depth"])
        return f"TREE-{kwargs['max_depth']}"

    monkeypatch.setattr(wd_mod.file_tree, "file_tree", fake_file_tree)
    monkeypatch.setattr(wd_mod.projects, "get_context_project_name", lambda ctx: None)
    monkeypatch.setattr(wd_mod.runtime, "is_development", lambda: False)
    monkeypatch.setattr(wd_mod.files, "get_abs_path_development", lambda p: "C:\\fake\\workdir")
    monkeypatch.setattr(wd_mod.files, "create_dir", lambda p: None)

    depth = {"value": 2}

    def fake_settings():
        return {
            "workdir_show": True,
            "workdir_max_depth": depth["value"],
            "workdir_max_files": 10,
            "workdir_max_folders": 10,
            "workdir_max_lines": 100,
            "workdir_gitignore": "",
            "workdir_path": "usr/workdir",
        }

    monkeypatch.setattr(wd_mod.settings, "get_settings", fake_settings)

    class _Agent:
        def read_prompt(self, name, **k):
            return "PROMPT"

        context = SimpleNamespace()

    ext = wd_mod.IncludeWorkdirExtras(agent=_Agent())  # type: ignore[arg-type]

    loop_data = SimpleNamespace(extras_temporary={})
    await ext.execute(loop_data=loop_data)
    depth["value"] = 5
    await ext.execute(loop_data=loop_data)

    assert calls == [2, 5], "a max_depth change must trigger a fresh walk, not reuse the old one"


# ---------------------------------------------------------------------
# _13_skills_prompt.py
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_prompt_does_not_relist_within_ttl(monkeypatch):
    from extensions.python.system_prompt import _13_skills_prompt as sp_mod

    calls = []

    def fake_list_skills(agent):
        calls.append(1)
        return [SimpleNamespace(name="demo", description="a demo skill")]

    monkeypatch.setattr(sp_mod.skills_helper, "list_skills", fake_list_skills)
    monkeypatch.setattr(sp_mod.projects, "get_context_project_name", lambda ctx: None)

    class _Agent:
        config = SimpleNamespace(profile="default")
        context = SimpleNamespace()

        def read_prompt(self, name, **k):
            return f"SKILLS:{k['skills']}"

    agent = _Agent()

    first = await sp_mod.build_prompt(agent)
    second = await sp_mod.build_prompt(agent)

    assert len(calls) == 1, "a second build within the TTL must reuse the cached listing"
    assert first == second
    assert "demo" in first


@pytest.mark.asyncio
async def test_skills_prompt_cache_key_changes_with_profile(monkeypatch):
    from extensions.python.system_prompt import _13_skills_prompt as sp_mod

    calls = []

    def fake_list_skills(agent):
        calls.append(agent.config.profile)
        return [SimpleNamespace(name=agent.config.profile, description="")]

    monkeypatch.setattr(sp_mod.skills_helper, "list_skills", fake_list_skills)
    monkeypatch.setattr(sp_mod.projects, "get_context_project_name", lambda ctx: None)

    class _Agent:
        def __init__(self, profile):
            self.config = SimpleNamespace(profile=profile)
            self.context = SimpleNamespace()

        def read_prompt(self, name, **k):
            return f"SKILLS:{k['skills']}"

    await sp_mod.build_prompt(_Agent("default"))
    await sp_mod.build_prompt(_Agent("coder"))

    assert calls == ["default", "coder"], "a different profile must not reuse another profile's listing"


# ---------------------------------------------------------------------
# _16_promptinclude.py
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promptinclude_does_not_rescan_within_ttl(monkeypatch):
    from plugins._promptinclude.extensions.python.system_prompt import (
        _16_promptinclude as pi_mod,
    )

    calls = []

    def fake_scan(scan_path, **kwargs):
        calls.append(1)
        return {"files": [], "skipped_count": 0}

    monkeypatch.setattr(pi_mod, "scan_promptinclude_files", fake_scan)
    monkeypatch.setattr(pi_mod.runtime, "is_development", lambda: False)
    monkeypatch.setattr(pi_mod.plugins, "get_plugin_config", lambda name, agent=None: {})
    monkeypatch.setattr(pi_mod, "_resolve_workdir", lambda agent: "C:\\somewhere")

    class _Agent:
        def read_prompt(self, name, **k):
            return f"PROMPT:{name}"

        context = SimpleNamespace()

    agent = _Agent()
    ext = pi_mod.PromptInclude(agent=agent)  # type: ignore[arg-type]
    system_prompt: list[str] = []
    await ext._append_includes(system_prompt)
    await ext._append_includes(system_prompt)

    assert len(calls) == 1, "a second call within the TTL must reuse the cached scan"


@pytest.mark.asyncio
async def test_promptinclude_dev_non_windows_branch_bypasses_debounce(monkeypatch):
    """The RFC dispatch branch is load-bearing for correctness (it must
    hit the dev host's filesystem view, not this process's), so it must
    keep calling call_development_function on every invocation, not the
    debounced cache."""
    from plugins._promptinclude.extensions.python.system_prompt import (
        _16_promptinclude as pi_mod,
    )

    rfc_calls = []

    async def fake_rfc(func, *a, **k):
        rfc_calls.append(1)
        return {"files": [], "skipped_count": 0}

    monkeypatch.setattr(pi_mod.runtime, "is_development", lambda: True)
    monkeypatch.setattr(pi_mod.runtime, "is_windows", lambda: False)
    monkeypatch.setattr(pi_mod.runtime, "call_development_function", fake_rfc)
    monkeypatch.setattr(pi_mod.plugins, "get_plugin_config", lambda name, agent=None: {})
    monkeypatch.setattr(pi_mod, "_resolve_workdir", lambda agent: "C:\\somewhere")

    class _Agent:
        def read_prompt(self, name, **k):
            return f"PROMPT:{name}"

        context = SimpleNamespace()

    agent = _Agent()
    ext = pi_mod.PromptInclude(agent=agent)  # type: ignore[arg-type]
    system_prompt: list[str] = []
    await ext._append_includes(system_prompt)
    await ext._append_includes(system_prompt)

    assert len(rfc_calls) == 2, "the dev/non-Windows branch must not be debounced"


# ---------------------------------------------------------------------
# persist_chat.save_tmp_chat_async
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_tmp_chat_async_produces_same_output_as_sync(monkeypatch, tmp_path):
    from helpers import persist_chat

    written = {}

    def fake_write_file(path, content):
        written[path] = content

    monkeypatch.setattr(persist_chat.files, "write_file", fake_write_file)
    monkeypatch.setattr(persist_chat.files, "make_dirs", lambda path: None)
    monkeypatch.setattr(
        persist_chat, "_get_chat_file_path", lambda ctxid: f"chats/{ctxid}/chat.json"
    )

    class _Context:
        type = persist_chat.AgentContextType.USER

    monkeypatch.setattr(
        persist_chat, "_serialize_context", lambda ctx: {"id": ctx.id, "n": 1}
    )

    ctx_sync = _Context()
    ctx_sync.id = "ctx-sync"
    ctx_sync.data = {}
    persist_chat.save_tmp_chat(ctx_sync)

    ctx_async = _Context()
    ctx_async.id = "ctx-async"
    ctx_async.data = {}
    await persist_chat.save_tmp_chat_async(ctx_async)

    sync_content = written["chats/ctx-sync/chat.json"]
    async_content = written["chats/ctx-async/chat.json"].replace("ctx-async", "ctx-sync")
    assert sync_content == async_content
    assert ctx_sync.data[persist_chat.SAVED_CHAT_CONTEXT_DATA_KEY] is True
    assert ctx_async.data[persist_chat.SAVED_CHAT_CONTEXT_DATA_KEY] is True


@pytest.mark.asyncio
async def test_save_tmp_chat_async_skips_background_contexts(monkeypatch):
    from helpers import persist_chat

    write_calls = []
    monkeypatch.setattr(
        persist_chat.files, "write_file", lambda *a, **k: write_calls.append(1)
    )

    class _Context:
        id = "bg-1"
        type = persist_chat.AgentContextType.BACKGROUND
        data = {}

    await persist_chat.save_tmp_chat_async(_Context())

    assert write_calls == [], "BACKGROUND contexts must never be persisted"


@pytest.mark.asyncio
async def test_save_tmp_chat_async_write_does_not_block_the_loop(monkeypatch):
    """The entire point of #10: the write must run on a worker thread, not
    stall the event loop for its duration."""
    from helpers import persist_chat

    calling_thread = {}

    def slow_write(path, content):
        calling_thread["id"] = threading.get_ident()
        time.sleep(0.2)

    monkeypatch.setattr(persist_chat.files, "write_file", slow_write)
    monkeypatch.setattr(persist_chat.files, "make_dirs", lambda path: None)
    monkeypatch.setattr(
        persist_chat, "_get_chat_file_path", lambda ctxid: f"chats/{ctxid}/chat.json"
    )
    monkeypatch.setattr(persist_chat, "_serialize_context", lambda ctx: {"id": ctx.id})

    class _Context:
        id = "ctx-slow"
        type = persist_chat.AgentContextType.USER
        data = {}

    ticks = []

    async def ticker():
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks.append(1)

    await asyncio.gather(
        persist_chat.save_tmp_chat_async(_Context()),
        ticker(),
    )

    assert calling_thread["id"] != threading.get_ident()
    assert len(ticks) >= 5, "the event loop must keep making progress during the write"
