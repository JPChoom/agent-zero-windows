"""Tests for the permission decision engine.

The engine decides whether every tool call proceeds, so the properties
worth pinning are the ones where a wrong answer is silent: a deny that
stops binding, a mode whose guarantee can be undone by a rule, or a
pattern that quietly matches nothing.
"""

from __future__ import annotations

import pytest

from plugins._permissions.helpers import rules as r


def _rs(**kw):
    return r.Ruleset.from_config(kw)


# ------------------------------------------------------------------
# Rule parsing
# ------------------------------------------------------------------

def test_bare_tool_name_matches_every_call():
    rule = r.Rule.parse("desktop_control")
    assert rule.tool == "desktop_control" and rule.pattern is None
    assert rule.matches("desktop_control", "anything")
    assert not rule.matches("text_editor", "anything")


def test_pattern_restricts_to_matching_calls():
    rule = r.Rule.parse("code_execution_tool(git status*)")
    assert rule.matches("code_execution_tool", "git status --short")
    assert not rule.matches("code_execution_tool", "rm -rf /")


def test_wildcards_work_in_the_tool_position():
    assert r.Rule.parse("*").matches("anything", "x")
    assert r.Rule.parse("*(*)").matches("anything", "x")


def test_matching_is_case_insensitive():
    """Commands and paths are typed by hand; a rule that fails on
    capitalisation is a rule that quietly does nothing."""
    assert r.Rule.parse("code_execution_tool(GIT STATUS*)").matches(
        "code_execution_tool", "git status"
    )


def test_patterns_containing_parentheses_survive_parsing():
    rule = r.Rule.parse("code_execution_tool(echo (hi))")
    assert rule.pattern == "echo (hi)"


@pytest.mark.parametrize("bad", ["", "   ", "()"])
def test_unparseable_rules_raise(bad):
    with pytest.raises(r.RuleError):
        r.Rule.parse(bad)


def test_malformed_rules_are_dropped_not_fatal():
    """One bad line in a config must not disable the whole gate."""
    ruleset = _rs(deny=["", "!!!nonsense((", "code_execution_tool(rm*)"])
    assert len(ruleset.deny) == 1
    assert ruleset.deny[0].tool == "code_execution_tool"


def test_rules_accept_both_lists_and_newline_text():
    from_list = _rs(allow=["a", "b"])
    from_text = _rs(allow="a\nb\n\n")
    assert [x.source for x in from_list.allow] == [x.source for x in from_text.allow]


# ------------------------------------------------------------------
# Precedence
# ------------------------------------------------------------------

def test_deny_outranks_ask_and_allow():
    ruleset = _rs(
        deny=["code_execution_tool(*rm -rf*)"],
        ask=["code_execution_tool"],
        allow=["code_execution_tool"],
    )
    assert r.decide("code_execution_tool", {"code": "rm -rf /"}, "auto", ruleset).decision == "deny"


def test_ask_outranks_allow():
    ruleset = _rs(ask=["code_execution_tool(npm*)"], allow=["code_execution_tool"])
    assert r.decide("code_execution_tool", {"code": "npm i"}, "auto", ruleset).decision == "ask"


def test_rules_outrank_the_mode():
    """A manual-mode user who allow-listed something should not be asked."""
    ruleset = _rs(allow=["code_execution_tool(git status*)"])
    assert r.decide(
        "code_execution_tool", {"code": "git status"}, "manual", ruleset
    ).decision == "allow"


def test_verdict_explains_itself():
    ruleset = _rs(deny=["desktop_control"])
    verdict = r.decide("desktop_control", {"action": "click"}, "auto", ruleset)
    assert "desktop_control" in verdict.reason and verdict.matched == "desktop_control"


# ------------------------------------------------------------------
# Effect classification
# ------------------------------------------------------------------

def test_unknown_tools_count_as_executing():
    """Over-guarding a new read-only tool is recoverable; under-guarding a
    new destructive one is not."""
    assert r.classify("some_brand_new_tool", {}) == "execute"


def test_read_actions_downgrade_an_editing_tool():
    assert r.classify("text_editor", {"action": "read"}) == "read"
    assert r.classify("text_editor", {"action": "write"}) == "edit"


def test_read_only_tools_are_reads():
    assert r.classify("search_engine", {"query": "x"}) == "read"
    assert r.classify("desktop_screenshot", {}) == "read"


# ------------------------------------------------------------------
# Mode behaviour
# ------------------------------------------------------------------

