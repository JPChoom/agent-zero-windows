from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from helpers import files, subagents


FUNCTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TOOL_NAME_EXAMPLE_PATTERN = re.compile(
    r"""["']tool_name["']\s*:\s*["']([A-Za-z0-9_-]{1,64})["']"""
)
TOOL_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
TOOL_PROMPT_PREFIX = "agent.system.tool."
TOOL_PROMPT_SUFFIX = ".md"
MAX_TOOL_DESCRIPTION_CHARS = 1024


def build_responses_function_tools(agent: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build permissive Responses function tools from A0 tool prompts and MCP schemas."""

    tools: list[dict[str, Any]] = []
    name_map: dict[str, str] = {}

    for tool_name, prompt in _local_tool_prompts(agent):
        native_name = _native_tool_name(tool_name)
        name_map[native_name] = tool_name
        tools.append(
            {
                "type": "function",
                "name": native_name,
                "description": _description_from_prompt(prompt, fallback=tool_name),
                "parameters": _schema_from_prompt(prompt),
            }
        )

    for tool_name, tool in _mcp_tools(agent):
        native_name = _native_tool_name(tool_name)
        name_map[native_name] = tool_name
        tools.append(
            {
                "type": "function",
                "name": native_name,
                "description": _truncate(str(tool.get("description") or tool_name)),
                "parameters": _schema_from_any(tool.get("input_schema")),
            }
        )

    return _dedupe_tools(tools), name_map


def original_tool_name(native_name: str, name_map: dict[str, str] | None) -> str:
    if not name_map:
        return native_name
    return name_map.get(native_name, native_name)


def _local_tool_prompts(agent: Any) -> list[tuple[str, str]]:
    prompt_dirs = subagents.get_paths(agent, "prompts")
    tool_files = files.get_unique_filenames_in_dirs(
        prompt_dirs, f"{TOOL_PROMPT_PREFIX}*{TOOL_PROMPT_SUFFIX}"
    )
    result: list[tuple[str, str]] = []
    for tool_file in tool_files:
        basename = os.path.basename(tool_file)
        fallback_name = _tool_name_from_prompt_basename(basename)
        if not fallback_name:
            continue
        try:
            prompt = agent.read_prompt(basename)
        except Exception:
            try:
                prompt = files.read_file(tool_file)
            except Exception:
                prompt = ""
        tool_name = _tool_name_from_prompt(prompt, fallback=fallback_name)
        if not _include_local_tool_prompt(agent, tool_name):
            continue
        result.append((tool_name, prompt))
    return result


def _include_local_tool_prompt(agent: Any, tool_name: str) -> bool:
    try:
        from plugins._a0_connector.helpers.remote_tool_prompts import (
            should_include_remote_tool_prompt,
        )
    except Exception:
        return True

    return should_include_remote_tool_prompt(agent, tool_name)


def _mcp_tools(agent: Any) -> list[tuple[str, dict[str, Any]]]:
    try:
        import helpers.mcp_handler as mcp_helper

        raw_tools = mcp_helper.MCPConfig.get_instance().get_tools()
    except Exception:
        return []

    result: list[tuple[str, dict[str, Any]]] = []
    for entry in raw_tools or []:
        if not isinstance(entry, dict):
            continue
        for tool_name, tool in entry.items():
            if isinstance(tool, dict):
                result.append((str(tool_name), tool))
    return result


def _tool_name_from_prompt_basename(basename: str) -> str:
    if not basename.startswith(TOOL_PROMPT_PREFIX) or not basename.endswith(TOOL_PROMPT_SUFFIX):
        return ""
    name = basename[len(TOOL_PROMPT_PREFIX) : -len(TOOL_PROMPT_SUFFIX)]
    if not name or name in {"tools", "tools_vision"}:
        return ""
    return name


def _tool_name_from_prompt(prompt: str, *, fallback: str) -> str:
    for match in TOOL_NAME_EXAMPLE_PATTERN.finditer(prompt or ""):
        name = match.group(1).strip()
        if FUNCTION_NAME_PATTERN.fullmatch(name):
            return name

    for match in TOOL_HEADING_PATTERN.finditer(prompt or ""):
        name = _tool_name_from_heading(match.group(1))
        if name:
            return name

    return fallback


def _tool_name_from_heading(heading: str) -> str:
    token = (heading or "").strip().split(None, 1)[0] if heading else ""
    name = token.strip("`'\" :")
    if FUNCTION_NAME_PATTERN.fullmatch(name):
        return name
    return ""


def _native_tool_name(tool_name: str) -> str:
    if FUNCTION_NAME_PATTERN.fullmatch(tool_name):
        return tool_name
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", tool_name).strip("_")
    digest = hashlib.sha1(tool_name.encode("utf-8")).hexdigest()[:8]
    native = f"{slug[:52]}_{digest}" if slug else f"a0_tool_{digest}"
    return native[:64]


def _description_from_prompt(prompt: str, *, fallback: str) -> str:
    lines: list[str] = []
    in_fence = False
    for raw_line in (prompt or "").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if line.lower() == fallback.lower():
                continue
        lines.append(line)
        if sum(len(part) for part in lines) >= MAX_TOOL_DESCRIPTION_CHARS:
            break
    description = " ".join(lines).strip() or fallback
    return _truncate(description)


def _schema_from_prompt(prompt: str) -> dict[str, Any]:
    schema = _schema_from_embedded_json(prompt)
    if schema:
        return schema
    schema = _schema_from_args_line(prompt)
    if schema.get("properties"):
        return schema
    # Some prompts never declare an "args:" line and document the call shape
    # only through their worked example - the response tool describes its
    # argument in prose ("put result in text arg") but shows
    # "tool_args": {"text": ...} underneath. The example is the calling
    # contract the model is being shown, so it is a sound last resort.
    return _schema_from_usage_example(prompt) or schema


def _schema_from_usage_example(prompt: str) -> dict[str, Any]:
    """Extract argument names from a prompt's "tool_args" worked example.

    Parsed with brace matching rather than json.loads: these examples are
    illustrative and frequently contain trailing commas or "..." elisions
    that are not valid JSON. Only keys at the top level of the tool_args
    object are taken, so nested example values contribute nothing.
    """
    marker = re.search(r'"tool_args"\s*:\s*\{', prompt or "")
    if not marker:
        return {}

    start = marker.end()
    depth = 1
    for index in range(start, len(prompt)):
        char = prompt[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
    else:
        return {}

    body = prompt[start:index]
    properties: dict[str, Any] = {}
    depth = 0
    for match in re.finditer(r'[{}\[\]]|"([A-Za-z_][A-Za-z0-9_-]*)"\s*:', body):
        token = match.group(0)
        if token in "{[":
            depth += 1
        elif token in "}]":
            depth -= 1
        elif depth == 0 and match.group(1):
            properties.setdefault(match.group(1), {"type": "string"})

    if not properties:
        return {}
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


def _schema_from_embedded_json(prompt: str) -> dict[str, Any]:
    marker = "Input schema for tool_args:"
    index = (prompt or "").find(marker)
    if index == -1:
        return {}
    tail = prompt[index + len(marker) :].strip()
    match = re.search(r"\{(?:[^{}]|(?R))*\}", tail, flags=re.DOTALL) if hasattr(re, "VERSION1") else None
    candidate = match.group(0) if match else _balanced_json_object(tail)
    if not candidate:
        return {}
    try:
        return _schema_from_any(json.loads(candidate))
    except Exception:
        return {}


# Tool prompts declare arguments on a line like:
#   arg: `query` (keyword-based text search query)
#   args: `message`, optional `profile`, `reset`
#   Args: `tool_calls`, `job_ids`, `wait` default `true`
# The singular "arg:" and capitalised "Args:" forms are both in active use,
# so this is anchored at line start and case-insensitive rather than doing a
# substring test for "args:" - that older test missed every singular "arg:"
# prompt (search_engine and behaviour), which then fell through to the fully
# permissive schema. A tool advertised with `properties: {}` is telling the
# model, formally, that it takes no arguments at all - observed live as
# repeated `{"tool_name": "search_engine", "tool_args": {}}` calls.
# A leading qualifier is common too ("Common args: `action`, `name`, ..."),
# so one optional word is allowed before the keyword.
_ARGS_LINE_PATTERN = re.compile(
    r"^(?:[A-Za-z]+\s+)?(?:arg|args|argument|arguments)\s*:", re.IGNORECASE
)
_ARG_NAME_PATTERN = re.compile(r"`([A-Za-z_][A-Za-z0-9_-]*)`")
# Markers that make the argument(s) in their comma-segment optional.
_OPTIONAL_SEGMENT_MARKERS = ("optional", "default")


# A bare argument name, for prompts that list them without backticks.
_BARE_ARG_NAME = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)
# Words that appear in prose after "args:" and are not argument names. Without
# this, a sentence like "args: see the table below" would become properties.
_PROSE_WORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "below", "but", "by",
    "can", "each", "for", "from", "if", "in", "is", "it", "its", "must", "no",
    "none", "not", "of", "on", "one", "only", "or", "see", "should", "so",
    "some", "such", "than", "that", "the", "them", "then", "these", "this",
    "to", "up", "use", "used", "when", "where", "which", "with", "you", "your",
}


def _collect_bulleted_args(
    lines: list[str], index: int, properties: dict[str, Any]
) -> None:
    """Read "- `name`: description" bullets following a bare "args:" line.

    Only the first backticked token on each bullet is the argument name; the
    rest are example values ("- `runtime`: `terminal`, `python`, `nodejs`"),
    and capturing those would advertise "terminal" as an argument.

    Nothing is marked required. Prompts in this form signal optionality
    inconsistently - code_execution_tool marks `cwd` "optional" and `session`
    with a "default", but leaves `reset` unmarked despite it being optional -
    and over-marking is the damaging direction, since a schema-enforcing
    provider would reject the call or make the model invent a value.
    """
    for follow in lines[index + 1 :]:
        stripped = follow.strip()
        if not stripped.startswith(("-", "*")):
            break
        match = _ARG_NAME_PATTERN.search(stripped)
        if match:
            properties.setdefault(match.group(1), {"type": "string"})


def _collect_bare_args(normalized: str, properties: dict[str, Any]) -> None:
    """Handle "common args: action path" - names written without backticks.

    Accepted only when every remaining token is a short identifier and none
    is a common English word, so prose following "args:" cannot be mistaken
    for a list of argument names. Like the bulleted form, this yields
    properties only and never marks anything required.
    """
    if ":" not in normalized:
        return
    tokens = normalized.split(":", 1)[1].replace(",", " ").split()
    if not 1 <= len(tokens) <= 8:
        return
    if not all(_BARE_ARG_NAME.match(token) for token in tokens):
        return
    if any(token.lower() in _PROSE_WORDS for token in tokens):
        return
    for token in tokens:
        properties.setdefault(token, {"type": "string"})


def _schema_from_args_line(prompt: str) -> dict[str, Any]:
    """Derive {properties, required} from a tool prompt's argument line.

    Required-detection is deliberately conservative: a name counts as
    required only when nothing in its own comma-separated segment marks it
    optional, and the line doesn't say "any of" (which means no single
    argument is individually mandatory - e.g. the wait tool). Marking a
    genuinely-optional argument as required is the damaging direction,
    since schema-enforcing providers would then reject or fabricate it;
    under-marking merely preserves the previous behaviour.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    lines = (prompt or "").splitlines()

    for index, line in enumerate(lines):
        normalized = line.strip()
        if not _ARGS_LINE_PATTERN.match(normalized):
            continue

        # Not every prompt names its arguments on the "args:" line itself.
        # code_execution_tool announces "args:" and lists them as bullets
        # underneath; text_editor writes "common args: action path" with no
        # backticks at all. Both previously fell through to the permissive
        # schema, which is what told the model - formally - that
        # code_execution_tool takes no arguments.
        if not _ARG_NAME_PATTERN.search(normalized):
            _collect_bulleted_args(lines, index, properties)
            _collect_bare_args(normalized, properties)
            continue

        lowered = normalized.lower()

        # Lines describing a subset ("any of `a`, `b`") or carrying inline
        # defaults ("`wait` default `true`") describe conditional or
        # mode-dependent signatures - the parallel tool's arguments depend on
        # its action, for example. Deriving "required" from those reliably
        # isn't possible from prose, so nothing is marked required and the
        # previous (permissive) behaviour is preserved for them.
        # A qualifier ("Common args: ...") means a shared pool spanning several
        # actions rather than a per-call signature - the scheduler tool's
        # arguments vary by action, so none of them is universally required.
        qualified = bool(re.match(r"^[A-Za-z]+\s+", normalized))
        derive_required = (
            not qualified and "any of" not in lowered and "default" not in lowered
        )

        # Everything from the first "optional" onward is optional; prompts use
        # it as a divider ("args: `message`, optional `profile`, `reset`")
        # rather than repeating it per argument.
        optional_at = lowered.find("optional")
        cut = optional_at if optional_at != -1 else len(normalized)

        for match in _ARG_NAME_PATTERN.finditer(normalized):
            name = match.group(1)
            # A backticked token after "default" in the same segment is a
            # default *value* (`true`), not an argument name.
            segment_start = normalized.rfind(",", 0, match.start()) + 1
            if "default" in normalized[segment_start : match.start()].lower():
                continue
            properties.setdefault(name, {"type": "string"})
            if derive_required and match.start() < cut and name not in required:
                required.append(name)

    if properties:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            # Kept permissive: tools accept undocumented extras (e.g. action
            # variants), and rejecting them would break working calls.
            "additionalProperties": True,
        }
        if required:
            schema["required"] = required
        return schema
    return _permissive_schema()


def _schema_from_any(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict):
        normalized = dict(schema)
        normalized.setdefault("type", "object")
        if normalized.get("type") == "object" and not isinstance(
            normalized.get("properties"), dict
        ):
            normalized["properties"] = {}
        normalized.setdefault("additionalProperties", True)
        return normalized
    return _permissive_schema()


def _permissive_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": True}


def _balanced_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _dedupe_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(tool)
    return result


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_DESCRIPTION_CHARS:
        return text
    return text[: MAX_TOOL_DESCRIPTION_CHARS - 3].rstrip() + "..."
