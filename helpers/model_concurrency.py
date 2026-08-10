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

Scoped per event loop, not a single global singleton. asyncio.Lock/
Semaphore bind to whichever running loop first uses them (raising
RuntimeError: "... is bound to a different event loop" if a second loop
touches the same instance) - and this fork genuinely has more than one
loop in play: plugins/_memory's end-of-turn "memorize solutions"
extension runs on its own background thread via helpers/defer.py's
DeferredTask, with its own event loop, separate from the main server
loop. A single module-level semaphore crashed the very first time that
background thread called the model (reproduced from a real user log -
plugins/_memory/extensions/python/monologue_end/_51_memorize_solutions.py
-> call_utility_model -> unified_call -> model_call_slot -> crash).
Keying by the running loop's id trades perfect cross-thread
serialization (which would need a thread-safe primitive, meaningfully
more complex) for "never crash, and fully serialize within whichever
loop each call happens to run on" - correct for the dominant case
(parallel_tools.py's worker agents, all on the main loop) and a real
fix, not a workaround, for the background-thread case that was broken
outright before (it crashed, so it had zero serialization anyway).
"""

import asyncio
import contextlib

_loop_state: dict[int, dict] = {}


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


def _get_loop_state() -> dict:
    """Returns this running loop's own lock/semaphore state, creating it
    on first use. The Lock/Semaphore created here are only ever touched
    by code running on this same loop (we're inside it right now), so
    they never see a foreign-loop access."""
    loop_key = id(asyncio.get_running_loop())
    state = _loop_state.get(loop_key)
    if state is None:
        state = {"lock": asyncio.Lock(), "semaphore": None, "limit": None}
        _loop_state[loop_key] = state
    return state


async def _get_semaphore() -> asyncio.Semaphore:
    state = _get_loop_state()
    limit = get_configured_limit()
    async with state["lock"]:
        if state["semaphore"] is None or state["limit"] != limit:
            # Recreates the semaphore when the configured limit changes
            # rather than trying to mutate an existing one's capacity
            # (asyncio.Semaphore doesn't support that). A call already
            # holding a slot on the old semaphore keeps running under the
            # old limit until it finishes - a brief, harmless transition
            # window for what is a politeness/contention-avoidance
            # measure, not a hard security control.
            state["semaphore"] = asyncio.Semaphore(limit)
            state["limit"] = limit
        return state["semaphore"]


@contextlib.asynccontextmanager
async def model_call_slot():
    """Async context manager: `async with model_call_slot(): ...` around
    the actual network call. Held only for the duration of the call
    itself, not message construction or rate-limiter bookkeeping."""
    semaphore = await _get_semaphore()
    async with semaphore:
        yield
