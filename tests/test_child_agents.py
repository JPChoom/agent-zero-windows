"""Independent child agents: named, resumable, stoppable, inside the parent's limits."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import child_agents, parallel_tools

ROOT = Path(__file__).resolve().parents[1]


class _Task:
    def __init__(self, reply="done", delay=0.0):
        self.reply, self.delay, self.killed = reply, delay, False

    async def result(self, timeout=None):
        if timeout is not None and self.delay > timeout:
            await asyncio.sleep(timeout)
            raise TimeoutError()
        await asyncio.sleep(self.delay)
        return self.reply

    def is_alive(self):
        return not self.killed


class _Context:
    contexts: dict = {}

    def __init__(self, name="parent", profile=""):
        self.id = f"ctx-{len(_Context.contexts) + 1}"
        self.name, self.data, self.output_data = name, {}, {}
        self.config = SimpleNamespace(profile=profile)
        self.task, self.messages, self.killed = None, [], 0
        self.next_reply, self.next_delay = "done", 0.0
        _Context.contexts[self.id] = self

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value

    def set_output_data(self, key, value):
        self.output_data[key] = value

    def is_running(self):
        return bool(self.task and self.task.is_alive() and self.task.delay > 0 and not self.killed)

    def communicate(self, msg):
        self.messages.append(msg.message)
        self.task = _Task(self.next_reply, self.next_delay)
        return self.task

    def kill_process(self):
        self.killed += 1
        if self.task:
            self.task.killed = True


@pytest.fixture
def world(monkeypatch):
    _Context.contexts = {}
    monkeypatch.setattr(child_agents, "_get_context", lambda cid: _Context.contexts.get(cid))
    monkeypatch.setattr(child_agents, "_create", lambda parent, agent, name, profile: _Context(name, profile))
    from helpers import message_queue, persist_chat

    monkeypatch.setattr(message_queue, "log_user_message", lambda *a, **k: None)
    monkeypatch.setattr(persist_chat, "save_tmp_chat", lambda *a, **k: None)
    parent = _Context("parent")
    agent = SimpleNamespace(context=parent, agent_name="A0", config=SimpleNamespace(profile=""), data={})
    return SimpleNamespace(parent=parent, agent=agent)


def _run(coro):
    return asyncio.run(coro)


def test_a_child_gets_its_own_chat_and_answers(world):
    outcome = _run(child_agents.send(world.agent, "tests", "Run the tests.", profile="developer"))
    child = child_agents.find(world.parent, "tests")
    assert child is not world.parent and child.config.profile == "developer"
    assert outcome["result"] == "done" and child.messages == ["Run the tests."]
    assert child_agents.registry(world.parent) == {"tests": child.id}


def test_the_same_name_resumes_the_same_child(world):
    _run(child_agents.send(world.agent, "research", "Find X."))
    first = child_agents.find(world.parent, "research")
    _run(child_agents.send(world.agent, "research", "Now compare it with Y."))
    assert child_agents.find(world.parent, "research") is first
    assert first.messages == ["Find X.", "Now compare it with Y."]


def test_a_child_can_work_while_the_parent_continues(world):
    def slow(parent, agent, name, profile):
        context = _Context(name, profile)
        context.next_delay = 0.2
        return context

    child_agents._create = slow
    outcome = _run(child_agents.send(world.agent, "tests", "Run the suite.", wait=False))
    assert outcome["state"] == "running"
    later = _run(child_agents.result(world.agent, "tests", timeout=0.05))
    assert later["state"] == "running" and "still working" in later["note"]


def test_a_busy_child_is_not_given_a_second_task(world):
    child_agents._create = lambda parent, agent, name, profile: _busy(_Context(name, profile))
    _run(child_agents.send(world.agent, "tests", "First.", wait=False))
    with pytest.raises(child_agents.ChildAgentError, match="still working"):
        _run(child_agents.send(world.agent, "tests", "Second."))


def _busy(context):
    context.next_delay = 5
    return context


def test_stopping_a_waiting_parent_stops_the_child(world):
    child_agents._create = lambda parent, agent, name, profile: _busy(_Context(name, profile))

    async def run():
        waiting = asyncio.ensure_future(child_agents.send(world.agent, "tests", "Long job."))
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    _run(run())
    assert child_agents.find(world.parent, "tests").killed == 1


def test_stop_and_forget(world):
    child_agents._create = lambda parent, agent, name, profile: _busy(_Context(name, profile))
    _run(child_agents.send(world.agent, "tests", "Long job.", wait=False))
    child = child_agents.find(world.parent, "tests")
    assert child_agents.stop(world.parent, "tests")["state"] == "stopped" and child.killed == 1
    child_agents.forget(world.parent, "tests")
    assert child_agents.registry(world.parent) == {}


def test_resetting_a_parent_stops_children_and_grandchildren(world):
    child_agents._create = lambda parent, agent, name, profile: _busy(_Context(name, profile))
    _run(child_agents.send(world.agent, "lead", "Coordinate.", wait=False))
    lead = child_agents.find(world.parent, "lead")
    lead_agent = SimpleNamespace(context=lead, agent_name="A0", config=lead.config, data={})
    _run(child_agents.send(lead_agent, "helper", "Help.", wait=False))
    assert child_agents.stop_all(world.parent) == 2
    assert lead.killed == 1 and child_agents.find(lead, "helper").killed == 1


def test_a_child_acts_for_the_parent_chat(world, monkeypatch):
    _run(child_agents.send(world.agent, "tests", "Run."))
    child = child_agents.find(world.parent, "tests")
    assert child.data[parallel_tools.PARALLEL_WORKER_PARENT_CONTEXT_KEY] == world.parent.id
    assert child.data[child_agents.CHILD_OF_KEY] == world.parent.id
    from agent import AgentContext

    monkeypatch.setattr(AgentContext, "get", staticmethod(lambda cid: _Context.contexts.get(cid)))
    assert parallel_tools.governing_context(child) == (world.parent, False)


def test_a_grandchild_acts_for_the_root_chat(world, monkeypatch):
    _run(child_agents.send(world.agent, "lead", "Coordinate."))
    lead = child_agents.find(world.parent, "lead")
    lead_agent = SimpleNamespace(context=lead, agent_name="A0", config=lead.config, data={})
    _run(child_agents.send(lead_agent, "helper", "Help."))
    from agent import AgentContext

    monkeypatch.setattr(AgentContext, "get", staticmethod(lambda cid: _Context.contexts.get(cid)))
    assert parallel_tools.governing_context(child_agents.find(lead, "helper"))[0] is world.parent


def test_a_child_keeps_the_parents_capability_limits(world, monkeypatch):
    from plugins._capabilities.helpers import policy

    monkeypatch.setattr(policy, "worker_scopes", lambda agent: [["", "researcher"]])
    _run(child_agents.send(world.agent, "tests", "Run."))
    child = child_agents.find(world.parent, "tests")
    assert child.data[policy.CONTEXT_SCOPES_KEY] == [["", "researcher"]]
    assert not policy.CONTEXT_SCOPES_KEY.startswith("_")  # saved with the chat, so it holds after a restart


def test_names_profiles_and_limits_are_checked(world):
    with pytest.raises(child_agents.ChildAgentError, match="short name"):
        _run(child_agents.send(world.agent, "bad name!", "x"))
    with pytest.raises(child_agents.ChildAgentError, match="needs a message"):
        _run(child_agents.send(world.agent, "tests", "  "))
    _run(child_agents.send(world.agent, "tests", "x", profile="developer"))
    with pytest.raises(child_agents.ChildAgentError, match="uses profile"):
        _run(child_agents.send(world.agent, "tests", "y", profile="researcher"))
    for i in range(child_agents.MAX_CHILDREN - 1):
        _run(child_agents.send(world.agent, f"c{i}", "x"))
    with pytest.raises(child_agents.ChildAgentError, match="already has"):
        _run(child_agents.send(world.agent, "one-more", "x"))


def test_status_lists_every_child(world):
    _run(child_agents.send(world.agent, "tests", "x", profile="developer"))
    listed = child_agents.describe(world.parent)
    [row] = listed
    assert {k: row[k] for k in ("name", "id", "state", "profile")} == {
        "name": "tests", "id": child_agents.find(world.parent, "tests").id, "state": "idle", "profile": "developer"}
    assert row["worktrees"] == [] and set(row["activity"]) == {"text", "kind", "steps", "last_activity"}


def test_the_tool_and_its_prompt_exist():
    assert (ROOT / "tools/child_agent.py").is_file()
    prompt = (ROOT / "prompts/agent.system.tool.child_agent.md").read_text(encoding="utf-8")
    assert '"tool_name": "child_agent"' in prompt
    for kind in ("reset", "remove"):
        assert (ROOT / f"extensions/python/_functions/agent/AgentContext/{kind}/start/_40_stop_child_agents.py").is_file()
