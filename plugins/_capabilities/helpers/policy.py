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
from typing import Any

PLUGIN = "_capabilities"
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


def _layer_allows(layer: dict, capability: str) -> bool:
    allow = _patterns(layer.get("allow")) if "allow" in layer else ["*"]
    deny = _patterns(layer.get("deny"))
    return any(_matches(capability, p) for p in allow) and not any(_matches(capability, p) for p in deny)


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


def layers(project: str = "", profile: str = "") -> list[dict]:
    """The policies of every scope that has one, broadest first."""
    from helpers import plugins

    found = []
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


def is_allowed(agent, capability: str) -> bool:
    if capability.split(":", 1)[0] in ALWAYS_ALLOWED:
        return True
    for member in _agent_chain(agent):
        for layer in layers(*_scope_of(member)):
            if not _layer_allows(layer, capability):
                return False
    return True


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
    for member in _agent_chain(agent):
        for layer in layers(*_scope_of(member)):
            if any(p.startswith(tool + ":") for p in _patterns(layer.get("allow"))):
                return False
    return True


def restrictions(agent) -> list[str]:
    """The deny patterns that apply to this agent, for the prompt notice."""
    found: list[str] = []
    for member in _agent_chain(agent):
        for layer in layers(*_scope_of(member)):
            for pattern in _patterns(layer.get("deny")):
                if pattern not in found:
                    found.append(pattern)
            if "allow" in layer and _patterns(layer.get("allow")) != ["*"]:
                note = "only: " + ", ".join(_patterns(layer.get("allow")) or ["nothing"])
                if note not in found:
                    found.append(note)
    return found
