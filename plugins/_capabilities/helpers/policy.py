"""Capability policies: which tools and tool actions an agent may use at all.

A permission mode (Plan ... Bypass) says how freely a chat may act. A
capability policy says what an agent may do in the first place: a research
profile can be limited to reading, whatever mode its chat is in.

A capability is `tool` or `tool:action`: `text_editor:write`,
`code_execution_tool:terminal`, `browser:navigate`. The action comes from the
tool name (`text_editor:read`) or the call's `action`, `method` or `runtime`
argument. MCP tools are their own names.

Each scope can set `allow` and `deny` glob patterns: global, project, agent
profile, and project + profile. A call must pass every scope that sets a
policy: allowed by each scope's `allow` (default everything) and denied by
none. A subordinate agent is also bound by its superior's policy, so a
narrower scope or a child can never widen what the parent may do.

Enforced before every tool call (`tool_execute_before/_04_capabilities`, ahead
of the safety floor and the permission gate, in every mode), and fully denied
tools are left out of the system prompt and the native tool list.
"""

from __future__ import annotations

import fnmatch
import json
import os
from typing import Any

PLUGIN = "_capabilities"
# Scopes a hidden worker context inherits from the agent that started it (a
# parallel job runs as a fresh top-level agent, outside the superior chain).
CONTEXT_SCOPES_KEY = "capability_scopes"  # no leading _: saved with a child agent's chat
# Tools every agent needs to finish a turn or report trouble.
ALWAYS_ALLOWED = {"response"}


def capability_id(tool_name: str, tool_args: dict | None = None) -> str:
    name = str(tool_name or "").strip().lower()
    tool, _, action = name.partition(":")
    if not action and isinstance(tool_args, dict):
        for key in ("action", "method", "runtime"):
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                action = value.strip().lower()
                break
    return f"{tool}:{action}" if action else tool


def _patterns(value: Any) -> list[str]:
    if isinstance(value, str):
        items = value.splitlines()
    elif isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        return []
    return [item.strip().lower() for item in items if item.strip() and not item.strip().startswith("#")]


def _matches(capability: str, pattern: str) -> bool:
    tool = capability.split(":", 1)[0]
    if ":" not in pattern:
        return fnmatch.fnmatchcase(tool, pattern)  # a bare tool name covers all its actions
    return fnmatch.fnmatchcase(capability, pattern)


def _layer_allows(layer: dict, capability: str, channel: str = "") -> bool:
    allow = _patterns(layer.get("allow")) if "allow" in layer else ["*"]
    deny = _patterns(layer.get("deny"))
    if not any(_matches(capability, p) for p in allow) or any(_matches(capability, p) for p in deny):
        return False
    if channel:
        # A chat that came in over Telegram, WhatsApp, email, Discord or Slack.
        if any(_matches(capability, p) for p in _patterns(layer.get("messaging_deny"))):
            return False
        per_channel = (layer.get("channels") or {}).get(channel) if isinstance(layer.get("channels"), dict) else None
        if isinstance(per_channel, dict) and not _layer_allows(per_channel, capability):
            return False
    return True


def _channel(agent) -> str:
    """The messaging channel the agent's chat acts for ("" for the WebUI)."""
    try:
        from helpers import channels, parallel_tools

        context, _orphaned = parallel_tools.governing_context(getattr(agent, "context", None))
        return channels.channel_of(context or getattr(agent, "context", None))
    except Exception:
        return ""


_cache: dict[str, tuple[float, dict | None]] = {}  # path -> (mtime, policy): checked on every tool call


def _read_config(path: str) -> dict | None:
    import os

    from helpers import files
    from helpers import yaml as yaml_helper

    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    if mtime is None:
        return None
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        text = files.read_file(path)
        data = json.loads(text) if path.lower().endswith(".json") else yaml_helper.loads(text)
        data = data if isinstance(data, dict) else None
    except Exception:
        data = {"allow": [], "deny": ["*"]}  # an unreadable policy allows nothing (fail closed)
    _cache[path] = (mtime, data)
    return data


