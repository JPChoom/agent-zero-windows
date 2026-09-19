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
    """Each test gets a clean slate - the module caches a semaphore per
    backend key, and tests deliberately vary the configured limit."""
    def _clear():
        model_concurrency._state.clear()

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
    first_semaphore = model_concurrency._state[model_concurrency.DEFAULT_BACKEND_KEY]["semaphore"]

    _patch_limit(monkeypatch, 3)
    async with model_concurrency.model_call_slot():
        pass
    second_semaphore = model_concurrency._state[model_concurrency.DEFAULT_BACKEND_KEY]["semaphore"]

    assert first_semaphore is not second_semaphore
    assert second_semaphore._value == 3


# ------------------------------------------------------------------
# backend_key - identifying which backend a call actually contends for
# ------------------------------------------------------------------


def test_backend_key_combines_api_base_and_model_name():
    assert (
        model_concurrency.backend_key("lm_studio/qwen", {"api_base": "http://127.0.0.1:1234/v1"})
        == "http://127.0.0.1:1234/v1|lm_studio/qwen"
    )


def test_backend_key_distinguishes_two_models_on_the_same_server():
    """The actual bug this must avoid: LM Studio (and similar local
    servers) serve every loaded model through one shared port, so a chat
    model and a utility model pointed at two different models on that
    same server must still get different keys - api_base alone would
    conflate them and serialize two genuinely independent, concurrently
    loaded inference engines."""
    same_base = {"api_base": "http://127.0.0.1:1234/v1"}
    key_a = model_concurrency.backend_key("qwen3-27b", same_base)
    key_b = model_concurrency.backend_key("qwen3.5-4b", same_base)
    assert key_a != key_b


def test_backend_key_falls_back_to_model_name_without_api_base():
    assert model_concurrency.backend_key("lm_studio/qwen", {}) == "lm_studio/qwen"
    assert model_concurrency.backend_key("lm_studio/qwen", None) == "lm_studio/qwen"


def test_backend_key_falls_back_to_default_when_nothing_identifies_it():
    assert model_concurrency.backend_key("", {}) == model_concurrency.DEFAULT_BACKEND_KEY


# ------------------------------------------------------------------
# Per-backend keying - the actual point of this module: two distinct
# backends must not serialize against each other, only calls that
# genuinely share one.
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_different_backend_keys_run_concurrently(monkeypatch):
    """The whole point: a stock config points chat and utility at the
    identical local server (same key, correctly serialized below), but a
    second, distinct backend - a different model/api_base loaded for
    utility work - must not be blocked by the first at all."""
    _patch_limit(monkeypatch, 1)

    active: dict[str, int] = {}
    max_active: dict[str, int] = {}

    async def _job(key):
        async with model_concurrency.model_call_slot(key):
            active[key] = active.get(key, 0) + 1
            max_active[key] = max(max_active.get(key, 0), active[key])
            await asyncio.sleep(0.1)
            active[key] -= 1

    both_active_at_once = []

    async def _watch():
        for _ in range(20):
            await asyncio.sleep(0.01)
            if active.get("backend-a", 0) and active.get("backend-b", 0):
                both_active_at_once.append(True)

    await asyncio.gather(_job("backend-a"), _job("backend-b"), _watch())

    assert max_active["backend-a"] == 1
    assert max_active["backend-b"] == 1
    assert both_active_at_once, "two distinct backends must be able to overlap in time"


@pytest.mark.asyncio
async def test_the_same_backend_key_still_serializes(monkeypatch):
    """The regression this keying must not introduce: a stock config where
    chat and utility share one backend must keep serializing exactly as
    the old global semaphore did."""
    _patch_limit(monkeypatch, 1)

    active = 0
    max_active = 0

    async def _job():
        nonlocal active, max_active
        async with model_concurrency.model_call_slot("shared-backend"):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(_job(), _job(), _job())

    assert max_active == 1


@pytest.mark.asyncio
async def test_default_key_keeps_pre_keying_behavior_for_untagged_callers(monkeypatch):
    """Callers that don't specify a key (none remain in this codebase, but
    the parameter has a default) must still get full serialization against
    each other, matching the original single-global-semaphore behavior."""
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

    await asyncio.gather(_job(), _job())

    assert max_active == 1


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
            results[key] = id(model_concurrency._get_semaphore(model_concurrency.DEFAULT_BACKEND_KEY))

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


@pytest.mark.asyncio
async def test_unified_call_does_not_serialize_across_distinct_backends(monkeypatch):
    """The actual point of keying by backend: a chat model and a utility
    model configured with different api_base values (a second, distinct
    server loaded for utility work) must run concurrently through
    unified_call - not just at the model_concurrency layer in isolation."""
    import models

    _patch_limit(monkeypatch, 1)

    active: dict[str, int] = {}
    both_active_at_once = []

    class _FakeTransport:
        def __init__(self, *a, kwargs=None, **k):
            self._api_base = (kwargs or {}).get("api_base", "")

        async def acomplete(self):
            key = self._api_base
            active[key] = active.get(key, 0) + 1
            if active.get("http://a") and active.get("http://b"):
                both_active_at_once.append(True)
            await asyncio.sleep(0.1)
            active[key] -= 1
            return {"response_delta": "ok", "reasoning_delta": ""}

    monkeypatch.setattr(models, "LiteLLMTransport", _FakeTransport)
    monkeypatch.setattr(models, "apply_rate_limiter", lambda *a, **k: _noop_async(None))
    monkeypatch.setattr(models, "configure_litellm", lambda: None)
    monkeypatch.setattr(
        models.settings, "get_settings", lambda: {"litellm_global_kwargs": {}}
    )

    chat_model = models.LiteLLMChatWrapper(
        model="model-a", provider="fake-provider", api_base="http://a"
    )
    utility_model = models.LiteLLMChatWrapper(
        model="model-b", provider="fake-provider", api_base="http://b"
    )

    await asyncio.gather(
        chat_model.unified_call(user_message="hi"),
        utility_model.unified_call(user_message="hi"),
    )

    assert both_active_at_once, "distinct backends must be able to run concurrently"


async def _noop_async(value):
    return value
