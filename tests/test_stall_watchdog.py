"""Stall watchdog: auto-nudges a running chat whose log hasn't moved for
STALL_SECONDS, never nudges idle/paused/progressing chats, and gives up with
a notification after MAX_NUDGES_PER_WINDOW nudges in NUDGE_WINDOW_SECONDS.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import extensions.python.job_loop._30_stall_watchdog as wd


class _Log:
    def __init__(self):
        self.guid = "g1"
        self.updates = []

    def log(self, **kw):
        self.updates.append(len(self.updates))


class _Ctx:
    def __init__(self, cid="c1", running=True, paused=False):
        self.id = cid
        self.name = "Test chat"
        self.log = _Log()
        self.running = running
        self.paused = paused
        self.nudges = 0

    def is_running(self):
        return self.running

    def nudge(self):
        self.nudges += 1
        self.log.log(type="user")  # a nudge logs its own message


@pytest.fixture
def env(monkeypatch):
    wd.StallWatchdog._state = {}
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(wd.time, "time", lambda: clock["now"])
    contexts = []
    monkeypatch.setattr(wd.AgentContext, "all", staticmethod(lambda: contexts))
    monkeypatch.setattr(wd.approval_registry, "has_pending", lambda: False)
    notes = []
    monkeypatch.setattr(
        wd.NotificationManager, "send_notification", staticmethod(lambda **kw: notes.append(kw))
    )
    return clock, contexts, notes


async def _tick(clock, seconds=0):
    clock["now"] += seconds
    await wd.StallWatchdog(agent=None).execute()


@pytest.mark.asyncio
async def test_stalled_running_chat_is_nudged_after_threshold(env):
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)

    await _tick(clock)  # baseline
    await _tick(clock, wd.STALL_SECONDS - 1)
    assert ctx.nudges == 0

    await _tick(clock, 2)
    assert ctx.nudges == 1


@pytest.mark.asyncio
async def test_progress_prevents_nudge(env):
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)

    await _tick(clock)
    for _ in range(5):
        ctx.log.log(type="agent")  # e.g. streamed output
        await _tick(clock, wd.STALL_SECONDS // 2)

    assert ctx.nudges == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("running,paused", [(False, False), (True, True)])
async def test_idle_or_paused_chats_are_never_nudged(env, running, paused):
    clock, contexts, _ = env
    ctx = _Ctx(running=running, paused=paused)
    contexts.append(ctx)

    await _tick(clock)
    await _tick(clock, wd.STALL_SECONDS * 3)

    assert ctx.nudges == 0


@pytest.mark.asyncio
async def test_nudges_own_log_lines_do_not_count_as_progress(env):
    """After a nudge that doesn't revive the agent, the next stall must
    still be detected STALL_SECONDS later."""
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)

    await _tick(clock)
    await _tick(clock, wd.STALL_SECONDS + 1)
    assert ctx.nudges == 1

    await _tick(clock, wd.STALL_SECONDS + 1)
    assert ctx.nudges == 2


@pytest.mark.asyncio
async def test_gives_up_with_notification_after_window_cap(env):
    clock, contexts, notes = env
    ctx = _Ctx()
    contexts.append(ctx)

    await _tick(clock)
    for _ in range(wd.MAX_NUDGES_PER_WINDOW + 3):
        await _tick(clock, wd.STALL_SECONDS + 1)

    assert ctx.nudges == wd.MAX_NUDGES_PER_WINDOW
    assert len(notes) == 1
    assert notes[0]["id"] == f"stall_watchdog_{ctx.id}"


@pytest.mark.asyncio
async def test_window_cap_expires(env):
    """Nudges older than NUDGE_WINDOW_SECONDS stop counting, so a chat that
    stalls occasionally over a long unattended run keeps being rescued."""
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)

    await _tick(clock)
    for _ in range(wd.MAX_NUDGES_PER_WINDOW):
        await _tick(clock, wd.STALL_SECONDS + 1)
        ctx.log.log(type="agent")  # the nudge worked
        await _tick(clock)
    assert ctx.nudges == wd.MAX_NUDGES_PER_WINDOW

    clock["now"] += wd.NUDGE_WINDOW_SECONDS
    ctx.log.log(type="agent")  # long stretch of healthy work
    await _tick(clock)
    await _tick(clock, wd.STALL_SECONDS + 1)
    assert ctx.nudges == wd.MAX_NUDGES_PER_WINDOW + 1


@pytest.mark.asyncio
async def test_pending_user_decision_is_not_a_stall(env, monkeypatch):
    """An Allow/Deny prompt can legitimately wait longer than STALL_SECONDS
    (infection-check clarification: 900s). The stall window must only
    start counting once the decision is resolved."""
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)
    pending = {"value": True}
    monkeypatch.setattr(wd.approval_registry, "has_pending", lambda: pending["value"])

    await _tick(clock)
    for _ in range(20):
        await _tick(clock, 60)  # 20 minutes waiting on the user
    assert ctx.nudges == 0

    pending["value"] = False
    await _tick(clock, wd.STALL_SECONDS - 60)
    assert ctx.nudges == 0
    await _tick(clock, 120)
    assert ctx.nudges == 1


@pytest.mark.asyncio
async def test_state_is_dropped_for_removed_chats(env):
    clock, contexts, _ = env
    ctx = _Ctx()
    contexts.append(ctx)
    await _tick(clock)
    assert ctx.id in wd.StallWatchdog._state

    contexts.clear()
    await _tick(clock)
    assert wd.StallWatchdog._state == {}
