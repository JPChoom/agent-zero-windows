"""Child agents: live progress, a git worktree per child, and the panel's API."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import child_agents
from plugins._coding_controller.helpers import task_worktrees as tw

ROOT = Path(__file__).resolve().parents[1]


class _Log:
    def __init__(self, items):
        import threading

        self._lock = threading.Lock()
        self.logs = items


def _item(type_, heading, timestamp):
    return SimpleNamespace(type=type_, heading=heading, timestamp=timestamp)


class _Context:
    contexts: dict = {}

    def __init__(self, name="parent"):
        self.id = f"ctx-{len(_Context.contexts) + 1}-{name}"
        self.name, self.data, self.output_data = name, {}, {}
        self.config = SimpleNamespace(profile="")
        self.task, self.messages, self.killed = None, [], 0
        self.log = _Log([])
        _Context.contexts[self.id] = self

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value

    def set_output_data(self, key, value):
        self.output_data[key] = value

    def is_running(self):
        return False

    def communicate(self, msg):
        self.messages.append(msg.message)

        class _Done:
            async def result(self, timeout=None):
                return "done"

        self.task = _Done()
        return self.task

    def kill_process(self):
        self.killed += 1


# -- progress ------------------------------------------------------------------------------

def test_progress_reads_the_newest_log_entry():
    child = _Context("tests")
    child.log = _Log([
        _item("user", "Run the tests", 100.0),
        _item("tool", "icon://construction A1: Using tool 'code_execution_tool'", 101.0),
        _item("code_exe", "icon://terminal A1: Running pytest", 102.0),
        _item("util", "", 103.0),
    ])
    assert child_agents.progress(child) == {"text": "Running pytest", "kind": "code_exe", "steps": 2, "last_activity": 102.0}


def test_progress_of_a_child_without_a_log_is_empty():
    assert child_agents.progress(None)["text"] == "" and child_agents.progress(SimpleNamespace())["steps"] == 0
    assert child_agents.progress(_Context("new"))["last_activity"] == 0.0


# -- a worktree per child --------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def world(tmp_path, monkeypatch):
    _Context.contexts = {}
    monkeypatch.setattr(child_agents, "_get_context", lambda cid: _Context.contexts.get(cid))
    monkeypatch.setattr(child_agents, "_create", lambda parent, agent, name, profile: _Context(name))
    monkeypatch.setattr(child_agents, "_discard", lambda child: _Context.contexts.pop(child.id, None))
    from helpers import message_queue, persist_chat

    monkeypatch.setattr(message_queue, "log_user_message", lambda *a, **k: None)
    monkeypatch.setattr(persist_chat, "save_tmp_chat", lambda *a, **k: None)
    monkeypatch.setattr(tw, "_workdir", lambda: tmp_path / "workdir")
    repo = tmp_path / "workdir" / "app"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "first")
    parent = _Context("parent")
    agent = SimpleNamespace(context=parent, agent_name="A0", config=SimpleNamespace(profile=""), data={})
    return SimpleNamespace(parent=parent, agent=agent, repo=repo)


@needs_git
def test_a_child_with_a_repo_works_in_its_own_worktree(world):
    asyncio.run(child_agents.send(world.agent, "fixer", "Fix the bug.", repo=str(world.repo)))
    child = child_agents.find(world.parent, "fixer")
    [tree] = child_agents.worktrees_of(child)
    assert tree["branch"] == "a0/fixer" and Path(tree["path"]).is_dir() and Path(tree["path"]) != world.repo
    assert child.messages[0].startswith(f"Your own git worktree for this job is {tree['path']}") and child.messages[0].endswith("Fix the bug.")
    [row] = child_agents.describe(world.parent)
    assert row["worktrees"] == [tree] and "activity" in row


@needs_git
def test_a_child_gets_one_worktree_and_keeps_it(world):
    asyncio.run(child_agents.send(world.agent, "fixer", "Fix the bug.", repo=str(world.repo)))
    asyncio.run(child_agents.send(world.agent, "fixer", "Now add a test."))  # next task, same worktree
    child = child_agents.find(world.parent, "fixer")
    assert child.messages[1] == "Now add a test."
    with pytest.raises(child_agents.ChildAgentError, match="already works in"):
        asyncio.run(child_agents.send(world.agent, "fixer", "Again.", repo=str(world.repo)))


@needs_git
def test_a_child_that_cannot_get_its_worktree_is_not_kept(world, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(child_agents.ChildAgentError):
        asyncio.run(child_agents.send(world.agent, "fixer", "Fix it.", repo=str(plain)))
    assert child_agents.registry(world.parent) == {}


@needs_git
def test_the_parent_reviews_and_merges_a_childs_worktree(world, monkeypatch):
    from plugins._coding_controller.tools.coding_task import CodingTask

    asyncio.run(child_agents.send(world.agent, "fixer", "Fix the bug.", repo=str(world.repo)))
    child = child_agents.find(world.parent, "fixer")
    [tree] = child_agents.worktrees_of(child)
    (Path(tree["path"]) / "app.py").write_text("print('v2')\n", encoding="utf-8")
    tool = CodingTask(agent=world.agent, name="coding_task", method=None, args={}, message="", loop_data=None)

    diff = asyncio.run(tool.execute(action="diff", child="fixer"))
    assert "v2" in diff.message
    asyncio.run(tool.execute(action="commit", child="fixer", message="Fix"))
    merged = asyncio.run(tool.execute(action="merge", child="fixer"))
    assert '"merged": true' in merged.message
    assert (world.repo / "app.py").read_text(encoding="utf-8") == "print('v2')\n"
    assert child_agents.worktrees_of(child) == [] and not Path(tree["path"]).exists()


def test_coding_task_refuses_an_unknown_child_and_a_start_for_a_child(world):
    from helpers.errors import RepairableException
    from plugins._coding_controller.tools.coding_task import CodingTask

    tool = CodingTask(agent=world.agent, name="coding_task", method=None, args={}, message="", loop_data=None)
    with pytest.raises(RepairableException, match="No child agent"):
        asyncio.run(tool.execute(action="diff", child="nobody"))
    asyncio.run(child_agents.send(world.agent, "plain", "Hi."))
    with pytest.raises(RepairableException, match="child_agent"):
        asyncio.run(tool.execute(action="start", child="plain", repo=str(world.repo)))


# -- the panel's API ----------------------------------------------------------------------------

def _api(monkeypatch, contexts):
    from agent import AgentContext
    from plugins._child_agents.api.status import Status

    monkeypatch.setattr(AgentContext, "get", staticmethod(lambda cid: contexts.get(cid)))
    handler = Status.__new__(Status)
    return lambda payload: asyncio.run(handler.process(payload, None))


def test_the_api_lists_a_chats_children(world, monkeypatch):
    asyncio.run(child_agents.send(world.agent, "tests", "Run them."))
    call = _api(monkeypatch, _Context.contexts)
    result = call({"context_id": world.parent.id})
    assert result["ok"] and result["parent"]["id"] == world.parent.id and result["current"] == world.parent.id
    assert [c["name"] for c in result["children"]] == ["tests"] and result["now"] > 0


def test_a_child_chat_sees_its_siblings(world, monkeypatch):
    asyncio.run(child_agents.send(world.agent, "tests", "Run them."))
    asyncio.run(child_agents.send(world.agent, "docs", "Write them."))
    child = child_agents.find(world.parent, "tests")
    child.set_data(child_agents.CHILD_OF_KEY, world.parent.id)
    result = _api(monkeypatch, _Context.contexts)({"context_id": child.id})
    assert result["parent"]["id"] == world.parent.id and result["current"] == child.id
    assert {c["name"] for c in result["children"]} == {"tests", "docs"}


def test_the_api_stops_a_child_and_reports_a_bad_name(world, monkeypatch):
    asyncio.run(child_agents.send(world.agent, "tests", "Run them."))
    call = _api(monkeypatch, _Context.contexts)
    assert call({"context_id": world.parent.id, "action": "stop", "name": "tests"})["ok"]
    assert child_agents.find(world.parent, "tests").killed == 1
    bad = call({"context_id": world.parent.id, "action": "stop", "name": "nobody"})
    assert not bad["ok"] and "No child agent" in bad["error"]


def test_an_unknown_chat_has_no_children(monkeypatch):
    assert _api(monkeypatch, {})({"context_id": "gone"})["children"] == []


def test_the_panel_is_registered_like_the_workspace():
    base = ROOT / "plugins" / "_child_agents"
    for path in ("plugin.yaml", "webui/main.html", "webui/child-agents-panel.html", "webui/child-agents-store.js",
                 "extensions/webui/right-canvas-panels/child-agents-panel.html",
                 "extensions/webui/right_canvas_register_surfaces/register-child-agents.js",
                 "extensions/webui/surfaces_register/register-child-agents.js", "AGENTS.md"):
        assert (base / path).is_file(), path
    store = (base / "webui/child-agents-store.js").read_text(encoding="utf-8")
    assert "/plugins/_child_agents/status" in store and 'createStore("childAgents"' in store
