"""Serializes concurrent Main/Utility model calls through a semaphore
per inference backend (default limit 1 per backend - fully serialized
within a backend), configurable via _model_config's own settings.

Keyed by backend, not global: chat_model and utility_model commonly
point at the exact same local server (confirmed live - a stock config
has both set to the identical model/api_base), in which case they
correctly share one semaphore and stay serialized, since they are
genuinely the same single-process inference engine underneath. But nothing
before this keying ever let two *different* backends - a second, smaller
model loaded for utility work on its own server, or a distinct cloud
provider - run concurrently: every call anywhere shared the one global
semaphore regardless of which backend it was actually going to, so a
slow utility call always blocked the main chat call even when they had
no server in common to contend over. The key combines the model's
api_base with its model name (see backend_key()) - api_base alone is
not enough, since a server like LM Studio serves every model it has
loaded through one shared port, so two different models loaded on the
same server would otherwise look like one backend and get serialized
against each other despite being independent, concurrently loaded
inference engines.

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

So each backend's semaphore is a threading.Semaphore, shared by the whole
process and safe to touch from any thread. It is acquired without blocking:
blocking a thread inside a coroutine would stall that entire event loop,
including whichever other coroutine currently holds the slot, so this
polls with a non-blocking acquire and an awaited sleep between attempts.
The uncontended path takes the first non-blocking acquire and never
sleeps at all; contended waiters back off from 20ms to 200ms, which is
noise next to a model call and costs no executor threads (asyncio.to_thread
would consume one per waiter and can deadlock against its own bounded
pool when the limit is small).

Priority (local-speed item B2). Calls made for the user's turn come first;
background work (memorizing, naming the chat - tagged with perf.tagged(...,
background=True)) only takes a free slot when no turn call is waiting for
that backend. A *preemptible* background call that is already running is
interrupted when a turn call needs its slot: the holder's task is cancelled
on its own loop and models.py turns that into `Preempted`, which the caller
(the memorize extensions) answers by waiting for the user to be idle and
trying again. Measured before this: background calls queued ahead of the
next turn cost ~200 s of waiting across the 8-task workflow benchmark.
"""

import asyncio
import contextlib
import threading
import time
from dataclasses import dataclass, field

# Guards the dict below. A plain threading.Lock because it is touched
# from arbitrary threads and held only for a couple of assignments.
_state_lock = threading.Lock()
# One entry per backend key, each independently tracking its own
# semaphore and the limit it was built with (so a configured-limit change
# is detected per backend, same as the old single-entry behavior was).
_state: dict[str, dict] = {}

_POLL_MIN_SECONDS = 0.02
_POLL_MAX_SECONDS = 0.2

DEFAULT_BACKEND_KEY = "default"


class Preempted(Exception):
    """A background model call gave its slot to a call for the user's turn.

    Raised by models.py only for calls started with preemptible=True; the
    caller should wait (wait_for_foreground_idle) and try again later.
    """


@dataclass
class _Holder:
    """A preemptible background call currently holding a slot."""
    loop: asyncio.AbstractEventLoop
    task: asyncio.Task
    preempted: bool = False


@dataclass
class _Activity:
    waiting: int = 0          # turn calls waiting for a slot
    active: int = 0           # turn calls holding a slot
    holders: list = field(default_factory=list)  # preemptible background holders


# Per backend key; guarded by _state_lock.
_activity: dict[str, _Activity] = {}
# Last moment any turn call was waiting or running, any backend (monotonic).
_last_foreground = 0.0


def _act(key: str) -> _Activity:
    entry = _activity.get(key)
    if entry is None:
        entry = _activity[key] = _Activity()
    return entry


def foreground_busy() -> bool:
    """Is a call for someone's turn waiting or running on any backend?"""
    with _state_lock:
        return any(a.waiting or a.active for a in _activity.values())


async def wait_for_foreground_idle(settle_seconds: float = 3.0, max_wait_seconds: float | None = None) -> bool:
    """Wait until no turn call has waited or run for `settle_seconds`.

    Background work calls this before starting, so it runs in the gaps
    between turns rather than in front of them. Returns False if
    `max_wait_seconds` ran out first (the caller may go ahead anyway).
    """
    started = time.monotonic()
    while True:
        now = time.monotonic()
        if foreground_busy():
            _mark_foreground()
        elif now - _last_foreground >= settle_seconds:
            return True
        if max_wait_seconds is not None and now - started >= max_wait_seconds:
            return False
        await asyncio.sleep(0.25)


def _mark_foreground() -> None:
    global _last_foreground
    _last_foreground = time.monotonic()


def _preempt_holders(key: str) -> None:
    with _state_lock:
        holders = [h for h in _act(key).holders if not h.preempted]
        for holder in holders:
            holder.preempted = True
    for holder in holders:
        try:
            holder.loop.call_soon_threadsafe(holder.task.cancel)
        except RuntimeError:
            pass  # that loop has closed; its call is gone anyway


