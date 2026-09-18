"""Tests for helpers.debounced.run_debounced.

This is applied to three real filesystem-walking extension call sites
(see helpers/debounced.py's module docstring), so correctness here is
correctness in all three at once.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import debounced


@pytest.fixture(autouse=True)
def _clear_cache():
    debounced.clear()
    yield
    debounced.clear()


@pytest.mark.asyncio
async def test_the_function_actually_runs_and_returns_its_result():
    async def go():
        return await debounced.run_debounced("k1", 60, lambda: 42)

    assert await go() == 42


@pytest.mark.asyncio
async def test_a_second_call_within_ttl_reuses_the_cached_result():
    calls = []

    def work():
        calls.append(1)
        return len(calls)

    first = await debounced.run_debounced("k2", 60, work)
    second = await debounced.run_debounced("k2", 60, work)

    assert first == second == 1
    assert len(calls) == 1, "work() must not run twice within the ttl"


@pytest.mark.asyncio
async def test_a_call_after_the_ttl_expires_runs_again():
    calls = []

    def work():
        calls.append(1)
        return len(calls)

    await debounced.run_debounced("k3", 0.05, work)
    await asyncio.sleep(0.1)
    second = await debounced.run_debounced("k3", 0.05, work)

    assert second == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_different_keys_never_share_a_cache_entry():
    def work():
        return "value"

    await debounced.run_debounced("a", 60, work)
    await debounced.run_debounced("b", 60, work)

    # Both present independently - the real point is a config change
    # (different max_depth, different profile, ...) must not silently
    # reuse a stale result computed under different parameters.
    assert debounced._cache["a"][1] == "value"
    assert debounced._cache["b"][1] == "value"
    assert "a" in debounced._cache and "b" in debounced._cache


@pytest.mark.asyncio
async def test_the_function_runs_on_a_worker_thread_not_the_event_loop():
    """The entire point: a slow call must not block the loop. Proven by
    running something else concurrently and confirming it makes progress
    while the "slow" work is in flight."""
    calling_thread = {}

    def slow_work():
        calling_thread["id"] = threading.get_ident()
        time.sleep(0.2)
        return "done"

    ticks = []

    async def ticker():
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks.append(1)

    result, _ = await asyncio.gather(
        debounced.run_debounced("k4", 60, slow_work),
        ticker(),
    )

    assert result == "done"
    assert calling_thread["id"] != threading.get_ident()
    assert len(ticks) >= 5, (
        "the event loop must keep making progress while the blocking "
        "call is in flight, not stall for its whole duration"
    )


@pytest.mark.asyncio
async def test_concurrent_callers_for_the_same_key_do_not_duplicate_work():
    """A thundering herd: several turns arrive for the same key while a
    walk is already in flight. Only one walk should actually happen."""
    calls = []

    def work():
        calls.append(1)
        time.sleep(0.05)
        return "shared-result"

    results = await asyncio.gather(
        debounced.run_debounced("k5", 60, work),
        debounced.run_debounced("k5", 60, work),
        debounced.run_debounced("k5", 60, work),
    )

    assert results == ["shared-result"] * 3
    assert len(calls) == 1, "concurrent callers for one key must share one run"


@pytest.mark.asyncio
async def test_arguments_are_forwarded_to_the_wrapped_function():
    def work(a, b, c=None):
        return (a, b, c)

    result = await debounced.run_debounced("k6", 60, work, 1, 2, c=3)
    assert result == (1, 2, 3)


@pytest.mark.asyncio
async def test_an_exception_propagates_and_is_not_cached():
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await debounced.run_debounced("k7", 60, boom)

    # A failed attempt must not poison the cache - the next call should
    # try again, not silently return nothing forever.
    with pytest.raises(ValueError):
        await debounced.run_debounced("k7", 60, boom)

    assert len(calls) == 2


def test_clear_removes_a_specific_key_without_touching_others():
    debounced._cache["x"] = (time.monotonic(), "vx")
    debounced._cache["y"] = (time.monotonic(), "vy")

    debounced.clear("x")

    assert "x" not in debounced._cache
    assert "y" in debounced._cache


def test_clear_with_no_key_removes_everything():
    debounced._cache["x"] = (time.monotonic(), "vx")
    debounced._locks["x"] = asyncio.Lock()

    debounced.clear()

    assert debounced._cache == {}
    assert debounced._locks == {}
