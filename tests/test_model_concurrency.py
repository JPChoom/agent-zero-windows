"""Tests for helpers/model_concurrency.py (Phase H): the shared semaphore
that serializes concurrent Main/Utility model calls, and its wiring into
models.py's unified_call()/_astream().

The semaphore is process-wide and thread-safe. A bare module-level
asyncio.Semaphore crashed for real ("RuntimeError: ... is bound to a
different event loop") when plugins/_memory's end-of-turn "memorize
solutions" extension - which runs on its own background thread via
helpers/defer.py's DeferredTask, with its own event loop - contended for
the instance the main server loop had already bound.

Keying state by loop id fixed the crash but gave each loop its own
independent limit, so the case that most needed serializing (a background
extension calling the model while the main loop is mid-request) was never
serialized at all. These tests now assert the opposite of that: one
semaphore, shared across threads and loops.
"""

import asyncio
import threading

import pytest

from helpers import model_concurrency


@pytest.fixture(autouse=True)
def _reset_semaphore_state():
    """Each test gets a clean slate - the module caches the semaphore,
    and tests deliberately vary the configured limit."""
    def _clear():
        model_concurrency._state["semaphore"] = None
        model_concurrency._state["limit"] = None

    _clear()
    yield
    _clear()


def _patch_limit(monkeypatch, limit: int) -> None:
    monkeypatch.setattr(model_concurrency, "get_configured_limit", lambda: limit)


# ------------------------------------------------------------------
# get_configured_limit
# ------------------------------------------------------------------

def test_get_configured_limit_defaults_to_one_on_error(monkeypatch):
    import plugins._model_config.helpers.model_config as model_config_module

    def _raise(*args, **kwargs):
        raise RuntimeError("plugin config unavailable")

    monkeypatch.setattr(model_config_module, "get_config", _raise)

    assert model_concurrency.get_configured_limit() == 1


def test_get_configured_limit_reads_stored_value(monkeypatch):
    import plugins._model_config.helpers.model_config as model_config_module

    monkeypatch.setattr(model_config_module, "get_config", lambda: {"max_concurrent_model_calls": 4})

    assert model_concurrency.get_configured_limit() == 4


def test_get_configured_limit_treats_non_positive_as_one(monkeypatch):
    import plugins._model_config.helpers.model_config as model_config_module

    monkeypatch.setattr(model_config_module, "get_config", lambda: {"max_concurrent_model_calls": 0})

    assert model_concurrency.get_configured_limit() == 1


def test_get_configured_limit_treats_garbled_value_as_one(monkeypatch):
    import plugins._model_config.helpers.model_config as model_config_module

    monkeypatch.setattr(model_config_module, "get_config", lambda: {"max_concurrent_model_calls": "banana"})

    assert model_concurrency.get_configured_limit() == 1


# ------------------------------------------------------------------
# model_call_slot - actual serialization behavior
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_call_slot_serializes_calls_when_limit_is_one(monkeypatch):
    _patch_limit(monkeypatch, 1)

    active = 0
    max_active = 0

    async def _job():
        nonlocal active, max_active
        async with model_concurrency.model_call_slot():
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(_job(), _job(), _job())

    assert max_active == 1


@pytest.mark.asyncio
async def test_model_call_slot_allows_up_to_configured_limit_concurrently(monkeypatch):
    _patch_limit(monkeypatch, 2)

    active = 0
    max_active = 0

    async def _job():
        nonlocal active, max_active
        async with model_concurrency.model_call_slot():
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(_job(), _job(), _job(), _job())

    assert max_active == 2


@pytest.mark.asyncio
async def test_model_call_slot_releases_on_exception(monkeypatch):
    _patch_limit(monkeypatch, 1)

    with pytest.raises(ValueError):
        async with model_concurrency.model_call_slot():
            raise ValueError("boom")

    # The slot must have been released - a second acquire must not hang.
    async def _job():
        async with model_concurrency.model_call_slot():
            pass

    await asyncio.wait_for(_job(), timeout=1)


@pytest.mark.asyncio
async def test_semaphore_recreated_when_configured_limit_changes(monkeypatch):
    _patch_limit(monkeypatch, 1)
    async with model_concurrency.model_call_slot():
        pass
    first_semaphore = model_concurrency._state["semaphore"]

    _patch_limit(monkeypatch, 3)
    async with model_concurrency.model_call_slot():
        pass
    second_semaphore = model_concurrency._state["semaphore"]

    assert first_semaphore is not second_semaphore
    assert second_semaphore._value == 3


# ------------------------------------------------------------------
# Cross-event-loop safety - the actual bug reproduced from a real user
# log (plugins/_memory's background-thread "memorize solutions"
# extension crashing the main server's next model call)
# ------------------------------------------------------------------

