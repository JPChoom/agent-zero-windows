"""Tests for the _goal plugin port (from upstream agent0ai/agent-zero).

Ported essentially verbatim (see plugins/_goal/README.md) - these tests
verify the file-backed goal lifecycle and the goal_command.py script hook
work correctly in this fork, since the plugin's own logic has no OS or
Docker assumptions.
"""

import pytest

from plugins._goal.tools import goal


@pytest.fixture(autouse=True)
def _cleanup_test_goals():
    yield
    for context_id in ("test-goal-ctx", "test-goal-ctx-2"):
        try:
            goal.delete_goal(context_id)
        except FileNotFoundError:
            pass


# ------------------------------------------------------------------
# create_goal / get_goal / update_goal / delete_goal
# ------------------------------------------------------------------

def test_create_goal_and_get_goal_roundtrip():
    created = goal.create_goal("test-goal-ctx", "Ship the feature", created_by="user")
    assert created["status"] == "active"
    assert created["objective"] == "Ship the feature"

    fetched = goal.get_goal("test-goal-ctx")
    assert fetched is not None
    assert fetched["objective"] == "Ship the feature"


def test_create_goal_requires_nonempty_objective():
    with pytest.raises(ValueError):
        goal.create_goal("test-goal-ctx", "   ", created_by="user")


def test_update_goal_raises_when_no_goal_exists():
    with pytest.raises(FileNotFoundError):
        goal.update_goal("test-goal-ctx-2", status="complete")


def test_update_goal_to_complete_stops_elapsed_time_accrual():
    goal.create_goal("test-goal-ctx", "Ship the feature", created_by="user")
    updated = goal.update_goal("test-goal-ctx", status="complete")
    assert updated["status"] == "complete"
    assert updated["active_since"] == ""


def test_update_goal_reactivating_sets_active_since():
    goal.create_goal("test-goal-ctx", "Ship the feature", created_by="user")
    goal.update_goal("test-goal-ctx", status="complete")
    reactivated = goal.update_goal("test-goal-ctx", status="active")
    assert reactivated["status"] == "active"
    assert reactivated["active_since"]


def test_delete_goal_removes_it():
    goal.create_goal("test-goal-ctx", "Ship the feature", created_by="user")
    goal.delete_goal("test-goal-ctx")
    assert goal.get_goal("test-goal-ctx") is None


def test_get_goal_returns_none_for_missing_context():
    assert goal.get_goal("no-such-context-at-all") is None


def test_summarize_goal_handles_missing_goal():
    assert goal.summarize_goal(None) == "No goal is set for this chat."


def test_summarize_goal_includes_objective_and_status():
    current = goal.create_goal("test-goal-ctx", "Ship the feature", created_by="user")
    summary = goal.summarize_goal(current)
    assert "Ship the feature" in summary
    assert "Status: active" in summary


# ------------------------------------------------------------------
# goal_command.py script hook (invoked via _commands' resolve_message_command)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_goal_command_creates_goal_via_slash_command():
    from plugins._commands.helpers import commands as commands_helper

    resolution = await commands_helper.resolve_message_command(
        "/goal Ship the feature", context_id="test-goal-ctx"
    )
    assert resolution is not None
    effects = resolution["result"]["effects"]
    assert any(effect.get("type") == "goal_changed" for effect in effects)

    stored = goal.get_goal("test-goal-ctx")
    assert stored is not None
    assert stored["objective"] == "Ship the feature"


@pytest.mark.asyncio
async def test_goal_command_status_reports_no_goal_when_absent():
    from plugins._commands.helpers import commands as commands_helper

    resolution = await commands_helper.resolve_message_command(
        "/goal status", context_id="test-goal-ctx-2"
    )
    effects = resolution["result"]["effects"]
    assert effects[0]["type"] == "show_markdown"
    assert "No goal is set for this chat." in effects[0]["content"]
