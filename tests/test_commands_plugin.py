"""Tests for the _commands plugin port (from upstream agent0ai/agent-zero).

Not a port of upstream's own test suite (which assumes a Docker exec test
runner and heavier fixtures) - these are scoped to what actually matters
for this fork: the core parser/discovery logic works, the built-in command
pack resolves end-to-end, and the two fork-specific adaptations (no
api.stop.stop_context, no legacy-plugin migration) behave correctly.
"""

import asyncio

import pytest

from agent import AgentContext
from plugins._commands.helpers import commands as commands_helper


# ------------------------------------------------------------------
# sanitize_command_name / normalize_command_type
# ------------------------------------------------------------------

def test_sanitize_command_name_lowercases_and_hyphenates():
    assert commands_helper.sanitize_command_name("Explain Code") == "explain-code"


def test_sanitize_command_name_strips_invalid_chars():
    assert commands_helper.sanitize_command_name("  foo!!bar__baz  ") == "foo-bar__baz"


def test_sanitize_command_name_raises_on_empty():
    with pytest.raises(ValueError):
        commands_helper.sanitize_command_name("   ")


def test_normalize_command_type_defaults_to_text():
    assert commands_helper.normalize_command_type("") == "text"


def test_normalize_command_type_rejects_invalid():
    with pytest.raises(ValueError):
        commands_helper.normalize_command_type("shell")


# ------------------------------------------------------------------
# parse_slash_invocation / parse_arguments
# ------------------------------------------------------------------

def test_parse_slash_invocation_prefix_form():
    result = commands_helper.parse_slash_invocation("/scan --git-url https://example.com/repo")
    assert result["command_name"] == "scan"
    assert result["raw_arguments"] == "--git-url https://example.com/repo"
    assert result["arguments"]["flags"]["git_url"] == "https://example.com/repo"


def test_parse_slash_invocation_postfix_form():
    result = commands_helper.parse_slash_invocation("do the thing /nudge")
    assert result["command_name"] == "nudge"
    assert result["raw_arguments"] == "do the thing"


def test_parse_arguments_short_flag_bundle():
    parsed = commands_helper.parse_arguments("-vq positional")
    assert parsed["flags"]["v"] is True
    assert parsed["flags"]["q"] is True
    assert parsed["positional"] == ["positional"]


# ------------------------------------------------------------------
# render_text_template
# ------------------------------------------------------------------

def test_render_text_template_substitutes_placeholders():
    rendered = commands_helper.render_command_body(
        "Repo: {args.flags.git_url}\n\n{raw}",
        "--git-url https://example.com/repo",
    )
    assert "Repo: https://example.com/repo" in rendered


def test_render_text_template_appends_raw_when_unreferenced():
    rendered = commands_helper.render_command_body("Static text.", "hello world")
    assert "Static text." in rendered
    assert "Arguments:\nhello world" in rendered


# ------------------------------------------------------------------
# Built-in command discovery (this fork's actual 22 bundled commands)
# ------------------------------------------------------------------

def test_list_builtin_commands_discovers_all_bundled_commands():
    names = {command["name"] for command in commands_helper.list_builtin_commands()}
    expected = {
        "attach", "browser", "chat", "chats", "clear", "compact",
        "computer-use", "copy", "models", "new", "nudge", "pause",
        "plugins", "presets", "profile", "project", "queue", "quit",
        "resume", "send", "status", "stop",
    }
    assert expected <= names


def test_list_effective_commands_includes_goal_plugin_command():
    names = {command["name"] for command in commands_helper.list_effective_commands("")[0]}
    assert "goal" in names, "expected _goal's plugin-contributed /goal command to be discovered"


# ------------------------------------------------------------------
# End-to-end resolution against real built-in script commands
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_status_command_reports_no_context_when_missing():
    resolution = await commands_helper.resolve_message_command("/status", context_id="")
    effects = resolution["result"]["effects"]
    assert effects[0]["type"] == "show_markdown"
    assert "Open or create a chat context first." in effects[0]["content"]


@pytest.mark.asyncio
async def test_resolve_unknown_command_returns_none():
    resolution = await commands_helper.resolve_message_command("/this-does-not-exist")
    assert resolution is None


# ------------------------------------------------------------------
# Fork adaptation: /stop uses AgentContext.kill_process(), not the
# nonexistent api.stop.stop_context this fork doesn't have.
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_command_reports_no_active_run_when_idle():
    import initialize

    config = initialize.initialize_agent()
    context = AgentContext(config=config)
    try:
        resolution = await commands_helper.resolve_message_command("/stop", context_id=context.id)
        effects = resolution["result"]["effects"]
        assert effects[0]["type"] == "toast"
        assert "No active agent run to stop." in effects[0]["message"]
    finally:
        AgentContext.remove(context.id)


@pytest.mark.asyncio
async def test_stop_command_kills_running_task(monkeypatch):
    import initialize

    config = initialize.initialize_agent()
    context = AgentContext(config=config)
    killed = {"called": False}

    monkeypatch.setattr(context, "is_running", lambda: True)
    monkeypatch.setattr(context, "kill_process", lambda: killed.__setitem__("called", True))

    try:
        resolution = await commands_helper.resolve_message_command("/stop", context_id=context.id)
        effects = resolution["result"]["effects"]
        assert killed["called"] is True
        assert "Agent run stopped." in effects[0]["message"]
    finally:
        AgentContext.remove(context.id)