def _shipped_profile_layer(profile: str) -> dict | None:
    """A limit a bundled agent profile ships with (agents/<profile>/
    capabilities.yaml), e.g. the read-only coding reviewer. User settings can
    narrow it further, never widen it."""
    from helpers import files

    if not profile or "/" in profile or "\\" in profile or profile.startswith("."):
        return None
    return _read_config(files.get_abs_path("agents", profile, "capabilities.yaml"))


def layers(project: str = "", profile: str = "") -> list[dict]:
    """The policies of every scope that has one, broadest first."""
    from helpers import plugins

    found = []
    shipped = _shipped_profile_layer(profile)
    if shipped is not None:
        found.append(shipped)
    scopes = [("", "")]
    if project:
        scopes.append((project, ""))
    if profile:
        scopes.append(("", profile))
    if project and profile:
        scopes.append((project, profile))
    for proj, prof in scopes:
        try:
            path = plugins.determine_plugin_asset_path(PLUGIN, proj, prof, plugins.CONFIG_FILE_NAME)
        except Exception:
            continue
        data = _read_config(path)
        if data is not None:
            found.append(data)
    return found


def _scope_of(agent) -> tuple[str, str]:
    project = ""
    try:
        from helpers import projects

        project = projects.get_context_project_name(agent.context) or ""
    except Exception:
        pass
    profile = str(getattr(getattr(agent, "config", None), "profile", "") or "")
    return project, profile


def _agent_chain(agent):
    """The agent and each superior above it."""
    seen = set()
    while agent is not None and id(agent) not in seen:
        seen.add(id(agent))
        yield agent
        try:
            from agent import Agent

            agent = agent.data.get(Agent.DATA_NAME_SUPERIOR)
        except Exception:
            agent = None


def scope_chain(agent) -> list[tuple[str, str]]:
    """Every (project, profile) whose policy binds this agent: its own, each
    superior's, and those a worker context inherited."""
    found: list[tuple[str, str]] = []
    for member in _agent_chain(agent):
        candidates = [_scope_of(member)]
        data = getattr(getattr(member, "context", None), "data", None)
        inherited = data.get(CONTEXT_SCOPES_KEY) if isinstance(data, dict) else None
        if isinstance(inherited, list):
            candidates += [tuple(item) for item in inherited if isinstance(item, (list, tuple)) and len(item) == 2]
        for scope in candidates:
            if scope not in found:
                found.append(scope)
    return found


def _all_layers(agent) -> list[dict]:
    result = []
    for project, profile in scope_chain(agent):
        result += layers(project, profile)
    return result


def is_allowed(agent, capability: str) -> bool:
    if capability.split(":", 1)[0] in ALWAYS_ALLOWED:
        return True
    channel = _channel(agent)
    return all(_layer_allows(layer, capability, channel) for layer in _all_layers(agent))


def calls_of(tool_name: str, tool_args: dict | None) -> list[str]:
    """The capability of a call and of every call it bundles: a browser
    `multi` call's steps, a `parallel` call's tool calls."""
    found = [capability_id(tool_name, tool_args)]
    args = tool_args if isinstance(tool_args, dict) else {}
    tool = str(tool_name or "").split(":", 1)[0].lower()
    if tool == "browser" and found[0] == "browser:multi":
        for step in args.get("calls") or []:
            if isinstance(step, dict):
                found.append(capability_id("browser", step))
    if tool == "parallel":
        try:
            from helpers import parallel_tools

            raw = parallel_tools.extract_tool_calls(args)
            if raw is not None:
                for call in parallel_tools.normalize_parallel_tool_calls(raw):
                    found += calls_of(call.tool_name, call.tool_args)
        except Exception:
            pass  # a malformed batch fails in the tool itself
    return found


