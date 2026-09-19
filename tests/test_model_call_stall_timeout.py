"""_run_unified bounds every model call - streaming and non-streaming -
instead of leaving them as a bare await with no timeout anywhere in the
chain.

Observed live: a stalled LM Studio response left a turn stuck on
"Compressing history..." indefinitely. py-spy showed the event loop
parked on GetQueuedCompletionStatus with nothing scheduled to ever wake
it - only cancelling the turn (Nudge) recovered. The narrower fix
(agent.py's call_utility_model) only protected that one caller; this is
the structural version covering every unified_call/unified_turn caller,
including the main chat call, which had no protection at all before this.

Streaming uses an idle timeout (silence between chunks, not total
duration) since reasoning tokens count as chunks too - a genuinely
working slow generation keeps producing them. Non-streaming uses a
total-duration timeout since there's no concept of partial progress
there.

These tests fake models.LiteLLMTransport itself rather than the
acompletion/aresponses functions one layer down: _run_unified only
depends on transport.astream()/acomplete()/policy.using_responses, and
pinning the test boundary there keeps this a unit test of the timeout
and retry logic, independent of the transport's own chat-vs-Responses
provider selection.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import models


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch):
    monkeypatch.setattr(
        models.settings, "get_settings", lambda: {"litellm_global_kwargs": {}}
    )

    async def fake_rate_limiter(*args, **kwargs):
        return None

    monkeypatch.setattr(models, "apply_rate_limiter", fake_rate_limiter)


class _StallingAsyncChunkStream:
    """Never yields another chunk - mirrors a provider that accepted the
    request and then simply stopped responding, no error, no more data."""

    def __init__(self):
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(999)

    async def aclose(self):
        self.closed = True


class _WorkingAsyncChunkStream:
    def __init__(self, chunks: list[dict], delay: float = 0.0):
        self._chunks = chunks
        self.index = 0
        self.closed = False
        self.delay = delay

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self._chunks):
            raise StopAsyncIteration
        if self.delay:
            await asyncio.sleep(self.delay)
        chunk = self._chunks[self.index]
        self.index += 1
        return chunk

    async def aclose(self):
        self.closed = True


class _FakeTransport:
    """Stands in for LiteLLMTransport: _run_unified only touches astream(),
    acomplete(), and policy.using_responses."""

    def __init__(self, astream_factory=None, acomplete_factory=None):
        self._astream_factory = astream_factory
        self._acomplete_factory = acomplete_factory
        self.policy = SimpleNamespace(using_responses=False)
        self.last_result = None

    def astream(self):
        return self._astream_factory()

    async def acomplete(self):
        return await self._acomplete_factory()


def _install_fake_transport(monkeypatch, **kwargs):
    monkeypatch.setattr(models, "LiteLLMTransport", lambda **_: _FakeTransport(**kwargs))


def _chunk_dict(text: str) -> dict:
    """Already-parsed ChatChunk shape (see helpers/litellm_transport.py's
    ChatChunk) - the fake transport's astream() bypasses the real parser,
    so chunks here must be pre-parsed rather than raw litellm deltas."""
    return {"reasoning_delta": "", "response_delta": text}


def _wrapper():
    return models.LiteLLMChatWrapper(model="test-model", provider="openai", model_config=None)


async def _noop_callback(chunk: str, full: str):
    return None


@pytest.mark.asyncio
async def test_a_stalled_stream_times_out_instead_of_hanging_forever(monkeypatch):
    stream = _StallingAsyncChunkStream()
    _install_fake_transport(monkeypatch, astream_factory=lambda: stream)

    with pytest.raises(TimeoutError):
        await _wrapper().unified_call(
            messages=[],
            response_callback=_noop_callback,
            a0_stream_idle_timeout_seconds=0.05,
            a0_retry_attempts=0,
        )

    assert stream.closed is True, "the abandoned stream must be closed, not leaked"


@pytest.mark.asyncio
async def test_a_stalled_non_streaming_call_times_out(monkeypatch):
    async def stalled():
        await asyncio.sleep(999)

    _install_fake_transport(monkeypatch, acomplete_factory=stalled)

    with pytest.raises(TimeoutError):
        await _wrapper().unified_call(
            messages=[],
            a0_total_timeout_seconds=0.05,
            a0_retry_attempts=0,
        )


@pytest.mark.asyncio
async def test_a_slow_but_progressing_stream_is_not_killed(monkeypatch):
    """The idle timeout must not fire as long as new chunks keep arriving,
    even if each individual gap is a meaningful fraction of the timeout -
    this is what distinguishes it from a flat total-duration cap."""
    chunks = [_chunk_dict("a"), _chunk_dict("b"), _chunk_dict("c")]
    stream = _WorkingAsyncChunkStream(chunks, delay=0.03)
    _install_fake_transport(monkeypatch, astream_factory=lambda: stream)

    response, _reasoning = await _wrapper().unified_call(
        messages=[],
        response_callback=_noop_callback,
        a0_stream_idle_timeout_seconds=0.1,
    )

    assert response == "abc"


@pytest.mark.asyncio
async def test_a_stall_with_no_chunks_yet_is_retried_automatically(monkeypatch):
    """A timeout is treated as a transient error (models._is_transient_
    litellm_error), so a one-off stall - the common case observed live -
    self-heals via the existing retry loop instead of surfacing at all."""
    attempts = {"n": 0}
    working_stream = _WorkingAsyncChunkStream([_chunk_dict("ok")])

    def astream_factory():
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _StallingAsyncChunkStream()
        return working_stream

    _install_fake_transport(monkeypatch, astream_factory=astream_factory)

    response, _reasoning = await _wrapper().unified_call(
        messages=[],
        response_callback=_noop_callback,
        a0_stream_idle_timeout_seconds=0.05,
        a0_retry_attempts=1,
        a0_retry_delay_seconds=0.01,
    )

    assert response == "ok"
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_a_stall_after_partial_chunks_is_not_retried(monkeypatch):
    """Matches the pre-existing retry rule: once any chunk has arrived,
    retrying from scratch would discard real partial progress, so the
    stall must surface immediately instead."""

    class _PartialThenStallStream:
        def __init__(self):
            self._sent = False
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return _chunk_dict("partial")
            await asyncio.sleep(999)

        async def aclose(self):
            self.closed = True

    stream = _PartialThenStallStream()
    _install_fake_transport(monkeypatch, astream_factory=lambda: stream)

    with pytest.raises(TimeoutError):
        await _wrapper().unified_call(
            messages=[],
            response_callback=_noop_callback,
            a0_stream_idle_timeout_seconds=0.05,
            a0_retry_attempts=5,
            a0_retry_delay_seconds=0.01,
        )


def test_the_structural_defaults_exist_and_are_generous():
    """These are what every caller gets without opting in - the whole
    point of making this structural rather than per-call-site. Sanity
    bounds only: long enough not to cut off a legitimate slow reasoning
    generation, short enough to actually recover within a session."""
    assert 30 <= models.DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS <= 600
    assert 60 <= models.DEFAULT_TOTAL_CALL_TIMEOUT_SECONDS <= 900
