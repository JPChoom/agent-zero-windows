"""TTYSession.__del__ must never drive an event loop.

Observed live: after a terminal-session reset, the old TTYSession was
garbage-collected mid-task-step on the agent's running loop. Its __del__
ran asyncio.run(self.close()) under nest_asyncio, spinning a nested loop
there; the interrupted task's just-scheduled 10ms sleep fired inside it,
its wakeup failed with "cannot enter context: ... is already entered",
and the agent froze permanently with no model activity.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins._code_execution.helpers import tty_session


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.pid = 12345
        self.killed = False
        self.terminated = False

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True


def _session_with_fake_proc():
    session = tty_session.TTYSession("fake-shell")
    proc = _FakeProc()
    session._proc = proc
    return session, proc


def test_del_kills_the_process_without_running_an_event_loop(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("__del__ must not run an event loop")

    monkeypatch.setattr(tty_session.asyncio, "run", _forbidden)
    monkeypatch.setattr(tty_session, "_IS_WIN", True)  # kill via proc.kill(), no killpg

    session, proc = _session_with_fake_proc()
    session.__del__()

    assert proc.killed is True


def test_del_on_a_never_started_session_is_a_noop():
    session = tty_session.TTYSession("fake-shell")
    session.__del__()  # must not raise


# Runs in a subprocess: a regression strands the task for good - even
# wait_for's own timeout can't cancel a task that can never be woken - so
# in-process it would hang the whole pytest run rather than fail.
_MID_STEP_SCRIPT = r'''
import asyncio, sys
sys.path.insert(0, sys.argv[1])
import nest_asyncio
from plugins._code_execution.helpers import tty_session

tty_session._IS_WIN = True
holder = []

class _SlowProc:
    returncode = None
    pid = 1
    def terminate(self): pass
    def kill(self): pass
    async def wait(self):
        await asyncio.sleep(0.2)  # outlasts the 10ms timer, like real winpty
        self.returncode = 0

class _GcRightAfterWakeupRegistered(asyncio.Future):
    # The task registers its wakeup here, inside its step with its context
    # entered; dropping the last session ref runs __del__ at exactly the
    # moment the live hang needed.
    def add_done_callback(self, fn, *, context=None):
        super().add_done_callback(fn, context=context)
        if holder:
            holder.pop()

async def step():
    s = tty_session.TTYSession("x")
    s._proc = _SlowProc()
    holder.append(s)
    del s
    loop = asyncio.get_running_loop()
    fut = _GcRightAfterWakeupRegistered(loop=loop)
    loop.call_later(0.01, fut.set_result, None)
    await fut
    print("resumed")

nest_asyncio.apply()
asyncio.run(step())
'''


def test_collecting_a_session_mid_step_does_not_strand_the_running_task():
    """The exact live freeze: the session is collected inside a task's step
    right after it registered its wakeup on a 10ms timer."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", _MID_STEP_SCRIPT, str(PROJECT_ROOT)],
        capture_output=True, text=True, timeout=30,
    )
    assert "already entered" not in result.stderr
    assert result.stdout.strip() == "resumed", result.stderr
