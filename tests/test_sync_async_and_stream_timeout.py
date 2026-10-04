"""helpers/sync_async.run_sync never nests event loops, and the LangChain
_astream path gives up on a silent provider instead of holding the backend's
model-call slot forever."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers.sync_async import run_sync


async def _which_thread():
    await asyncio.sleep(0)
    return threading.current_thread().name


def test_run_sync_without_a_running_loop_runs_inline():
    assert run_sync(_which_thread()) == threading.current_thread().name


@pytest.mark.asyncio
async def test_run_sync_inside_a_running_loop_uses_a_separate_loop():
    outer_loop = asyncio.get_running_loop()

    async def probe():
        return asyncio.get_running_loop() is not outer_loop, threading.current_thread().name

    separate, name = run_sync(probe())
    assert separate is True
    assert name.startswith("run_sync")


@pytest.mark.asyncio
async def test_astream_times_out_on_a_silent_provider(monkeypatch):
    import models

    class _SilentTransport:
        def __init__(self, **kwargs):
            pass

        async def astream(self):
            yield {"response_delta": "", "reasoning_delta": ""}
            await asyncio.sleep(3600)  # provider goes silent mid-stream

    monkeypatch.setattr(models, "LiteLLMTransport", _SilentTransport)
    monkeypatch.setattr(models, "configure_litellm", lambda: None)

    async def _no_limit(*a, **k):
        return None

    monkeypatch.setattr(models, "apply_rate_limiter", _no_limit)

    wrapper = models.LiteLLMChatWrapper.__new__(models.LiteLLMChatWrapper)
    object.__setattr__(wrapper, "__dict__", {})
    wrapper.__dict__.update(model_name="test/model", kwargs={"a0_stream_idle_timeout_seconds": 0.2}, a0_model_conf=None)
    monkeypatch.setattr(models.LiteLLMChatWrapper, "_convert_messages", lambda self, m, **k: [], raising=False)

    async def consume():
        async for _ in wrapper._astream([]):
            pass

    with pytest.raises(TimeoutError, match="stalled"):
        await asyncio.wait_for(consume(), timeout=5)
