"""Local-speed B1/B2: background model work never holds up the user's turn.

Before: after every reply two memorize calls (each with up to 80k characters
of the whole chat) and their consolidation calls queued on the one local
model, and the next turn waited behind them - ~200 s across the 8-task
workflow benchmark.
"""

import asyncio
import threading
import time

import pytest

from helpers import model_concurrency as mc
from helpers import perf


@pytest.fixture(autouse=True)
def _limit_one(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "get_configured_limit", lambda: 1)
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))
    mc._state.clear()
    mc._activity.clear()
    yield
    mc._state.clear()
    mc._activity.clear()


# ------------------------------------------------------------ B2: priority

def test_turn_call_goes_before_a_waiting_background_call():
    order = []

    async def holder():
        async with mc.model_call_slot("k"):
            await asyncio.sleep(0.2)
            order.append("first turn call")

    async def background():
        await asyncio.sleep(0.02)
        async with mc.model_call_slot("k", background=True):
            order.append("background")

    async def turn():
        await asyncio.sleep(0.05)  # starts waiting after the background call
        async with mc.model_call_slot("k"):
            order.append("second turn call")

    async def run():
        await asyncio.gather(holder(), background(), turn())

    asyncio.run(run())
    assert order == ["first turn call", "second turn call", "background"]


def test_turn_call_interrupts_a_running_preemptible_background_call():
    events = []

    async def background():
        try:
            async with mc.model_call_slot("k", background=True, preemptible=True) as holder:
                events.append("background started")
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            events.append(f"background interrupted (preempted={holder.preempted})")

    async def turn():
        await asyncio.sleep(0.05)
        started = time.monotonic()
        async with mc.model_call_slot("k"):
            events.append(f"turn got the model after {time.monotonic() - started:.2f}s")

    async def run():
        await asyncio.gather(background(), turn())

    asyncio.run(run())
    assert events[0] == "background started"
    assert "background interrupted (preempted=True)" in events
    waited = float(events[-1].split("after ")[1].rstrip("s"))
    assert waited < 1.0


def test_non_preemptible_background_call_is_not_interrupted():
    events = []

    async def background():
        async with mc.model_call_slot("k", background=True, preemptible=False):
            await asyncio.sleep(0.2)
            events.append("background done")

    async def turn():
        await asyncio.sleep(0.05)
        async with mc.model_call_slot("k"):
            events.append("turn")

    async def run():
        await asyncio.gather(background(), turn())

    asyncio.run(run())
    assert events == ["background done", "turn"]


def test_preemption_reaches_a_background_call_on_another_thread():
    """Memorize runs on its own thread and event loop (DeferredTask)."""
    result = {}

    def background_thread():
        async def run():
            try:
                async with mc.model_call_slot("k", background=True, preemptible=True):
                    result["started"] = True
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                result["interrupted"] = True

        asyncio.run(run())

    thread = threading.Thread(target=background_thread)
    thread.start()
    while not result.get("started"):
        time.sleep(0.01)

    async def turn():
        started = time.monotonic()
        async with mc.model_call_slot("k"):
            return time.monotonic() - started

    waited = asyncio.run(turn())
    thread.join(timeout=5)
    assert result.get("interrupted") and waited < 1.0


@pytest.mark.asyncio
async def test_unified_call_turns_preemption_into_a_retryable_error(monkeypatch):
    import models

    class _SlowTransport:
        def __init__(self, *a, **k):
            pass

        async def acomplete(self):
            await asyncio.sleep(5)
            return {"response_delta": "late", "reasoning_delta": ""}

    class _FastTransport(_SlowTransport):
        async def acomplete(self):
            return {"response_delta": "ok", "reasoning_delta": ""}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(models, "apply_rate_limiter", _noop)
    monkeypatch.setattr(models, "configure_litellm", lambda: None)
    model = models.LiteLLMChatWrapper(model="m", provider="p")

    @perf.tagged("memorize_solutions", background=True)
    async def memorize():
        monkeypatch.setattr(models, "LiteLLMTransport", _SlowTransport)
        return await model.unified_call(user_message="history")

    async def turn():
        await asyncio.sleep(0.1)
        monkeypatch.setattr(models, "LiteLLMTransport", _FastTransport)
        return await model.unified_call(user_message="hi")

    background_task = asyncio.create_task(memorize())
    started = time.monotonic()
    reply, _ = await turn()
    assert reply == "ok" and time.monotonic() - started < 1.5
    with pytest.raises(mc.Preempted):
        await background_task
    assert not background_task.cancelled()  # a retryable error, not a cancelled task


