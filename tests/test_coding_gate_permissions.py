"""The coding completion gate asks before running a project's own commands (enforcement audit E5).

Build/test commands (npm test, dotnet build, pytest...) execute whatever the
project defines; they used to run with no permission check, also in
Accept-edits mode where commands should ask.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from helpers.errors import RepairableException
from plugins._coding_controller.extensions.python.tool_execute_after import _80_completion_gate as gate_ext
from plugins._permissions.helpers import ask, rules
from plugins._permissions.helpers import config as perm_config


def _gate():
    data = {}
    ctx = types.SimpleNamespace(id="ctx", data=data, get_data=data.get, set_data=data.__setitem__)
    return gate_ext.CodingCompletionGate(agent=types.SimpleNamespace(context=ctx, agent_name="A0"))


@pytest.fixture
def mode(monkeypatch):
    def set_mode(name):
        monkeypatch.setattr(perm_config, "get_config", lambda agent: {
            "mode": name, "ruleset": rules.Ruleset.from_config({}), "approval_timeout_seconds": 5,
        })
    return set_mode


@pytest.fixture
def approvals(monkeypatch):
    calls = []
    answer = {"approve": True}

    async def request(agent, tool_name, tool_args, **kwargs):
        calls.append(tool_args["root"])
        if not answer["approve"]:
            raise RepairableException("declined")

    monkeypatch.setattr(ask, "request_approval", request)
    return calls, answer


def _may(gate, root="C:/proj"):
    return asyncio.run(gate._may_run_project_commands(root, "npm"))


def test_plan_mode_never_runs_project_commands(mode, approvals):
    mode("plan")
    assert _may(_gate()) is False
    assert approvals[0] == []


def test_auto_mode_runs_without_asking(mode, approvals):
    mode("auto")
    assert _may(_gate()) is True
    assert approvals[0] == []


@pytest.mark.parametrize("name", ["manual", "accept_edits"])
def test_manual_and_accept_edits_ask_once_per_project(mode, approvals, name):
    mode(name)
    gate = _gate()
    assert _may(gate) is True and _may(gate) is True
    assert approvals[0] == ["C:/proj"]  # asked once, remembered for this chat
    assert _may(gate, "C:/other") is True
    assert approvals[0] == ["C:/proj", "C:/other"]


def test_declined_project_is_skipped_and_not_asked_again(mode, approvals):
    mode("manual")
    approvals[1]["approve"] = False
    gate = _gate()
    assert _may(gate) is False and _may(gate) is False
    assert approvals[0] == ["C:/proj"]
