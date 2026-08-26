"""Tests for helpers/responses_tools.py's argument-schema derivation.

Observed live: a chat repeatedly emitted
``{"tool_name": "search_engine", "tool_args": {}}`` - a search with no query -
until the loop-stall breaker ended the turn. The model wasn't misbehaving:
_schema_from_args_line only recognised an ``args:``/``argument:`` substring,
while search_engine's prompt declares ``arg: `query` `` (singular). The line
was skipped, the tool fell through to the fully permissive schema, and the
model was told - formally - that search_engine accepts no arguments at all.

Two properties matter here and are asserted below:

1. Argument names are actually discovered, across every declaration style in
   use (``arg:``, ``args:``, ``Args:``, ``Common args:``).
2. "required" is derived conservatively. Marking a genuinely-optional
   argument as required is the damaging direction - schema-enforcing
   providers would reject the call or make the model fabricate a value -
   whereas under-marking merely preserves the previous behaviour. Every
   ambiguous construction ("any of", inline "default", a qualifier such as
   "Common args") therefore yields no required list at all.
"""

from __future__ import annotations

from helpers import responses_tools as rt


def _schema(prompt: str) -> dict:
    return rt._schema_from_prompt(prompt)


# ------------------------------------------------------------------
# Discovery - the regression that caused the live failure
# ------------------------------------------------------------------

def test_singular_arg_line_is_recognised():
    """The exact shape of search_engine's prompt, which the old
    substring test for "args:" silently skipped."""
    schema = _schema("### search_engine\narg: `query` (keyword-based text search)\n")
    assert schema["properties"] == {"query": {"type": "string"}}
    assert schema["required"] == ["query"]


def test_plural_and_capitalised_forms_are_recognised():
    assert "message" in _schema("args: `message`")["properties"]
    assert "tool_calls" in _schema("Args: `tool_calls`")["properties"]
    assert "adjustments" in _schema("Argument: `adjustments`")["properties"]


def test_qualified_args_line_is_recognised():
    schema = _schema("Common args: `action`, `name`, `uuid`")
    assert set(schema["properties"]) == {"action", "name", "uuid"}


def test_prompt_without_any_args_line_stays_permissive():
    schema = _schema("### some_tool\ndoes a thing\n")
    assert schema == {"type": "object", "properties": {}, "additionalProperties": True}


def test_args_keyword_mid_sentence_is_not_treated_as_a_declaration():
    """Only a line that *starts* with the keyword declares arguments;
    prose merely mentioning it must not invent properties."""
    schema = _schema("pass the `query` to downstream args: whatever you like\n")
    assert schema["properties"] == {}


# ------------------------------------------------------------------
# required - conservative derivation
# ------------------------------------------------------------------

def test_optional_acts_as_a_divider_for_the_rest_of_the_line():
    """Prompts write "args: `a`, optional `b`, `c`" meaning both b and c are
    optional - "optional" is a divider, not a per-argument label."""
    schema = _schema("args: `message`, optional `profile`, `reset`")
    assert set(schema["properties"]) == {"message", "profile", "reset"}
    assert schema["required"] == ["message"]


def test_multiple_leading_args_are_all_required():
    schema = _schema("args: `agent_url`, `message`, optional `reset`")
    assert schema["required"] == ["agent_url", "message"]


def test_any_of_marks_nothing_required():
    """The wait tool: the caller supplies some subset, so no single
    argument is individually mandatory."""
    schema = _schema("args: any of `seconds`, `minutes`, `hours`, or `until`")
    assert set(schema["properties"]) >= {"seconds", "minutes", "hours", "until"}
    assert schema.get("required", []) == []


def test_inline_default_suppresses_required_for_the_whole_line():
    """A line carrying defaults describes a conditional/mode-dependent
    signature (the parallel tool), which prose can't be parsed into a
    reliable required list."""
    schema = _schema("Args: `tool_calls`, `job_ids`, `wait` default `true`, `action`")
    assert schema.get("required", []) == []


def test_default_value_is_not_captured_as_an_argument_name():
    schema = _schema("Args: `tool_calls`, `wait` default `true`")
    assert "true" not in schema["properties"]
    assert "wait" in schema["properties"]


def test_qualifier_suppresses_required():
    """"Common args" is a shared pool across actions, not a per-call
    signature - so names are discovered but none is required."""
    schema = _schema("Common args: `action`, `name`, `uuid`")
    assert schema.get("required", []) == []


def test_required_names_are_unique_and_ordered():
    schema = _schema("args: `a`, `b`\nargs: `a`, `c`")
    assert schema["required"] == ["a", "b", "c"]


def test_additional_properties_stays_permissive():
    """Tools accept undocumented extras (action variants); rejecting them
    would break working calls."""
    assert _schema("arg: `query`")["additionalProperties"] is True


# ------------------------------------------------------------------
# End to end against the real shipped prompts
# ------------------------------------------------------------------

def test_real_search_engine_prompt_requires_a_query():
    from helpers import files

    schema = _schema(files.read_file("prompts/agent.system.tool.search_engine.md"))
    assert schema["properties"].keys() == {"query"}
    assert schema["required"] == ["query"]


def test_no_shipped_prompt_over_marks_optional_arguments():
    """Guards the dangerous direction across every shipped tool: an
    argument introduced by "optional", or on a line using "any of" /
    "default" / a qualifier, must never end up in required."""
    import glob

    from helpers import files

    for path in glob.glob("prompts/agent.system.tool.*.md"):
        text = files.read_file(path)
        schema = _schema(text)
        required = schema.get("required", [])
        for line in text.splitlines():
            normalized = line.strip()
            if not rt._ARGS_LINE_PATTERN.match(normalized):
                continue
            lowered = normalized.lower()
            if "any of" in lowered or "default" in lowered:
                assert required == [], f"{path}: ambiguous line yielded {required}"
                continue
            cut = lowered.find("optional")
            if cut == -1:
                continue
            for match in rt._ARG_NAME_PATTERN.finditer(normalized):
                if match.start() > cut:
                    assert match.group(1) not in required, (
                        f"{path}: optional arg {match.group(1)!r} marked required"
                    )
