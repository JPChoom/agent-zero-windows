"""The Agent Workspace (helpers/workspace.py): app ownership that survives a
parallel worker's temporary context, hand-over / orphaning when a context
ends, deterministic terminal cleanup, live listings, and the API. Real
contexts and real (idle) processes are used where the behaviour depends on
them; the Computer Use driver and terminal sessions are faked."""

from __future__ import annotations

import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from helpers import workspace

NO_WINDOW = 0x08000000


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    from helpers import access_control

    # Never write test events into the real usr/security_audit.jsonl.
    monkeypatch.setattr(access_control, "_audit_path", lambda: str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(access_control, "_ip_history", None)
    # Extension lists are cached per hook point; an earlier test that stubbed
    # plugin discovery can leave a list without the plugin hooks tested here.
    from helpers import cache, extension

    cache.clear(extension._EXTENSIONS_CACHE_AREA)
    cache.clear(extension._CLASSES_CACHE_AREA)
    workspace._resources.clear()
    yield
    workspace._resources.clear()


@pytest.fixture
def proc():
    """A real idle process, so start-time checks run against the OS."""
    started = []

    def spawn():
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WINDOW)
        started.append(p)
        time.sleep(0.2)
        return p

    yield spawn
    for p in started:
        p.kill()
        p.wait(timeout=10)


@pytest.fixture
def contexts(monkeypatch):
    """A parent chat and a parallel worker context started by it (real objects)."""
    from agent import AgentContext
    from helpers import parallel_tools, state_snapshot  # noqa: F401
    from initialize import initialize_agent

    made = []

    def make(name, parent=None):
        ctx = AgentContext(config=initialize_agent(), id=f"ws-{name}-{len(made)}", name=name, set_current=False)
        if parent:
            ctx.set_data(workspace.PARALLEL_PARENT_KEY, parent.id)
        made.append(ctx)
        return ctx

    yield make
    for ctx in made:
        AgentContext.remove(ctx.id)


# -- ownership -----------------------------------------------------------------

def test_an_app_is_owned_only_by_the_chat_that_launched_it_while_it_runs(proc):
    p = proc()
    workspace.register_app(p.pid, "notepad", context_id="chat-a", agent_name="A0")
    assert workspace.owns_app("chat-a", p.pid)
    assert not workspace.owns_app("chat-b", p.pid)
    p.kill()
    p.wait(timeout=10)
    assert not workspace.owns_app("chat-a", p.pid)
    assert workspace.apps() == []  # an exited app is dropped, not listed


def test_a_reused_process_id_is_never_treated_as_owned(proc):
    p = proc()
    entry = workspace.register_app(p.pid, "old app", context_id="chat-a")
    entry.handle["started"] -= 500  # the pid now belongs to a process started later
    assert not workspace.owns_app("chat-a", p.pid)
    assert workspace.apps() == []


def test_registering_the_same_process_again_updates_its_owner(proc):
    p = proc()
    workspace.register_app(p.pid, "app", context_id="chat-a", agent_name="A0")
    workspace.register_app(p.pid, "app", context_id="chat-b", agent_name="A1")
    assert len(workspace.apps()) == 1 and workspace.owns_app("chat-b", p.pid)


# -- hand-over and orphaning ------------------------------------------------------

def test_a_worker_ending_hands_its_apps_to_the_chat_that_started_the_job(proc, contexts):
    from agent import AgentContext

    parent = contexts("parent")
    worker = contexts("worker", parent)
    p = proc()
    workspace.register_app(p.pid, "calc", context_id=worker.id, agent_name="A0", job_id="job-1")

    AgentContext.remove(worker.id)  # runs the real remove hook

    assert workspace.owns_app(parent.id, p.pid)
    [entry] = workspace.apps()
    assert entry.state == workspace.ACTIVE and entry.origin_context == worker.id and "job-1" == entry.origin_job
    assert "Handed over" in entry.note and p.poll() is None  # never closed


def test_a_deleted_chat_orphans_its_apps_without_closing_them(proc, contexts):
    from agent import AgentContext

    chat = contexts("chat")
    p = proc()
    workspace.register_app(p.pid, "paint", context_id=chat.id)

    AgentContext.remove(chat.id)

    [entry] = workspace.apps()
    assert entry.state == workspace.ORPHANED and "chat was deleted" in entry.note
    assert not workspace.owns_app(chat.id, p.pid) and p.poll() is None