def worker_scopes(agent) -> list[list[str]]:
    """What a worker context started by `agent` must carry (CONTEXT_SCOPES_KEY)."""
    return [list(scope) for scope in scope_chain(agent)]


def denial_for_call(agent, tool_name: str, tool_args: dict | None) -> str:
    for capability in calls_of(tool_name, tool_args):
        reason = denial(agent, capability)
        if reason:
            return reason
    return ""


def denial(agent, capability: str) -> str:
    """Why `capability` is refused, or "" when it is allowed."""
    if is_allowed(agent, capability):
        return ""
    profile = _scope_of(agent)[1] or "default"
    return (f"[capabilities] {capability} is not allowed for this agent (profile: {profile}). "
            "It is outside what this agent may do in any permission mode; do the task another way "
            "or tell the user it needs a different agent.")


def tool_hidden(agent, tool: str) -> bool:
    """True when no action of `tool` is allowed: leave it out of the prompt."""
    tool = str(tool or "").strip().lower()
    if tool in ALWAYS_ALLOWED:
        return False
    if is_allowed(agent, tool):
        return False
    # The bare tool is refused, but a specific action may still be allowed.
    for layer in _all_layers(agent):
        if any(p.startswith(tool + ":") for p in _patterns(layer.get("allow"))):
            return False
    return True


def restrictions(agent) -> list[str]:
    """The deny patterns that apply to this agent, for the prompt notice."""
    found: list[str] = []
    channel = _channel(agent)
    for layer in _all_layers(agent):
        denied = _patterns(layer.get("deny"))
        if channel:
            denied += _patterns(layer.get("messaging_deny"))
            per_channel = (layer.get("channels") or {}).get(channel) if isinstance(layer.get("channels"), dict) else None
            if isinstance(per_channel, dict):
                denied += _patterns(per_channel.get("deny"))
        for pattern in denied:
            if pattern not in found:
                found.append(pattern)
        if "allow" in layer and _patterns(layer.get("allow")) != ["*"]:
            note = "only: " + ", ".join(_patterns(layer.get("allow")) or ["nothing"])
            if note not in found:
                found.append(note)
    return found


# Actions users can write after a tool name, for the list in Settings.
KNOWN_ACTIONS = {
    "text_editor": ["read", "write", "patch"],
    "code_execution_tool": ["terminal", "python", "nodejs", "output", "reset"],
    "browser": ["open", "navigate", "content", "click", "type", "submit", "evaluate", "multi", "screenshot", "close"],
    "parallel": ["start", "await", "cancel"],
    "child_agent": ["start", "message", "result", "status", "stop", "forget"],
    "coding_task": ["start", "diff", "commit", "merge", "discard", "list"],
}


def known_capabilities(agent=None) -> list[dict]:
    """Tool names this install offers, with their known actions."""
    from helpers import files, subagents

    names: set[str] = set()
    try:
        dirs = subagents.get_paths(agent, "prompts") if agent else [files.get_abs_path("prompts")]
        dirs += [str(p) for p in __import__("pathlib").Path(files.get_abs_path("plugins")).glob("*/prompts")]
        from helpers.responses_tools import _tool_name_from_prompt

        for path in files.get_unique_filenames_in_dirs(dirs, "agent.system.tool.*.md"):
            base = os.path.basename(path)
            fallback = base[len("agent.system.tool."):-len(".md")]
            try:
                names.add(_tool_name_from_prompt(files.read_file(path), fallback=fallback))
            except Exception:
                names.add(fallback)
    except Exception:
        pass
    try:
        from helpers import mcp_handler

        for entry in mcp_handler.MCPConfig.get_instance().get_tools() or []:
            if isinstance(entry, dict):
                names.update(str(name) for name in entry)
    except Exception:
        pass
    names.discard("tools")
    names.discard("tools_vision")
    return [{"tool": name, "actions": KNOWN_ACTIONS.get(name, [])} for name in sorted(names)]