def test_every_loop_shares_one_semaphore():
    """The regression that mattered: per-loop state meant a background
    thread and the main loop each had their own limit, so neither ever
    waited for the other."""
    results = {}

    def run_in_new_loop(key):
        async def go():
            results[key] = id(model_concurrency._get_semaphore())

        asyncio.run(go())

    t1 = threading.Thread(target=run_in_new_loop, args=("loop_a",))
    t2 = threading.Thread(target=run_in_new_loop, args=("loop_b",))
    t1.start()
    t1.join()
    t2.start()
    t2.join()

    assert results["loop_a"] == results["loop_b"]


def test_a_background_thread_waits_for_the_main_loop(monkeypatch):
    """The live failure this fixes: plugins/_memory's "memorize solutions"
    extension ran on its own loop and called the model while the main loop
    was mid-request. Both hit LM Studio at once and both came back
    "Context size has been exceeded", though either alone fits the window.
    With one limit=1 semaphore across the process, the second call must
    wait rather than overlap."""
    _patch_limit(monkeypatch, 1)
    overlapped = []
    active = []
    started = threading.Event()

    async def hold(tag, seconds):
        async with model_concurrency.model_call_slot():
            active.append(tag)
            if len(active) > 1:
                overlapped.append(tuple(active))
            await asyncio.sleep(seconds)
            active.remove(tag)

    def background():
        started.wait(timeout=5)
        asyncio.run(hold("background", 0.05))

    thread = threading.Thread(target=background)
    thread.start()

    async def main_loop_work():
        async with model_concurrency.model_call_slot():
            active.append("main")
            started.set()          # let the other thread try while we hold it
            await asyncio.sleep(0.2)
            if len(active) > 1:
                overlapped.append(tuple(active))
            active.remove("main")

    asyncio.run(main_loop_work())
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert overlapped == [], f"calls overlapped across threads: {overlapped}"


def test_acquiring_does_not_block_the_event_loop(monkeypatch):
    """A blocking acquire inside a coroutine would freeze the whole loop -
    including the coroutine holding the slot being waited on, which is a
    deadlock rather than a delay. Other tasks must keep running while a
    call waits for its slot."""
    _patch_limit(monkeypatch, 1)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.01)
                ticks += 1

        async def holder():
            async with model_concurrency.model_call_slot():
                await asyncio.sleep(0.15)

        async def waiter():
            await asyncio.sleep(0.02)   # ensure holder goes first
            async with model_concurrency.model_call_slot():
                pass

        t = asyncio.ensure_future(ticker())
        await asyncio.gather(holder(), waiter())
        t.cancel()
        return ticks

    ticks = asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    assert ticks > 5, f"loop appears to have stalled while waiting (ticks={ticks})"


def test_model_call_slot_works_from_a_background_thread_with_its_own_loop(monkeypatch):
    """End-to-end reproduction of the actual crash: use model_call_slot()
    on the main loop first (as agent.py's normal chat/utility calls do),
    then from a separate thread with its own fresh event loop (matching
    helpers/defer.py's DeferredTask, which plugins/_memory's "memorize
    solutions" extension uses to run in the background). Must not raise."""
    _patch_limit(monkeypatch, 1)

    async def use_slot():
        async with model_concurrency.model_call_slot():
            await asyncio.sleep(0.01)
        return "ok"

    asyncio.run(use_slot())  # main-loop-equivalent use, establishes state first

    result: dict = {}

    def background_thread_with_own_loop():
        try:
            result["value"] = asyncio.run(use_slot())
        except Exception as exc:  # pragma: no cover - failure path under test
            result["error"] = repr(exc)

    thread = threading.Thread(target=background_thread_with_own_loop)
    thread.start()
    thread.join(timeout=5)

    assert "error" not in result, f"cross-loop crash reproduced: {result.get('error')}"
    assert result.get("value") == "ok"


# ------------------------------------------------------------------
# models.py wiring - unified_call and _astream both hold the slot
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unified_call_holds_model_call_slot(monkeypatch):
    """Doesn't exercise a real model - just confirms unified_call's retry
    loop is wrapped in model_call_slot() by observing the slot is held
    (max concurrency 1) while two calls race against each other."""
    import models

    _patch_limit(monkeypatch, 1)

    active = 0
    max_active = 0

    class _FakeTransport:
        def __init__(self, *a, **k):
            pass

        async def acomplete(self):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {"response_delta": "ok", "reasoning_delta": ""}

    monkeypatch.setattr(models, "LiteLLMTransport", _FakeTransport)
    monkeypatch.setattr(models, "apply_rate_limiter", lambda *a, **k: _noop_async(None))
    monkeypatch.setattr(models, "configure_litellm", lambda: None)

    chat_model = models.LiteLLMChatWrapper(model="fake-model", provider="fake-provider")

    async def _call():
        await chat_model.unified_call(user_message="hi")

    await asyncio.gather(_call(), _call())

    assert max_active == 1


async def _noop_async(value):
    return value