def test_a_worker_whose_parent_chat_is_gone_orphans_instead(proc, contexts):
    from agent import AgentContext

    parent = contexts("parent")
    worker = contexts("worker", parent)
    p = proc()
    workspace.register_app(p.pid, "app", context_id=worker.id)
    AgentContext.remove(parent.id)
    AgentContext.remove(worker.id)
    assert workspace.apps()[0].state == workspace.ORPHANED


def test_orphans_can_be_adopted_by_a_chat_or_released(proc):
    a, b = proc(), proc()
    one = workspace.register_app(a.pid, "one", context_id="gone-chat")
    two = workspace.register_app(b.pid, "two", context_id="gone-chat")
    one.state = two.state = workspace.ORPHANED

    assert workspace.adopt(one.id, "chat-x", "A0").state == workspace.ACTIVE
    assert workspace.owns_app("chat-x", a.pid)
    assert workspace.release(two.id) and not workspace.owns_app("gone-chat", b.pid)
    assert [r.id for r in workspace.apps()] == [one.id]
    assert workspace.adopt("res-missing", "chat-x") is None


def test_hand_over_and_orphaning_are_audited(proc, contexts, monkeypatch):
    from agent import AgentContext
    from helpers import access_control

    events = []
    monkeypatch.setattr(access_control, "audit", lambda event, **f: events.append((event, f)))
    parent = contexts("parent")
    worker = contexts("worker", parent)
    p, q = proc(), proc()
    workspace.register_app(p.pid, "handed", context_id=worker.id)
    workspace.register_app(q.pid, "orphan", context_id=parent.id)
    AgentContext.remove(worker.id)
    AgentContext.remove(parent.id)
    # The worker's app moved to the parent first, so deleting the parent orphans both.
    assert [e for e, _ in events] == ["workspace_handover", "workspace_orphaned", "workspace_orphaned"]
    assert events[0][1]["to_context"] == parent.id and events[0][1]["label"] == "handed"
    assert {f["label"] for e, f in events if e == "workspace_orphaned"} == {"handed", "orphan"}


# -- Computer Use: the original defect, end to end ---------------------------------------

@pytest.mark.asyncio
async def test_an_app_a_parallel_worker_launches_stays_owned_by_the_parent_after_the_job(proc, contexts, monkeypatch):
    from agent import AgentContext
    from plugins._computer_use.tools import computer_use as mod

    parent = contexts("parent")
    worker = contexts("worker", parent)
    app = proc()

    async def fake_call(agent, tool, args):
        if tool == "list_apps":
            return {"apps": []}
        if tool == "launch_app":
            return {"pid": app.pid, "windows": []}
        return {"summary": "ok"}

    async def noop(record):
        return None

    monkeypatch.setattr(mod.driver, "call", fake_call)
    monkeypatch.setattr(mod.audit_log, "append_record", noop)

    def tool_for(context):
        return mod.ComputerUse(agent=context.agent0, name="computer_use", method=None, args={}, message="", loop_data=None)

    launched = await tool_for(worker)._launch(cfg={}, app="calc")
    assert "New process" in launched.message
    assert tool_for(worker)._owned(app.pid) and not tool_for(parent)._owned(app.pid)

    AgentContext.remove(worker.id)  # the parallel job ended; its context is gone

    assert tool_for(parent)._owned(app.pid)  # the chat that started the job still owns it
    assert workspace.apps()[0].origin_agent == "A0" and workspace.apps()[0].label == "calc"


@pytest.mark.asyncio
async def test_closing_an_app_stops_tracking_it(proc, contexts, monkeypatch):
    from plugins._computer_use.tools import computer_use as mod

    chat = contexts("chat")
    app = proc()
    workspace.register_app(app.pid, "calc", context_id=chat.id)
    killed = []

    async def fake_call(agent, tool, args):
        killed.append(tool)
        return {"summary": "closed"}

    async def noop(record):
        return None

    monkeypatch.setattr(mod.driver, "call", fake_call)
    monkeypatch.setattr(mod.audit_log, "append_record", noop)
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: False)
    monkeypatch.setattr(mod.driver, "get_config", lambda agent=None: {**mod.driver.DEFAULTS, "control_enabled": True})
    import plugins._permissions.helpers.config as perm
    from plugins._permissions.helpers import rules

    monkeypatch.setattr(perm, "get_config", lambda agent=None: {"mode": "bypass", "ruleset": rules.Ruleset(), "approval_timeout_seconds": 5})
    t = mod.ComputerUse(agent=chat.agent0, name="computer_use", method=None, args={}, message="", loop_data=None)
    await t.execute(action="close", pid=app.pid)
    assert "kill_app" in killed and workspace.apps() == []


