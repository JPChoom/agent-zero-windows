"""Agent Workspace validation (v1.4 item 2): contention, isolation, process
exit, restart, ownership history and audit failures.

Uses real idle processes where the behaviour depends on the OS (start-time
checks); contexts are plain ids, which is all the registry needs.
"""

from __future__ import annotations

import random
import subprocess
import sys
import threading
import time

import pytest

from helpers import workspace

NO_WINDOW = 0x08000000


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    from helpers import access_control

    monkeypatch.setattr(access_control, "_audit_path", lambda: str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(access_control, "_ip_history", None)
    workspace._resources.clear()
    yield
    workspace._resources.clear()


@pytest.fixture
def proc():
    started = []

    def spawn():
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WINDOW)
        started.append(p)
        time.sleep(0.2)
        return p

    yield spawn
    for p in started:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)


def _audit_events(tmp_path):
    import json

    path = tmp_path / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- contention ------------------------------------------------------------------

def test_concurrent_ownership_changes_stay_consistent(proc):
    """Many agents and the user changing one app's owner at once: no errors
    other than refusals, a valid final owner, and a history entry per change."""
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    errors = []
    changes = {"n": 0}
    lock = threading.Lock()

    def worker(seed):
        rng = random.Random(seed)
        for _ in range(50):
            try:
                choice = rng.choice(("hand", "assign", "pass"))
                if choice == "hand":
                    owner = workspace.agent_number(res.owner_agent)
                    workspace.hand_over("chat", p.pid, owner, f"A{owner + 1}")
                elif choice == "assign":
                    workspace.assign(res.id, "chat", f"A{rng.randint(0, 3)}")
                else:
                    workspace.pass_up("chat", rng.randint(1, 4))
                with lock:
                    changes["n"] += 1
            except ValueError:
                pass  # a refusal (the app moved before this agent acted) is correct
            except Exception as exc:  # anything else is a bug
                errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errors == []
    assert res.owner_context == "chat" and res.owner_agent.startswith("A")
    assert workspace.agent_number(res.owner_agent) >= 0
    assert 1 <= len(res.history) <= workspace.MAX_HISTORY
    assert res.history[-1]["agent"] == res.owner_agent  # the last entry is the current owner


def test_hand_over_rechecks_ownership_under_the_lock(proc, monkeypatch):
    """If the app is reassigned after an agent decided to hand it over, the
    hand-over is refused instead of overwriting the newer owner."""
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A1")
    workspace.assign(res.id, "chat", "A0")  # the user gave it to A0 meanwhile
    with pytest.raises(ValueError):
        workspace.hand_over("chat", p.pid, 1, "A2")  # A1 no longer owns it
    assert res.owner_agent == "A0"


# -- isolation -------------------------------------------------------------------

def test_another_chat_can_neither_use_nor_take_an_app(proc):
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat-a", agent_name="A0")
    assert workspace.owns_app("chat-a", p.pid, 0)
    assert not workspace.owns_app("chat-b", p.pid)
    assert not workspace.owns_app("chat-b", p.pid, 0)
    with pytest.raises(ValueError):
        workspace.hand_over("chat-b", p.pid, 0, "A1")
    assert workspace.assign(res.id, "chat-b", "A0") is None
    assert res.owner_context == "chat-a"


# -- process exit and pid reuse --------------------------------------------------

def test_an_exited_app_is_owned_by_nobody_and_cannot_be_adopted(proc):
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    p.kill()
    p.wait(timeout=10)
    assert not workspace.owns_app("chat", p.pid)
    assert workspace.adopt(res.id, "chat") is None
    assert workspace.apps() == []


# A reused pid is covered by tests/test_workspace.py::test_a_reused_process_id_is_never_treated_as_owned.


# -- restart ---------------------------------------------------------------------

def test_after_a_restart_running_apps_are_the_users(proc):
    """The registry is in memory by design: after a restart (an empty
    registry) nothing is agent-owned, so agents must ask before using an app."""
    p = proc()
    workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    workspace._resources.clear()  # what a restart leaves
    assert not workspace.owns_app("chat", p.pid)
    assert not workspace.owns_app("chat", p.pid, 0)


# -- history and audit -----------------------------------------------------------

def test_history_records_every_change_with_who_made_it(proc, tmp_path):
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    workspace.hand_over("chat", p.pid, 0, "A2")
    workspace.pass_up("chat", 2)
    workspace.assign(res.id, "chat", "A0", by="local")
    events = [(h["event"], h["agent"], h["by"]) for h in res.history]
    assert events == [
        ("launched", "A0", "A0"),
        ("handed over", "A2", "A0"),
        ("passed up", "A1", "A2"),
        ("assigned", "A0", "local"),
    ]
    assert "history" in res.public()
    audited = _audit_events(tmp_path)
    assert {"workspace_handover", "workspace_pass_up", "workspace_assign"} <= set(audited)


def test_reregistering_an_owned_process_for_another_chat_is_audited(proc, tmp_path):
    p = proc()
    workspace.register_app(p.pid, "notepad", context_id="chat-a", agent_name="A0")
    res = workspace.register_app(p.pid, "notepad", context_id="chat-b", agent_name="A0")
    assert res.owner_context == "chat-b"
    assert res.history[-1]["event"] == "registered again"
    assert "workspace_reassigned" in _audit_events(tmp_path)


def test_history_is_bounded(proc):
    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    for i in range(workspace.MAX_HISTORY + 20):
        workspace.assign(res.id, "chat", f"A{i % 3}")
    assert len(res.history) == workspace.MAX_HISTORY


def test_a_failed_audit_write_is_reported_not_swallowed(proc, monkeypatch):
    from helpers import access_control
    from helpers.print_style import PrintStyle

    p = proc()
    res = workspace.register_app(p.pid, "notepad", context_id="chat", agent_name="A0")
    warnings = []

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(access_control, "audit", broken)
    monkeypatch.setattr(PrintStyle, "warning", staticmethod(lambda *a, **k: warnings.append(" ".join(map(str, a)))))
    workspace.assign(res.id, "chat", "A1")
    assert res.owner_agent == "A1"  # the change itself still happens
    assert any("could not write audit event" in w for w in warnings)
