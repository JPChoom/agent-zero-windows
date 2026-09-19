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
"""

import asyncio
import contextlib

import threading

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
async def model_call_slot(key: str = DEFAULT_BACKEND_KEY):
    """Async context manager: `async with model_call_slot(key=...): ...`
    around the actual network call. Held only for the duration of the
    call itself, not message construction or rate-limiter bookkeeping.

    key identifies the inference backend being called - see backend_key().
    Calls sharing a key are serialized against each other; calls with
    different keys can run concurrently. Defaults to a single shared key
    for callers that don't know their backend's identity (matches the
    pre-keying behavior of full global serialization)."""
    semaphore = _get_semaphore(key)
    await _acquire(semaphore)
    try:
        yield
    finally:
        # Release the object that was acquired, not whatever _get_semaphore
        # would hand back now - the limit may have changed in between.
        semaphore.release()