# -- terminals -------------------------------------------------------------------------

class _FakeShell:
    def __init__(self):
        self.killed = 0
        self.closed = 0
        self.cwd = "C:\\work"
        self.session = SimpleNamespace(_proc=SimpleNamespace(pid=None))

    def kill(self):
        self.killed += 1

    async def close(self):
        self.closed += 1


def _give_terminals(agent, *numbers):
    from plugins._code_execution.tools.code_execution_tool import ShellWrap, State

    shells = {n: ShellWrap(id=n, session=_FakeShell(), running=False) for n in numbers}
    agent.set_data("_cet_state", State(ssh_enabled=False, shells=dict(shells)))
    return shells  # a copy is stored, so closing a terminal does not change what tests inspect


def test_terminals_end_when_their_context_is_removed(contexts):
    from agent import AgentContext

    chat = contexts("chat")
    shells = _give_terminals(chat.agent0, 0, 1)
    AgentContext.remove(chat.id)
    assert [w.session.killed for w in shells.values()] == [1, 1]
    assert chat.agent0.get_data("_cet_state") is None


def test_terminals_end_when_a_chat_is_reset(contexts):
    chat = contexts("chat")
    shells = _give_terminals(chat.agent0, 0)
    chat.reset()
    assert shells[0].session.killed == 1


def test_a_subordinates_terminals_end_with_the_chat_and_when_it_is_replaced(contexts):
    from agent import Agent, AgentContext
    from initialize import initialize_agent

    chat = contexts("chat")
    sub = Agent(1, initialize_agent(), chat)
    chat.agent0.set_data(Agent.DATA_NAME_SUBORDINATE, sub)
    own, subs = _give_terminals(chat.agent0, 0), _give_terminals(sub, 0)

    workspace.end_agent(sub)  # what call_subordinate(reset=true) does before replacing it
    assert subs[0].session.killed == 1 and own[0].session.killed == 0

    AgentContext.remove(chat.id)
    assert own[0].session.killed == 1


@pytest.mark.asyncio
async def test_terminals_are_listed_per_agent_and_can_be_closed(contexts):
    from agent import Agent
    from initialize import initialize_agent
    from plugins._code_execution.helpers import workspace_provider as wp

    chat = contexts("chat")
    sub = Agent(1, initialize_agent(), chat)
    chat.agent0.set_data(Agent.DATA_NAME_SUBORDINATE, sub)
    _give_terminals(chat.agent0, 0)
    subs = _give_terminals(sub, 3)

    mine = [r for r in await wp.resources() if r["owner_context"] == chat.id]
    assert {(r["owner_agent"], r["label"]) for r in mine} == {("A0", "Terminal session 0"), ("A1", "Terminal session 3")}
    assert mine[0]["detail"] == "C:\\work" and mine[0]["kind"] == "terminal"

    assert await wp.close_terminal(f"terminal:{chat.id}:1:3")
    assert subs[3].session.closed == 1
    assert not await wp.close_terminal(f"terminal:{chat.id}:1:3")  # already closed
    assert not await wp.close_terminal("terminal:bad")


# -- listing and API --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_merges_apps_terminals_and_browser_tabs(proc, contexts, monkeypatch):
    from plugins._browser.helpers import runtime

    chat = contexts("My chat")
    app = proc()
    workspace.register_app(app.pid, "calc", context_id=chat.id, agent_name="A0")
    _give_terminals(chat.agent0, 0)
    monkeypatch.setattr(runtime, "peek_pages", lambda: [{"context_id": chat.id, "browser_id": 2, "url": "https://example.com/a"}])

    snap = await workspace.snapshot()
    mine = {r["kind"]: r for r in snap["resources"] if r["owner_context"] == chat.id}
    assert set(mine) == {"app", "terminal", "browser"}
    assert mine["browser"]["label"] == "example.com" and mine["browser"]["detail"] == "https://example.com/a"
    assert snap["contexts"][chat.id] == "My chat"


