"""Permission rules and the decision engine, modelled on Claude Code.

Five modes, matching Claude Code's own selector:

    auto          the harness decides; permissive but still rule-governed
    manual        ask before anything that changes state
    accept_edits  file edits proceed; anything that executes still asks
    plan          refuse state changes outright, so a plan comes first
    bypass        allow everything the safety floor still permits

Rules are written as ``Tool`` or ``Tool(pattern)``, e.g.::

    code_execution_tool                    every call to that tool
    code_execution_tool(git status*)       only matching commands
    text_editor(write:*)                   only writes
    *(*)                                   everything

Precedence is deny > ask > allow > mode, which is the order that makes a
deny rule meaningful: any other order would let a broad allow silently
outrank a specific prohibition.

This module deliberately has no Agent Zero imports. The gate extension,
the API and the tests all share it, and a decision engine that cannot be
exercised without a running agent is one that does not get tested.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Literal


Decision = Literal["allow", "ask", "deny"]
Mode = Literal["auto", "manual", "accept_edits", "plan", "bypass"]

MODES: tuple[Mode, ...] = ("auto", "manual", "accept_edits", "plan", "bypass")
DEFAULT_MODE: Mode = "auto"

# How a tool's effect is classified. Modes are expressed in terms of these
# rather than tool names, so a new tool inherits sensible behaviour instead
# of silently defaulting to "allowed".
Effect = Literal["read", "edit", "execute"]

# Tools that only observe. Everything absent from this map is treated as
# "execute" - the conservative default, since an unknown tool is more
# likely to act than to merely look.
_READ_ONLY_TOOLS = {
    "search_engine",
    "document_query",
    "desktop_screenshot",
    "knowledge_tool",
    "vision_load",
    "webpage_content_tool",
}

# Tools that write files. Split out because "accept edits" mode exists
# precisely to treat them differently from tools that execute code.
_EDIT_TOOLS = {
    "text_editor",
    "office_artifact",
}

# Per-tool action arguments that flip a normally-editing tool to read-only,
# so `text_editor(read)` is not treated as a change.
_READ_ACTIONS = {
    "text_editor": {"read", "search", "list"},
    "memory": {"memory_load"},
    "scheduler": {"list_tasks", "show_task", "find_task_by_name"},
    "skills": {"list", "search", "read_file"},
    "ytdlp": {"info", "formats"},
    "desktop_control": {"focus"},
}

# The argument that best identifies what a call will actually do, used as
# the text a rule pattern matches against. Falls back to a compact JSON of
# all arguments so a pattern can still target tools not listed here.
_TARGET_ARGS = {
    "code_execution_tool": ("code",),
    "text_editor": ("action", "path"),
    "ytdlp": ("action", "url"),
    "desktop_control": ("action", "window"),
    "search_engine": ("query",),
    "document_query": ("document",),
    "call_subordinate": ("profile", "message"),
    "browser": ("action",),
    "memory": ("action", "query"),
    "scheduler": ("action", "name"),
    "skills": ("action", "skill_name"),
}

_RULE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_*.-]+)\s*(?:\((.*)\))?\s*$", re.DOTALL)


class RuleError(ValueError):
    """A rule string that cannot be parsed."""


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str | None = None
    source: str = ""

    @classmethod
    def parse(cls, text: str) -> "Rule":
        raw = str(text or "").strip()
        if not raw:
            raise RuleError("empty rule")
        match = _RULE_PATTERN.match(raw)
        if not match:
            raise RuleError(f"cannot parse rule {raw!r}; expected Tool or Tool(pattern)")
        tool, pattern = match.group(1), match.group(2)
        return cls(tool=tool, pattern=pattern, source=raw)

    def matches(self, tool_name: str, target: str) -> bool:
        if not fnmatch.fnmatchcase(tool_name, self.tool):
            return False
        if self.pattern is None:
            # A bare tool name matches every call to that tool.
            return True
        # Case-insensitive: commands and paths are typed by hand and a rule
        # that fails on capitalisation is a rule that quietly does nothing.
        return fnmatch.fnmatch(target.lower(), self.pattern.strip().lower())


@dataclass
class Ruleset:
    deny: list[Rule] = field(default_factory=list)
    ask: list[Rule] = field(default_factory=list)
    allow: list[Rule] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: dict) -> "Ruleset":
        def _parse(key: str) -> list[Rule]:
            rules = []
            for entry in _as_list(cfg.get(key)):
                try:
                    rules.append(Rule.parse(entry))
                except RuleError:
                    # A malformed rule must not take down the gate; dropping
                    # it is safe because an unparsed allow grants nothing and
                    # an unparsed deny falls through to the mode default.
                    continue
            return rules

        return cls(deny=_parse("deny"), ask=_parse("ask"), allow=_parse("allow"))


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line for line in value.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return []


def target_text(tool_name: str, tool_args: dict | None) -> str:
    """The text a rule pattern is matched against for this call."""
    args = tool_args or {}
    keys = _TARGET_ARGS.get(tool_name)
    if keys:
        parts = [str(args.get(k, "")).strip() for k in keys]
        joined = ":".join(p for p in parts if p)
        if joined:
            return joined
    if not args:
        return ""
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except Exception:
        return str(args)


def classify(tool_name: str, tool_args: dict | None) -> Effect:
    """What kind of effect this call has: read, edit, or execute."""
    args = tool_args or {}
    action = str(args.get("action", "")).strip().lower()

    read_actions = _READ_ACTIONS.get(tool_name)
    if read_actions and action in read_actions:
        return "read"
    if tool_name in _READ_ONLY_TOOLS:
        return "read"
    if tool_name in _EDIT_TOOLS:
        return "edit"
    # Unknown tools count as executing. A new tool that merely reads will be
    # over-guarded, which is recoverable; the reverse is not.
    return "execute"


# What each mode does with each effect when no rule matched.
_MODE_DEFAULTS: dict[str, dict[str, Decision]] = {
    # Permissive but still governed by rules and the safety floor. This is
    # the closest analogue to "the harness decides".
    "auto": {"read": "allow", "edit": "allow", "execute": "allow"},
    "manual": {"read": "allow", "edit": "ask", "execute": "ask"},
    "accept_edits": {"read": "allow", "edit": "allow", "execute": "ask"},
    # Planning refuses rather than asks: the point is to produce a plan, and
    # a prompt the user can approve would defeat that.
    "plan": {"read": "allow", "edit": "deny", "execute": "deny"},
    "bypass": {"read": "allow", "edit": "allow", "execute": "allow"},
}


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str
    matched: str = ""


def decide(
    tool_name: str,
    tool_args: dict | None,
    mode: str = DEFAULT_MODE,
    ruleset: Ruleset | None = None,
) -> Verdict:
    """Resolve one tool call to allow, ask, or deny.

    Rules outrank the mode, and among rules deny outranks ask outranks
    allow - so a specific prohibition is never overridden by a broad
    permission, whichever order they were written in.
    """
    ruleset = ruleset or Ruleset()
    mode = str(mode or DEFAULT_MODE).strip().lower()
    if mode not in _MODE_DEFAULTS:
        mode = DEFAULT_MODE
    target = target_text(tool_name, tool_args)

    effect = classify(tool_name, tool_args)

    for decision, rules in (
        ("deny", ruleset.deny),
        ("ask", ruleset.ask),
        ("allow", ruleset.allow),
    ):
        for rule in rules:
            if not rule.matches(tool_name, target):
                continue

            # Bypass means "stop asking me". Honouring an ask rule there
            # would produce exactly the prompt the mode exists to remove.
            # Deny rules still bind: an explicit prohibition the user wrote
            # should not be discarded by changing mode.
            if decision == "ask" and mode == "bypass":
                return Verdict(
                    "allow",
                    f"bypass mode overrides ask rule {rule.source!r}",
                    rule.source,
                )

            # Plan mode's guarantee is that nothing changes. An allow rule
            # is a statement about trust, not about wanting edits during
            # planning, so it does not unlock them.
            if decision == "allow" and mode == "plan" and effect != "read":
                return Verdict(
                    "deny",
                    f"plan mode: {effect} operations are refused even though "
                    f"{rule.source!r} allows this tool",
                    rule.source,
                )

            return Verdict(
                decision=decision,  # type: ignore[arg-type]
                reason=f"matched {decision} rule {rule.source!r}",
                matched=rule.source,
            )

    decision = _MODE_DEFAULTS[mode][effect]
    return Verdict(
        decision=decision,
        reason=f"{mode} mode: {effect} operations are set to {decision}",
    )


def rule_for(tool_name: str, tool_args: dict | None, scope: str = "exact") -> str:
    """Suggest a rule string covering this call.

    Used by the "always allow" affordance on an approval prompt, so that
    answering a question once can stop it being asked again.
    """
    if scope == "tool":
        return tool_name
    target = target_text(tool_name, tool_args)
    if not target:
        return tool_name
    return f"{tool_name}({target})"
