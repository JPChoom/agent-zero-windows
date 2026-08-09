"""Tests for the independent diff reviewer: git_state.py's git wrappers,
and reviewer.py's packet building, response parsing, and (lightly mocked)
sub-agent spawn wiring.
"""

import subprocess

import pytest

from plugins._coding_controller.helpers import git_state, reviewer


# ------------------------------------------------------------------
# git_state - uses a real git repo in tmp_path (git is a hard dependency
# of this repo's own workflow, safe to assume present in this environment)
# ------------------------------------------------------------------

def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_is_git_repo_true_for_real_repo(tmp_path):
    _init_repo(tmp_path)

    assert await git_state.is_git_repo(str(tmp_path)) is True


@pytest.mark.asyncio
async def test_is_git_repo_false_for_non_repo(tmp_path):
    assert await git_state.is_git_repo(str(tmp_path)) is False


@pytest.mark.asyncio
async def test_get_git_status_and_changed_files_for_new_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "new.txt").write_text("hello", encoding="utf-8")

    status = await git_state.get_git_status(str(tmp_path))
    changed = await git_state.get_changed_files(str(tmp_path))

    assert "new.txt" in status
    assert "new.txt" in changed


@pytest.mark.asyncio
async def test_get_git_diff_shows_modification(tmp_path):
    _init_repo(tmp_path)
    target = tmp_path / "tracked.txt"
    target.write_text("line one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)

    target.write_text("line one\nline two\n", encoding="utf-8")

    diff = await git_state.get_git_diff(str(tmp_path))

    assert "line two" in diff


@pytest.mark.asyncio
async def test_get_git_diff_scoped_to_one_path(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)

    (tmp_path / "a.txt").write_text("a changed\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b changed\n", encoding="utf-8")

    diff_a = await git_state.get_git_diff(str(tmp_path), path="a.txt")

    assert "a changed" in diff_a
    assert "b changed" not in diff_a


@pytest.mark.asyncio
async def test_git_helpers_degrade_gracefully_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(git_state, "find_git", lambda: "")

    assert await git_state.get_git_status(str(tmp_path)) == ""
    assert await git_state.get_git_diff(str(tmp_path)) == ""
    assert await git_state.get_changed_files(str(tmp_path)) == []
    assert await git_state.is_git_repo(str(tmp_path)) is False


# ------------------------------------------------------------------
# reviewer.build_review_packet
# ------------------------------------------------------------------

def test_build_review_packet_includes_all_sections():
    packet = reviewer.build_review_packet(
        original_request="Add input validation",
        acceptance_criteria=["Empty names rejected", "Valid names still save"],
        changed_files=["ViewModels/MainViewModel.cs"],
        diff="--- a/x\n+++ b/x\n+ validated",
        baseline_summary="2 pre-existing test failures",
        gate_evidence="build: passed\ntest: passed",
        project_instructions="Use the existing validation pattern.",
        project_root=r"C:\Projects\ExampleApp",
    )

    assert "Add input validation" in packet
    assert "Empty names rejected" in packet
    assert "ViewModels/MainViewModel.cs" in packet
    assert "validated" in packet
    assert "2 pre-existing test failures" in packet
    assert "build: passed" in packet
    assert "existing validation pattern" in packet
    assert r"C:\Projects\ExampleApp" in packet


def test_build_review_packet_handles_missing_optional_fields():
    packet = reviewer.build_review_packet(
        original_request="",
        acceptance_criteria=[],
        changed_files=[],
        diff="",
        baseline_summary="",
        gate_evidence="",
        project_instructions="",
        project_root="C:\\proj",
    )

    assert "(not provided)" in packet
    assert "(none listed)" in packet


# ------------------------------------------------------------------
# reviewer.parse_review_response
# ------------------------------------------------------------------

def test_parse_review_response_approve_no_findings():
    text = "Looks good.\n\n<review_decision>APPROVE</review_decision>\n<review_findings>\n[]\n</review_findings>"

    result = reviewer.parse_review_response(text)

    assert result.decision == "APPROVE"
    assert result.findings == []
    assert result.parse_error == ""


def test_parse_review_response_changes_required_with_blocking_finding():
    text = """
    <review_decision>CHANGES_REQUIRED</review_decision>
    <review_findings>
    [
      {"severity": "high", "category": "correctness", "file": "x.cs", "line": 42,
       "finding": "bug", "impact": "breaks feature", "evidence": "see line 42",
       "recommended_action": "fix it", "blocking": true}
    ]
    </review_findings>
    """

    result = reviewer.parse_review_response(text)

    assert result.decision == "CHANGES_REQUIRED"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "high"
    assert finding.file == "x.cs"
    assert finding.line == 42
    assert finding.blocking is True
    assert result.has_blocking_findings is True


def test_parse_review_response_multiple_findings_mixed_blocking():
    text = """
    <review_decision>APPROVE_WITH_NOTES</review_decision>
    <review_findings>
    [
      {"severity": "low", "category": "style", "file": "a.cs", "finding": "minor", "blocking": false},
      {"severity": "medium", "category": "correctness", "file": "b.cs", "finding": "edge case", "blocking": false}
    ]
    </review_findings>
    """

    result = reviewer.parse_review_response(text)

    assert result.decision == "APPROVE_WITH_NOTES"
    assert len(result.findings) == 2
    assert result.has_blocking_findings is False


def test_parse_review_response_missing_decision_tag_is_unable_to_verify():
    text = "I reviewed the code but forgot the format.\n<review_findings>[]</review_findings>"

    result = reviewer.parse_review_response(text)

    assert result.decision == "UNABLE_TO_VERIFY"
    assert "review_decision" in result.parse_error


def test_parse_review_response_invalid_decision_value_is_unable_to_verify():
    text = "<review_decision>MAYBE</review_decision>\n<review_findings>[]</review_findings>"

    result = reviewer.parse_review_response(text)

    assert result.decision == "UNABLE_TO_VERIFY"


def test_parse_review_response_missing_findings_tag_is_unable_to_verify():
    text = "<review_decision>APPROVE</review_decision>"

    result = reviewer.parse_review_response(text)

    assert result.decision == "UNABLE_TO_VERIFY"
    assert "review_findings" in result.parse_error


def test_parse_review_response_malformed_json_is_unable_to_verify():
    text = "<review_decision>APPROVE</review_decision>\n<review_findings>\nnot json\n</review_findings>"

    result = reviewer.parse_review_response(text)

    assert result.decision == "UNABLE_TO_VERIFY"
    assert "not valid JSON" in result.parse_error


def test_parse_review_response_findings_must_be_a_list():
    text = (
        "<review_decision>APPROVE</review_decision>\n"
        '<review_findings>\n{"not": "a list"}\n</review_findings>'
    )

    result = reviewer.parse_review_response(text)

    assert result.decision == "UNABLE_TO_VERIFY"


def test_parse_review_response_unknown_severity_falls_back_to_informational():
    text = (
        "<review_decision>APPROVE_WITH_NOTES</review_decision>\n"
        '<review_findings>\n[{"severity": "extreme", "file": "x", "finding": "y"}]\n</review_findings>'
    )

    result = reviewer.parse_review_response(text)

    assert result.findings[0].severity == "informational"


def test_parse_review_response_missing_line_is_none():
    text = (
        "<review_decision>APPROVE_WITH_NOTES</review_decision>\n"
        '<review_findings>\n[{"severity": "low", "file": "x", "finding": "y"}]\n</review_findings>'
    )

    result = reviewer.parse_review_response(text)

    assert result.findings[0].line is None


def test_parse_review_response_non_dict_finding_entries_are_skipped():
    text = (
        "<review_decision>APPROVE_WITH_NOTES</review_decision>\n"
        '<review_findings>\n["not a dict", {"severity": "low", "file": "x", "finding": "y"}]\n</review_findings>'
    )

    result = reviewer.parse_review_response(text)

    assert len(result.findings) == 1


# ------------------------------------------------------------------
# reviewer.run_review - spawn wiring, with a lightweight fake Agent
# (deep-mocking the real Agent class would be brittle; the happy path
# through a real reviewer sub-agent is covered by live verification
# instead, per this task's plan)
# ------------------------------------------------------------------

class _FakeReviewerAgent:
    """Stands in for agent.Agent - only implements what run_review touches."""

    DATA_NAME_SUPERIOR = "_superior"
    last_instance = None

    def __init__(self, number, config, context):
        self.number = number
        self.config = config
        self.context = context
        self.data = {}
        self.user_messages = []
        type(self).last_instance = self

    def set_data(self, key, value):
        self.data[key] = value

    def hist_add_user_message(self, message):
        self.user_messages.append(message)

    async def monologue(self):
        return (
            "<review_decision>APPROVE</review_decision>\n"
            "<review_findings>\n[]\n</review_findings>"
        )


class _FakeParentAgent:
    number = 0
    context = "fake-context"


@pytest.mark.asyncio
async def test_run_review_spawns_agent_and_parses_result(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    monkeypatch.setattr(agent_module, "Agent", _FakeReviewerAgent)
    monkeypatch.setattr(initialize_module, "initialize_agent", lambda **kwargs: "fake-config")

    parent = _FakeParentAgent()
    result = await reviewer.run_review(parent, "packet text")

    assert result.decision == "APPROVE"
    assert result.parse_error == ""
    spawned = _FakeReviewerAgent.last_instance
    assert spawned is not None
    assert spawned.number == parent.number + 1
    assert spawned.user_messages[0].message == "packet text"


@pytest.mark.asyncio
async def test_run_review_uses_reviewer_profile(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    captured = {}

    def _fake_initialize_agent(**kwargs):
        captured.update(kwargs)
        return "fake-config"

    monkeypatch.setattr(agent_module, "Agent", _FakeReviewerAgent)
    monkeypatch.setattr(initialize_module, "initialize_agent", _fake_initialize_agent)

    result = await reviewer.run_review(_FakeParentAgent(), "packet text")

    assert captured["override_settings"]["agent_profile"] == reviewer.REVIEWER_PROFILE
    assert result.decision == "APPROVE"  # confirms the whole spawn succeeded, not just initialize_agent


@pytest.mark.asyncio
async def test_run_review_spawn_failure_is_unable_to_verify_not_raised(monkeypatch):
    import initialize as initialize_module

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(initialize_module, "initialize_agent", _raise)

    result = await reviewer.run_review(_FakeParentAgent(), "packet text")

    assert result.decision == "UNABLE_TO_VERIFY"
    assert "boom" in result.parse_error


class _FakeReviewerAgentMissingTagsThenFixes:
    """First monologue() call replies with no tags (observed live against a
    real local model); second call (after the retry nudge) replies correctly.
    """

    DATA_NAME_SUPERIOR = "_superior"
    last_instance = None

    def __init__(self, number, config, context):
        self.number = number
        self.data = {}
        self.user_messages = []
        self._calls = 0
        type(self).last_instance = self

    def set_data(self, key, value):
        self.data[key] = value

    def hist_add_user_message(self, message):
        self.user_messages.append(message)

    async def monologue(self):
        self._calls += 1
        if self._calls == 1:
            return "This looks fine, no issues found."
        return (
            "<review_decision>APPROVE</review_decision>\n"
            "<review_findings>\n[]\n</review_findings>"
        )


class _FakeReviewerAgentAlwaysMissingTags(_FakeReviewerAgentMissingTagsThenFixes):
    async def monologue(self):
        self._calls += 1
        return "This looks fine, no issues found."


@pytest.mark.asyncio
async def test_run_review_retries_once_when_tags_missing(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    monkeypatch.setattr(agent_module, "Agent", _FakeReviewerAgentMissingTagsThenFixes)
    monkeypatch.setattr(initialize_module, "initialize_agent", lambda **kwargs: "fake-config")

    result = await reviewer.run_review(_FakeParentAgent(), "packet text")

    assert result.decision == "APPROVE"
    spawned = _FakeReviewerAgentMissingTagsThenFixes.last_instance
    assert spawned._calls == 2
    assert len(spawned.user_messages) == 2  # original packet + retry nudge


@pytest.mark.asyncio
async def test_run_review_gives_up_as_unable_to_verify_after_one_retry(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    monkeypatch.setattr(agent_module, "Agent", _FakeReviewerAgentAlwaysMissingTags)
    monkeypatch.setattr(initialize_module, "initialize_agent", lambda **kwargs: "fake-config")

    result = await reviewer.run_review(_FakeParentAgent(), "packet text")

    assert result.decision == "UNABLE_TO_VERIFY"
    spawned = _FakeReviewerAgentAlwaysMissingTags.last_instance
    assert spawned._calls == 2  # exactly one retry, not an infinite loop