@pytest.mark.parametrize("mode", r.MODES)
def test_reads_are_never_blocked_by_any_mode(mode):
    """No mode should stop the agent looking at things; that would make
    plan mode in particular useless."""
    assert r.decide("search_engine", {"query": "x"}, mode).decision == "allow"


def test_manual_asks_before_edits_and_commands():
    assert r.decide("text_editor", {"action": "write"}, "manual").decision == "ask"
    assert r.decide("code_execution_tool", {"code": "ls"}, "manual").decision == "ask"


def test_accept_edits_allows_files_but_still_asks_to_execute():
    assert r.decide("text_editor", {"action": "write"}, "accept_edits").decision == "allow"
    assert r.decide("code_execution_tool", {"code": "ls"}, "accept_edits").decision == "ask"


def test_plan_refuses_rather_than_asking():
    """Prompting would defeat the mode: the point is to produce a plan, and
    an approvable prompt just relocates the decision."""
    assert r.decide("text_editor", {"action": "write"}, "plan").decision == "deny"
    assert r.decide("code_execution_tool", {"code": "ls"}, "plan").decision == "deny"


def test_auto_is_permissive_but_still_rule_governed():
    assert r.decide("code_execution_tool", {"code": "ls"}, "auto").decision == "allow"
    ruleset = _rs(deny=["code_execution_tool(*curl*)"])
    assert r.decide(
        "code_execution_tool", {"code": "curl x"}, "auto", ruleset
    ).decision == "deny"


def test_unknown_mode_falls_back_to_the_default():
    assert r.decide("code_execution_tool", {"code": "ls"}, "nonsense").decision == (
        r.decide("code_execution_tool", {"code": "ls"}, r.DEFAULT_MODE).decision
    )


# ------------------------------------------------------------------
# Mode guarantees that rules must not undo
# ------------------------------------------------------------------

def test_bypass_turns_an_ask_rule_into_an_allow():
    """"Accepts all permissions" must not still produce prompts."""
    ruleset = _rs(ask=["desktop_control"])
    verdict = r.decide("desktop_control", {"action": "click"}, "bypass", ruleset)
    assert verdict.decision == "allow"
    assert "bypass" in verdict.reason


def test_bypass_still_honours_an_explicit_deny():
    """A prohibition the user wrote should survive a mode change; only the
    prompting is bypassed, not their stated intent."""
    ruleset = _rs(deny=["code_execution_tool(*rm -rf*)"])
    assert r.decide(
        "code_execution_tool", {"code": "rm -rf /"}, "bypass", ruleset
    ).decision == "deny"


def test_plan_mode_is_not_unlocked_by_an_allow_rule():
    """Otherwise a broad allow silently converts plan mode back into auto."""
    ruleset = _rs(allow=["text_editor(*)", "code_execution_tool(*)"])
    assert r.decide("text_editor", {"action": "write"}, "plan", ruleset).decision == "deny"
    assert r.decide("code_execution_tool", {"code": "ls"}, "plan", ruleset).decision == "deny"


def test_plan_mode_still_allows_reads_that_rules_permit():
    ruleset = _rs(allow=["text_editor(*)"])
    assert r.decide("text_editor", {"action": "read"}, "plan", ruleset).decision == "allow"


# ------------------------------------------------------------------
# Target text and rule suggestion
# ------------------------------------------------------------------

def test_target_uses_the_identifying_argument():
    assert r.target_text("code_execution_tool", {"runtime": "terminal", "code": "ls -la"}) == "ls -la"
    assert r.target_text("text_editor", {"action": "write", "path": "a.py"}) == "write:a.py"


def test_target_falls_back_to_serialised_args():
    text = r.target_text("unknown_tool", {"b": 2, "a": 1})
    assert '"a": 1' in text and '"b": 2' in text


def test_target_of_an_argument_less_call_is_empty():
    assert r.target_text("desktop_screenshot", {}) == ""


def test_suggested_rule_round_trips_into_a_matching_rule():
    """The "always allow" affordance depends on this: the rule it offers
    must actually match the call it came from."""
    args = {"runtime": "terminal", "code": "git status"}
    suggestion = r.rule_for("code_execution_tool", args)
    assert r.Rule.parse(suggestion).matches("code_execution_tool", r.target_text("code_execution_tool", args))


def test_tool_scoped_suggestion_covers_the_whole_tool():
    rule = r.Rule.parse(r.rule_for("desktop_control", {"action": "click"}, scope="tool"))
    assert rule.matches("desktop_control", "anything at all")