def test_run_when_idle_waits_for_quiet_then_retries_after_preemption(monkeypatch):
    monkeypatch.setattr(mc, "_last_foreground", 0.0)
    calls = []

    async def make_call():
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise mc.Preempted("turn")
        return "done"

    async def run():
        return await mc.run_when_idle(make_call, settle_seconds=0.05)

    assert asyncio.run(run()) == "done"
    assert len(calls) == 2


def test_run_when_idle_gives_up_after_its_attempts(monkeypatch):
    monkeypatch.setattr(mc, "_last_foreground", 0.0)

    async def always_preempted():
        raise mc.Preempted("turn")

    with pytest.raises(mc.Preempted):
        asyncio.run(mc.run_when_idle(always_preempted, attempts=2, settle_seconds=0.01))


def test_wait_for_idle_holds_while_a_turn_call_runs():
    async def run():
        async def turn():
            async with mc.model_call_slot("k"):
                await asyncio.sleep(0.3)

        task = asyncio.create_task(turn())
        await asyncio.sleep(0.05)
        started = time.monotonic()
        await mc.wait_for_foreground_idle(settle_seconds=0.1)
        await task
        return time.monotonic() - started

    assert asyncio.run(run()) >= 0.3


# ------------------------------------------------------------ B1: only what is new

class _Agent:
    def __init__(self, history):
        self.history = history
        self._data = {}

    def get_data(self, key):
        return self._data.get(key)

    def set_data(self, key, value):
        self._data[key] = value


def _history():
    from helpers.history import History

    class _A:
        config = None

        def read_prompt(self, *a, **k):
            return ""

    history = History.__new__(History)
    History.__init__(history, agent=_A())
    return history


def test_memorize_sends_only_messages_since_the_last_time():
    from plugins._memory.helpers import memorize_scope as scope

    history = _history()
    for n in range(5):
        history.add_message(ai=False, content=f"old question {n} about printers")
        history.add_message(ai=True, content=f'{{"tool_name": "response", "tool_args": {{"text": "old answer {n}"}}}}')
    agent = _Agent(history)
    text, newest = scope.new_messages(agent, "fragments")
    assert "old question 0" in text  # first run: everything
    scope.mark_done(agent, "fragments", newest)

    history.add_message(ai=False, content="new question about Excel")
    history.add_message(ai=True, content='{"tool_name": "code_execution_tool", "tool_args": {"code": "x"}}')
    text, newest2 = scope.new_messages(agent, "fragments")
    assert "new question about Excel" in text and newest2 > newest
    # the two messages just before, for context - never the older turns
    assert "old question 4" in text and "old answer 4" in text
    assert "old question 3" not in text and "old question 0" not in text

def test_trivial_turns_are_skipped():
    from plugins._memory.helpers import memorize_scope as scope

    assert not scope.worth_memorizing("fragments", "hi there")
    long_chat = "user: tell me a joke " * 200
    assert scope.worth_memorizing("fragments", long_chat)
    assert not scope.worth_memorizing("solutions", long_chat + '"tool_name": "response"')
    assert scope.worth_memorizing("solutions", long_chat + '"tool_name": "code_execution_tool"')


def test_nothing_new_means_nothing_to_send():
    from plugins._memory.helpers import memorize_scope as scope

    history = _history()
    history.add_message(ai=False, content="question")
    agent = _Agent(history)
    _, newest = scope.new_messages(agent, "solutions")
    scope.mark_done(agent, "solutions", newest)
    assert scope.new_messages(agent, "solutions")[0] == ""
