"""Tests for coding_agent_manager.py's spawn/send/terminate wrapper and
diagnostician.py's packet building + spawn wiring (Phase B of the hand-off
roadmap). Reviewer.py's own tests (test_coding_controller_reviewer.py)
cover the same spawn pattern via reviewer.run_review, now itself
refactored to go through coding_agent_manager - these tests exercise the
manager directly instead.
"""

import pytest

from plugins._coding_controller.helpers import coding_agent_manager, diagnostician


class _FakeSpawnedAgent:
    """Stands in for agent.Agent - only implements what coding_agent_manager touches."""

    DATA_NAME_SUPERIOR = "_superior"
    last_instance = None

    def __init__(self, number, config, context):
        self.number = number
        self.config = config
        self.context = context
        self.data = {"preexisting": "value"}
        self.user_messages = []
        self._responses = iter(["first response"])
        type(self).last_instance = self

    def set_data(self, key, value):
        self.data[key] = value

    def hist_add_user_message(self, message):
        self.user_messages.append(message)

    async def monologue(self):
        return next(self._responses, "no more responses")


class _FakeParentAgent:
    number = 0
    context = "fake-context"


# ------------------------------------------------------------------
# coding_agent_manager.create_role / send_task / terminate_role
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_role_spawns_agent_with_requested_profile(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    captured = {}

    def _fake_initialize_agent(**kwargs):
        captured.update(kwargs)
        return "fake-config"

    monkeypatch.setattr(agent_module, "Agent", _FakeSpawnedAgent)
    monkeypatch.setattr(initialize_module, "initialize_agent", _fake_initialize_agent)

    parent = _FakeParentAgent()
    role = await coding_agent_manager.create_role(parent, "coding-diagnostician")

    assert captured["override_settings"]["agent_profile"] == "coding-diagnostician"
    assert role.profile == "coding-diagnostician"
    assert role.agent.number == parent.number + 1
    assert role.agent.context == parent.context
    assert role.agent.data["_superior"] is parent


@pytest.mark.asyncio
async def test_send_task_adds_user_message_and_returns_monologue_result(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    monkeypatch.setattr(agent_module, "Agent", _FakeSpawnedAgent)
    monkeypatch.setattr(initialize_module, "initialize_agent", lambda **kwargs: "fake-config")

    role = await coding_agent_manager.create_role(_FakeParentAgent(), "coding-reviewer")
    result = await coding_agent_manager.send_task(role, "do the thing")

    assert result == "first response"
    assert role.agent.user_messages[0].message == "do the thing"


def test_terminate_role_clears_role_agent_data():
    role = coding_agent_manager.RoleAgent(agent=_FakeSpawnedAgent(1, "cfg", "ctx"), profile="coding-reviewer")
    assert role.agent.data  # preexisting data present before terminate

    coding_agent_manager.terminate_role(role)

    assert role.agent.data == {}


def test_terminate_role_does_not_raise_on_broken_agent():
    class _BrokenAgent:
        @property
        def data(self):
            raise RuntimeError("boom")

    role = coding_agent_manager.RoleAgent(agent=_BrokenAgent(), profile="coding-reviewer")

    coding_agent_manager.terminate_role(role)  # must not raise


# ------------------------------------------------------------------
# diagnostician.build_diagnosis_packet
# ------------------------------------------------------------------

def test_build_diagnosis_packet_includes_all_sections():
    packet = diagnostician.build_diagnosis_packet(
        project_root=r"C:\Projects\ExampleApp",
        original_request="Add input validation",
        repair_attempts=3,
        max_repair_attempts=3,
        final_failure_summary="build: FAILED\ntest: FAILED",
        diff="--- a/x\n+++ b/x\n+ broken change",
        repair_history="attempt 1: tried X\nattempt 2: tried Y",
    )

    assert r"C:\Projects\ExampleApp" in packet
    assert "Add input validation" in packet
    assert "3/3" in packet
    assert "build: FAILED" in packet
    assert "broken change" in packet
    assert "tried X" in packet


def test_build_diagnosis_packet_handles_missing_optional_fields():
    packet = diagnostician.build_diagnosis_packet(
        project_root="C:\\proj",
        original_request="",
        repair_attempts=1,
        max_repair_attempts=1,
        final_failure_summary="",
        diff="",
        repair_history="",
    )

    assert "(not provided)" in packet
    assert "(no diff available)" in packet
    assert "Repair attempt history" not in packet  # omitted entirely when empty


# ------------------------------------------------------------------
# diagnostician.run_diagnosis - spawn wiring via coding_agent_manager
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_diagnosis_returns_raw_response_text(monkeypatch):
    import agent as agent_module
    import initialize as initialize_module

    captured = {}

    def _fake_initialize_agent(**kwargs):
        captured.update(kwargs)
        return "fake-config"

    monkeypatch.setattr(agent_module, "Agent", _FakeSpawnedAgent)
    monkeypatch.setattr(initialize_module, "initialize_agent", _fake_initialize_agent)

    result = await diagnostician.run_diagnosis(_FakeParentAgent(), "packet text")

    assert result == "first response"
    assert captured["override_settings"]["agent_profile"] == "coding-diagnostician"


@pytest.mark.asyncio
async def test_run_diagnosis_spawn_failure_returns_explanatory_string_not_raised(monkeypatch):
    import initialize as initialize_module

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(initialize_module, "initialize_agent", _raise)

    result = await diagnostician.run_diagnosis(_FakeParentAgent(), "packet text")

    assert "boom" in result
    assert "failed to run" in result