def test_browser_listing_only_reads_open_tabs_it_never_starts_a_browser(monkeypatch):
    from plugins._browser.helpers import runtime

    class Page:
        url = "https://example.org/"

    core = SimpleNamespace(pages={1: SimpleNamespace(page=Page()), 2: SimpleNamespace(page=SimpleNamespace())})
    monkeypatch.setattr(runtime, "_runtimes", {"ctx-1": SimpleNamespace(_core=core)})
    tabs = runtime.peek_pages()
    assert tabs[0] == {"context_id": "ctx-1", "browser_id": 1, "url": "https://example.org/"}
    assert tabs[1]["url"] == ""  # a page whose url cannot be read does not break the list


@pytest.fixture
def api(monkeypatch):
    from api import workspace as mod

    monkeypatch.setattr(mod, "caller", lambda request: (False, "local"))
    events = []
    from helpers import access_control

    monkeypatch.setattr(access_control, "audit", lambda event, **f: events.append((event, f.get("by"))))
    handler = mod.WorkspaceApi.__new__(mod.WorkspaceApi)
    return SimpleNamespace(mod=mod, call=lambda **inp: handler.process(inp, None), events=events)


@pytest.mark.asyncio
async def test_api_lists_adopts_and_releases(api, proc, contexts):
    chat = contexts("chat")
    p = proc()
    entry = workspace.register_app(p.pid, "calc", context_id="old-chat")
    entry.state = workspace.ORPHANED

    listed = await api.call(action="list")
    assert listed["ok"] and listed["resources"][0]["state"] == "orphaned" and "control_enabled" in listed

    assert (await api.call(action="adopt", id=entry.id, context_id="no-such-chat"))["ok"] is False
    assert (await api.call(action="adopt", id=entry.id, context_id=chat.id))["ok"] is True
    assert workspace.owns_app(chat.id, p.pid)
    assert (await api.call(action="release", id=entry.id))["ok"] is True
    assert (await api.call(action="release", id=entry.id))["ok"] is False
    assert api.events == [("workspace_adopt", "local"), ("workspace_release", "local")]


@pytest.mark.asyncio
async def test_api_closing_an_app_needs_input_enabled_and_an_untripped_kill_switch(api, proc, monkeypatch):
    from plugins._computer_use.helpers import driver

    p = proc()
    entry = workspace.register_app(p.pid, "calc", context_id="chat")
    calls = []

    async def fake_call(agent, tool, args):
        calls.append((tool, args["pid"]))
        return {}

    async def noop(record):
        return None

    monkeypatch.setattr(driver, "call", fake_call)
    monkeypatch.setattr(api.mod.audit_log, "append_record", noop)
    monkeypatch.setattr(driver, "get_config", lambda agent=None: {**driver.DEFAULTS, "control_enabled": False})
    assert "disabled" in (await api.call(action="close", id=entry.id))["error"] and not calls

    monkeypatch.setattr(driver, "get_config", lambda agent=None: {**driver.DEFAULTS, "control_enabled": True})
    monkeypatch.setattr(api.mod.kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(api.mod.kill_switch, "denial_message", lambda: "kill switch tripped")
    assert (await api.call(action="close", id=entry.id))["error"] == "kill switch tripped" and not calls

    monkeypatch.setattr(api.mod.kill_switch, "is_tripped", lambda: False)
    result = await api.call(action="close", id=entry.id)
    assert result["ok"] and calls == [("kill_app", p.pid)] and result["resources"] == []
    assert ("workspace_close", "local") in api.events
    assert "no longer" in (await api.call(action="close", id=entry.id))["error"]


@pytest.mark.asyncio
async def test_api_closes_a_terminal_and_rejects_unknown_actions(api, contexts):
    chat = contexts("chat")
    shells = _give_terminals(chat.agent0, 0)
    result = await api.call(action="close", id=f"terminal:{chat.id}:0:0")
    assert result["ok"] and shells[0].session.closed == 1
    assert (await api.call(action="explode"))["ok"] is False
