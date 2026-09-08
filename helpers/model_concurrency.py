"""Serializes concurrent Main/Utility model calls through a single
global semaphore (default 1 - fully serialized), configurable via
_model_config's own settings.

Real-world motivation: a local single-process inference backend (LM
Studio, etc.) doesn't reliably handle multiple concurrent requests - this
fork has observed transient "Engine protocol predict request failed:
fetch failed" errors from LM Studio during live testing, consistent with
request contention rather than a genuine outage (the existing retry logic
in models.py's unified_call() already recovers from it, but avoiding the
contention in the first place is better than retrying around it).

Concurrent model calls are a real possibility in this fork despite each
Agent's own monologue loop being single-threaded: helpers/parallel_tools.py's
"parallel" tool spawns independent worker Agent instances that each run
their own monologue concurrently via asyncio tasks (see that module's
_run_direct_tool_job/_run_subordinate_context_job), and each could call
the model at the same moment.

Wraps two call surfaces in models.py: unified_call(), the choke point
this fork's own agent.py chat/utility-model calls funnel through
(confirmed during this fork's independent-reviewer work - see
plugins/_coding_controller/helpers/reviewer.py), and _astream(), the
LangChain-compatible async interface some plugins reach through
helpers/call_llm.py's chain.astream(). No other call site needs to know
this module exists - both wrap it internally.

Process-wide, and deliberately not an asyncio primitive. asyncio.Lock/
Semaphore bind to whichever running loop first uses them (raising
RuntimeError: "... is bound to a different event loop" if a second loop
touches the same instance), and this fork genuinely has more than one
loop in play: plugins/_memory's end-of-turn "memorize solutions"
extension runs on its own background thread via helpers/defer.py's
DeferredTask, with its own event loop, separate from the main server
loop. A bare module-level asyncio.Semaphore crashed the first time that
background thread called the model.

An earlier fix keyed the semaphore by running-loop id, which stopped the
crash but left each loop with its own independent limit - so the one case
that most needed serializing, a background extension calling the model
while the main loop is mid-request, was never serialized at all. Observed
live: a 39k-token main call and a concurrent "memorize solutions" call
both failing with LM Studio's "Context size has been exceeded" while
either alone fits the 65k window comfortably, consistent with the server
dividing its context across simultaneous requests.

So the semaphore is a threading.Semaphore, shared by the whole process
and safe to touch from any thread. It is acquired without blocking:
blocking a thread inside a coroutine would stall that entire event loop,
including whichever other coroutine currently holds the slot, so this
polls with a non-blocking acquire and an awaited sleep between attempts.
The uncontended path takes the first non-blocking acquire and never
sleeps at all; contended waiters back off from 20ms to 200ms, which is
noise next to a model call and costs no executor threads (asyncio.to_thread
would consume one per waiter and can deadlock against its own bounded
pool when the limit is small).
"""

import asyncio
import contextlib

import threading

# Guards the singleton below. A plain threading.Lock because it is touched
# from arbitrary threads and held only for a couple of assignments.
_state_lock = threading.Lock()
_state: dict = {"semaphore": None, "limit": None}

_POLL_MIN_SECONDS = 0.02
_POLL_MAX_SECONDS = 0.2


def get_configured_limit() -> int:
    """Reads _model_config's max_concurrent_model_calls setting.
    Deferred import - plugins._model_config.helpers.model_config imports
    models.py, and models.py imports this module, so importing it at this
    module's top level would be a circular import; importing it lazily
    here (only once both modules are already loaded, at call time) avoids
    that without needing to break either side's own natural dependency."""
    try:
        from plugins._model_config.helpers import model_config

        cfg = model_config.get_config()
        limit = int(cfg.get("max_concurrent_model_calls", 1))
    except Exception:
        return 1
    return limit if limit > 0 else 1


def _get_semaphore() -> threading.Semaphore:
    """The one semaphore every thread and every loop shares."""
    limit = get_configured_limit()
    with _state_lock:
        if _state["semaphore"] is None or _state["limit"] != limit:
            # Recreates the semaphore when the configured limit changes
            # rather than trying to mutate an existing one's capacity
            # (Semaphore doesn't support that). A call already holding a
            # slot on the old semaphore keeps running under the old limit
            # until it finishes, and releases the object it acquired - a
            # brief, harmless transition window for what is a
            # politeness/contention-avoidance measure, not a hard
            # security control.
            _state["semaphore"] = threading.Semaphore(limit)
            _state["limit"] = limit
        return _state["semaphore"]


async def _acquire(semaphore: threading.Semaphore) -> None:
    """Take a slot without blocking the event loop.

    semaphore.acquire() would block the whole loop, including the
    coroutine holding the slot we are waiting on - a deadlock, not just a
    stall. The non-blocking attempt comes first so an uncontended call
    never sleeps.
    """
    if semaphore.acquire(blocking=False):
        return
    delay = _POLL_MIN_SECONDS
    while True:
        await asyncio.sleep(delay)
        if semaphore.acquire(blocking=False):
            return
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)


@contextlib.asynccontextmanager
async def model_call_slot():
    """Async context manager: `async with model_call_slot(): ...` around
    the actual network call. Held only for the duration of the call
    itself, not message construction or rate-limiter bookkeeping."""
    semaphore = _get_semaphore()
    await _acquire(semaphore)
    try:
        yield
    finally:
        # Release the object that was acquired, not whatever _get_semaphore
        # would hand back now - the limit may have changed in between.
        semaphore.release()
