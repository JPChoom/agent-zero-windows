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
"""

import asyncio
import contextlib

_lock = asyncio.Lock()
_semaphore: asyncio.Semaphore | None = None
_semaphore_limit: int | None = None


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


async def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_limit
    limit = get_configured_limit()
    async with _lock:
        if _semaphore is None or _semaphore_limit != limit:
            # Recreates the semaphore when the configured limit changes
            # rather than trying to mutate an existing one's capacity
            # (asyncio.Semaphore doesn't support that). A call already
            # holding a slot on the old semaphore keeps running under the
            # old limit until it finishes - a brief, harmless transition
            # window for what is a politeness/contention-avoidance
            # measure, not a hard security control.
            _semaphore = asyncio.Semaphore(limit)
            _semaphore_limit = limit
        return _semaphore


@contextlib.asynccontextmanager
async def model_call_slot():
    """Async context manager: `async with model_call_slot(): ...` around
    the actual network call. Held only for the duration of the call
    itself, not message construction or rate-limiter bookkeeping."""
    semaphore = await _get_semaphore()
    async with semaphore:
        yield