def backend_key(model_name: str, kwargs: dict | None = None) -> str:
    """The identity of the inference backend a call is actually contending
    for.

    api_base alone is not enough: LM Studio (and similar local servers)
    serve every loaded model through one shared port, so a chat model and
    a utility model pointed at two different models on the same server
    have identical api_base values despite being genuinely independent
    inference engines that can run concurrently once both are loaded -
    keying on api_base alone would still serialize them, defeating the
    reason to load a second model at all. Combining api_base with the
    model name distinguishes "two requests to the same loaded model"
    (correctly serialized - the real contention this module exists for)
    from "two different models on the same server" (correctly
    concurrent). Falls back to the model name alone when no api_base is
    configured (most cloud providers)."""
    api_base = (kwargs or {}).get("api_base")
    if api_base:
        return f"{api_base}|{model_name or DEFAULT_BACKEND_KEY}"
    return model_name or DEFAULT_BACKEND_KEY


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


def _get_semaphore(key: str) -> threading.Semaphore:
    """The one semaphore every thread and every loop shares for this
    backend key. A different key gets its own independent semaphore, so
    two genuinely different backends can run concurrently while calls to
    the same backend stay serialized."""
    limit = get_configured_limit()
    with _state_lock:
        entry = _state.get(key)
        if entry is None or entry["limit"] != limit:
            # Recreates the semaphore when the configured limit changes
            # rather than trying to mutate an existing one's capacity
            # (Semaphore doesn't support that). A call already holding a
            # slot on the old semaphore keeps running under the old limit
            # until it finishes, and releases the object it acquired - a
            # brief, harmless transition window for what is a
            # politeness/contention-avoidance measure, not a hard
            # security control.
            entry = {"semaphore": threading.Semaphore(limit), "limit": limit}
            _state[key] = entry
        return entry["semaphore"]


async def _acquire(semaphore: threading.Semaphore, key: str = "", background: bool = False) -> None:
    """Take a slot without blocking the event loop.

    semaphore.acquire() would block the whole loop, including the
    coroutine holding the slot we are waiting on - a deadlock, not just a
    stall. The non-blocking attempt comes first so an uncontended call
    never sleeps.
    """
    def turn_waiting() -> bool:
        if not background:
            return False
        with _state_lock:
            return _act(key).waiting > 0

    if not turn_waiting() and semaphore.acquire(blocking=False):
        return
    if not background:
        # The slot is taken: if a preemptible background call holds it, it
        # gives it up now (models.py raises Preempted in that call).
        _preempt_holders(key)
    delay = _POLL_MIN_SECONDS
    while True:
        await asyncio.sleep(delay)
        if not turn_waiting() and semaphore.acquire(blocking=False):
            return
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)


@contextlib.asynccontextmanager
async def model_call_slot(
    key: str = DEFAULT_BACKEND_KEY, *, background: bool = False, preemptible: bool = False
):
    """Async context manager: `async with model_call_slot(key=...): ...`
    around the actual network call. Held only for the duration of the
    call itself, not message construction or rate-limiter bookkeeping.

    key identifies the inference backend being called - see backend_key().
    Calls sharing a key are serialized against each other; calls with
    different keys can run concurrently. Defaults to a single shared key
    for callers that don't know their backend's identity (matches the
    pre-keying behavior of full global serialization)."""
    semaphore = _get_semaphore(key)
    holder: _Holder | None = None
    if not background:
        with _state_lock:
            _act(key).waiting += 1
        _mark_foreground()
    try:
        await _acquire(semaphore, key, background)
    finally:
        if not background:
            with _state_lock:
                _act(key).waiting -= 1
    with _state_lock:
        if not background:
            _act(key).active += 1
        elif preemptible:
            task = asyncio.current_task()
            if task is not None:
                holder = _Holder(loop=asyncio.get_running_loop(), task=task)
                _act(key).holders.append(holder)
    try:
        yield holder
    finally:
        with _state_lock:
            if not background:
                _act(key).active -= 1
            elif holder is not None and holder in _act(key).holders:
                _act(key).holders.remove(holder)
        if not background:
            _mark_foreground()
        # Release the object that was acquired, not whatever _get_semaphore
        # would hand back now - the limit may have changed in between.
        semaphore.release()


async def run_when_idle(make_call, *, attempts: int = 5, settle_seconds: float = 3.0, max_wait_seconds: float = 900.0):
    """Run a background model call in a gap between turns.

    Waits for the user's turns to go quiet, runs `make_call()` (a coroutine
    factory), and if the call gives its slot to a turn (`Preempted`) waits
    and tries again, up to `attempts` times; then raises `Preempted`. Waiting
    happens before the call, so time-limited callers (the 180 s utility-call
    limit) only count the call itself.
    """
    for _ in range(max(1, attempts)):
        await wait_for_foreground_idle(settle_seconds, max_wait_seconds)
        try:
            return await make_call()
        except Preempted:
            continue
    raise Preempted(f"still interrupted by the user's turns after {attempts} tries")
