"""call_utility_model must not hang forever on a stalled provider call.

Observed live: a stalled LM Studio response left a turn stuck on
"Compressing history..." indefinitely - the event loop had nothing
scheduled to ever wake it, and only cancelling the turn (Nudge) recovered.
Traced to agent.py's call_utility_model awaiting model.unified_call()
directly with no timeout anywhere in that chain. Bounded with
asyncio.wait_for so a stalled provider raises a recoverable TimeoutError
instead of hanging the whole turn.

call_utility_model is decorated with @extension.extensible, which requires
a real Agent instance to look up registered hooks (helpers/extension.py's
_get_agent checks isinstance(..., Agent)). A plain duck-typed fake fails
that check and _get_agent returns None, which is fine here - it just means
no extension hooks fire, which is the point of testing the method in
isolation rather than the extension machinery.
"""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import Agent


class _Model:
    def __init__(self, delay: float = 0.0, result=("a response", "reasoning")):
        self.delay = delay
        self.result = result
        self.calls = 0

    async def unified_call(self, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


class _FakeAgent:
    """Not a real Agent instance - _get_agent's isinstance check fails on
    purpose so no extension hooks fire, keeping this a pure unit test of
    the timeout wrapping."""

    UTILITY_MODEL_TIMEOUT_SECONDS = Agent.UTILITY_MODEL_TIMEOUT_SECONDS
    rate_limiter_callback = None

    class _Config:
        profile = ""

    class _Context:
        def get_data(self, key):
            return None

    def __init__(self, model):
        self._model = model
        self.config = self._Config()
        self.context = self._Context()

    def get_utility_model(self):
        return self._model


@pytest.mark.asyncio
async def test_a_fast_response_is_returned_normally():
    agent = _FakeAgent(_Model(delay=0.0))
    response = await Agent.call_utility_model(agent, system="sys", message="msg")
    assert response == "a response"


@pytest.mark.asyncio
async def test_a_stalled_provider_raises_timeout_instead_of_hanging_forever():
    agent = _FakeAgent(_Model(delay=999999))
    agent.UTILITY_MODEL_TIMEOUT_SECONDS = 0.05

    with pytest.raises(TimeoutError):
        await Agent.call_utility_model(agent, system="sys", message="msg")


@pytest.mark.asyncio
async def test_a_slow_but_within_budget_response_still_completes():
    agent = _FakeAgent(_Model(delay=0.05))
    agent.UTILITY_MODEL_TIMEOUT_SECONDS = 1.0

    response = await Agent.call_utility_model(agent, system="sys", message="msg")
    assert response == "a response"
