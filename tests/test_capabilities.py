"""Capability policies: what an agent may use at all, in every permission mode."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import extension, plugins
from helpers.errors import RepairableException
from plugins._capabilities.helpers import policy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    """Write policies per (project, profile) scope into a temp tree."""

    def path_of(plugin, project, profile, *rest):
        folder = tmp_path / (project or "_global") / (profile or "_any")
        return str(folder.joinpath(*rest))

    monkeypatch.setattr(plugins, "determine_plugin_asset_path", path_of)
    monkeypatch.setattr(policy, "_scope_of", lambda agent: (agent.project, agent.config.profile))

    def write(project="", profile="", **config):
        file = Path(path_of("", project, profile, plugins.CONFIG_FILE_NAME))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(config), encoding="utf-8")

    return write


def _agent(profile="", project="", superior=None):
    data = {"_superior": superior} if superior else {}
    return SimpleNamespace(config=SimpleNamespace(profile=profile), project=project, data=data, context=None)


# -- capability ids --------------------------------------------------------------------

@pytest.mark.parametrize("name,args,expected", [
    ("text_editor:read", {}, "text_editor:read"),
    ("text_editor", {"action": "write"}, "text_editor:write"),
    ("code_execution_tool", {"runtime": "terminal", "code": "dir"}, "code_execution_tool:terminal"),
    ("browser", {"method": "Navigate"}, "browser:navigate"),
    ("search_engine", {"query": "x"}, "search_engine"),
    ("Some_Server.tool", None, "some_server.tool"),
])
def test_capability_ids(name, args, expected):
    assert policy.capability_id(name, args) == expected


# -- decisions --------------------------------------------------------------------------

def test_nothing_is_limited_by_default(scopes):
    assert policy.is_allowed(_agent("researcher"), "code_execution_tool:terminal")


def test_a_profile_can_be_read_only(scopes):
    scopes(profile="researcher", allow="text_editor:read\nsearch_engine\ndocument_query")
    agent = _agent("researcher")
    assert policy.is_allowed(agent, "text_editor:read")
    assert policy.is_allowed(agent, "search_engine")
    assert not policy.is_allowed(agent, "text_editor:write")
    assert not policy.is_allowed(agent, "code_execution_tool:terminal")
    assert policy.is_allowed(_agent("developer"), "text_editor:write")  # other profiles untouched


def test_a_bare_tool_pattern_covers_every_action(scopes):
    scopes(deny="code_execution_tool")
    for runtime in ("terminal", "python", "nodejs"):
        assert not policy.is_allowed(_agent(), f"code_execution_tool:{runtime}")


def test_deny_beats_allow_in_the_same_scope(scopes):
    scopes(allow="text_editor", deny="text_editor:write")
    assert policy.is_allowed(_agent(), "text_editor:read")
    assert not policy.is_allowed(_agent(), "text_editor:write")


def test_a_narrower_scope_cannot_widen_a_broader_one(scopes):
    scopes(deny="browser")  # global
    scopes(project="demo", allow="*")  # the project tries to allow everything
    assert not policy.is_allowed(_agent(project="demo"), "browser:navigate")


def test_every_scope_must_allow(scopes):
    scopes(project="demo", allow="text_editor\nsearch_engine")
    scopes(profile="researcher", allow="search_engine")
    assert policy.is_allowed(_agent("researcher", "demo"), "search_engine")
    assert not policy.is_allowed(_agent("researcher", "demo"), "text_editor:read")


def test_a_subordinate_keeps_its_superiors_limits(scopes):
    scopes(profile="researcher", deny="code_execution_tool")
    parent = _agent("researcher")
    child = _agent("developer", superior=parent)
    grandchild = _agent("developer", superior=child)
    assert not policy.is_allowed(child, "code_execution_tool:terminal")
    assert not policy.is_allowed(grandchild, "code_execution_tool:python")
    assert policy.is_allowed(_agent("developer"), "code_execution_tool:terminal")


def test_the_reply_tool_is_always_allowed(scopes):
    scopes(allow="search_engine")
    assert policy.is_allowed(_agent(), "response")


def test_an_unreadable_policy_allows_nothing(scopes, tmp_path):
    file = tmp_path / "_global" / "_any" / plugins.CONFIG_FILE_NAME
    file.parent.mkdir(parents=True)
    file.write_text("{ not json", encoding="utf-8")
    assert not policy.is_allowed(_agent(), "search_engine")


# -- the gate, through the real dispatcher -------------------------------------------

def _gate_classes():
    import importlib

    module = importlib.import_module("plugins._capabilities.extensions.python.tool_execute_before._04_capabilities")
    return [module.CapabilityGate]


def test_the_gate_refuses_through_the_dispatcher(scopes, monkeypatch):
    scopes(deny="text_editor:write")
    monkeypatch.setattr(extension, "_get_extension_classes", lambda point, agent=None, **kw: _gate_classes())
    agent = _agent()
    with pytest.raises(RepairableException, match="text_editor:write is not allowed"):
        asyncio.run(extension.call_extensions_async("tool_execute_before", agent=agent,
                                                    tool_name="text_editor", tool_args={"action": "write", "path": "a"}))
    asyncio.run(extension.call_extensions_async("tool_execute_before", agent=agent,
                                                tool_name="text_editor", tool_args={"action": "read", "path": "a"}))


def test_the_gate_runs_before_the_safety_floor_and_the_permission_gate():
    gate = ROOT / "plugins/_capabilities/extensions/python/tool_execute_before/_04_capabilities.py"
    assert gate.is_file() and "FAIL_LOUD = True" in gate.read_text(encoding="utf-8")
    assert (ROOT / "plugins/_safety_policy/extensions/python/tool_execute_before/_05_command_policy.py").is_file()
    assert (ROOT / "plugins/_permissions/extensions/python/tool_execute_before/_06_permissions.py").is_file()


# -- what the model is offered ------------------------------------------------------

def test_a_fully_denied_tool_is_hidden_and_a_partly_allowed_one_is_not(scopes):
    scopes(allow="text_editor:read\nsearch_engine")
    agent = _agent()
    assert policy.tool_hidden(agent, "code_execution_tool")
    assert not policy.tool_hidden(agent, "text_editor")  # its read action is allowed
    assert not policy.tool_hidden(agent, "search_engine")
    assert not policy.tool_hidden(agent, "response")


def test_the_model_is_told_its_limits(scopes):
    scopes(profile="researcher", deny="code_execution_tool")
    notes = policy.restrictions(_agent("researcher"))
    assert "code_execution_tool" in notes


def test_prompts_are_matched_by_the_tool_name_they_declare():
    import importlib

    module = importlib.import_module("extensions.python.system_prompt._11_tools_prompt")
    code_prompt = (ROOT / "prompts/agent.system.tool.code_exe.md")
    if not code_prompt.exists():
        code_prompt = next(ROOT.glob("plugins/*/prompts/agent.system.tool.code_exe.md"))
    assert module._declared_tool_name("agent.system.tool.code_exe.md", code_prompt.read_text(encoding="utf-8")) == "code_execution_tool"


def test_the_prompt_and_native_tools_use_the_policy():
    tools_prompt = (ROOT / "extensions/python/system_prompt/_11_tools_prompt.py").read_text(encoding="utf-8")
    native = (ROOT / "helpers/responses_tools.py").read_text(encoding="utf-8")
    assert "tool_hidden(agent, _declared_tool_name(basename, tool))" in tools_prompt and "Capability limits" in tools_prompt
    assert "tool_hidden(agent, tool_name)" in native


def test_defaults_change_nothing():
    text = (ROOT / "plugins/_capabilities/default_config.yaml").read_text(encoding="utf-8")
    assert 'allow: "*"' in text and 'deny: ""' in text


def test_a_changed_policy_takes_effect_at_once(scopes):
    import os
    import time

    scopes(deny="browser")
    assert not policy.is_allowed(_agent(), "browser:navigate")
    scopes(deny="")
    path = plugins.determine_plugin_asset_path("", "", "", plugins.CONFIG_FILE_NAME)
    os.utime(path, (time.time() + 5, time.time() + 5))  # a later save, even within the same second
    assert policy.is_allowed(_agent(), "browser:navigate")


# -- messaging channels -------------------------------------------------------------

def _channel_agent(channel, profile=""):
    agent = _agent(profile)
    agent.context = SimpleNamespace(data={"channel_origin": channel} if channel else {})
    return agent


def test_messaging_chats_get_their_extra_limits(scopes):
    scopes(messaging_deny="code_execution_tool")
    assert not policy.is_allowed(_channel_agent("telegram"), "code_execution_tool:terminal")
    assert policy.is_allowed(_channel_agent(""), "code_execution_tool:terminal")  # the WebUI is unaffected


def test_a_single_channel_can_be_limited(scopes):
    scopes(channels={"email": {"deny": "browser"}})
    assert not policy.is_allowed(_channel_agent("email"), "browser:navigate")
    assert policy.is_allowed(_channel_agent("telegram"), "browser:navigate")


def test_the_model_sees_its_messaging_limits(scopes):
    scopes(messaging_deny="code_execution_tool")
    assert "code_execution_tool" in policy.restrictions(_channel_agent("whatsapp"))
    assert "code_execution_tool" not in policy.restrictions(_channel_agent(""))


# -- bundled calls ------------------------------------------------------------------

def test_every_step_of_a_browser_multi_call_is_checked(scopes):
    scopes(deny="browser:evaluate")
    args = {"action": "multi", "calls": [{"action": "navigate", "url": "https://example.com"}, {"action": "evaluate", "script": "1"}]}
    assert "browser:evaluate is not allowed" in policy.denial_for_call(_agent(), "browser", args)
    assert policy.denial_for_call(_agent(), "browser", {"action": "multi", "calls": [{"action": "navigate"}]}) == ""


def test_every_call_of_a_parallel_batch_is_checked(scopes):
    scopes(deny="code_execution_tool")
    args = {"tool_calls": [{"tool_name": "search_engine", "tool_args": {"query": "x"}},
                           {"tool_name": "code_execution_tool", "tool_args": {"runtime": "terminal", "code": "dir"}}]}
    assert "code_execution_tool:terminal" in policy.denial_for_call(_agent(), "parallel", args)


def test_a_parallel_worker_keeps_the_limits_of_the_agent_that_started_it(scopes):
    scopes(profile="researcher", deny="code_execution_tool")
    child = _agent("developer", superior=_agent("researcher"))
    scopes_carried = policy.worker_scopes(child)
    assert ["", "researcher"] in scopes_carried
    worker = _agent("developer")  # a fresh top-level agent in a hidden context
    worker.context = SimpleNamespace(data={policy.CONTEXT_SCOPES_KEY: scopes_carried})
    assert not policy.is_allowed(worker, "code_execution_tool:terminal")


def test_jobs_carry_and_workers_receive_the_scopes():
    source = (ROOT / "helpers/parallel_tools.py").read_text(encoding="utf-8")
    assert "capability_scopes=_capability_scopes(agent)" in source
    calls = [line for line in source.splitlines() if line.strip() == "_set_capability_scopes(worker_context, job)"]
    assert len(calls) == 2  # both kinds of worker


# -- MCP and the settings list -------------------------------------------------------

def test_the_mcp_prompt_leaves_out_refused_tools(monkeypatch):
    from helpers import mcp_handler

    server = SimpleNamespace(name="files", description="file server", get_tools=lambda: [
        {"name": "read", "description": "read a file", "input_schema": {}},
        {"name": "delete", "description": "delete a file", "input_schema": {}}])
    config = object.__new__(mcp_handler.MCPConfig)
    monkeypatch.setattr(mcp_handler.MCPConfig, "servers", [server], raising=False)
    monkeypatch.setattr(mcp_handler.MCPConfig, "_MCPConfig__lock", __import__("threading").Lock(), raising=False)
    prompt = config.get_tools_prompt(include=lambda name: name != "files.delete")
    assert "files.read" in prompt and "files.delete" not in prompt


def test_the_settings_list_names_this_installs_tools():
    names = {item["tool"]: item["actions"] for item in policy.known_capabilities()}
    assert "text_editor" in names and "read" in names["text_editor"]
    assert "code_execution_tool" in names
