"""Tests for helpers/model_concurrency.py (Phase H): the shared semaphore
that serializes concurrent Main/Utility model calls, and its wiring into
models.py's unified_call()/_astream().
"""

import asyncio

import pytest

from helpers import model_concurrency


@pytest.fixture(autouse=True)
def _reset_semaphore_state():
    """Each test gets a clean slate - the module caches the semaphore
    keyed by configured limit, and tests deliberately vary that limit."""
    model_concurrency._semaphore = None
    model_concurrency._semaphore_limit = None
    yield
    model_concurrency._semaphore = None
    model_concurrency._semaphore_limit = None


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
    first_semaphore = model_concurrency._semaphore

    _patch_limit(monkeypatch, 3)
    async with model_concurrency.model_call_slot():
        pass
    second_semaphore = model_concurrency._semaphore

    assert first_semaphore is not second_semaphore
    assert second_semaphore._value == 3


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
