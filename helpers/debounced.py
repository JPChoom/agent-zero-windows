"""Debounced, thread-offloaded execution of a blocking call.

Two problems this solves together, because they showed up on the same
call sites: file_tree.file_tree(), skills_helper.list_skills(), and
scan_promptinclude_files() are plain synchronous functions - real
filesystem walks - called directly from async Extension.execute()
methods with no thread offload at all. Confirmed by reading the actual
call sites, not assumed: on Windows and on any non-dev-mode deployment,
nothing routes these through a thread or a separate process, so they run
straight on the asyncio event loop. Since A0 is a single-process asyncio
server, that does not just slow the current turn - it stalls every other
agent, every websocket message, every concurrent request for the
duration of the walk.

Two of the three run on hooks that fire on every single turn
(message_loop_prompts_after) or every single prompt build (system_prompt),
regardless of whether the workdir or skill set changed since the last
call. This does not try to detect whether the underlying data actually
changed - that would mean walking it to find out, which defeats the
point - it bounds the *rate* instead, the same way
plugins/_time_travel's own debounced snapshot already does for a
different kind of write.
"""

import asyncio
import time
from typing import Any, Callable

_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def run_debounced(
    key: str, ttl_seconds: float, func: Callable[..., Any], *args, **kwargs
) -> Any:
    """Run func(*args, **kwargs) in a thread, reusing the result for
    ttl_seconds under the same key.

    func must have no dependency on the calling thread (no asyncio
    primitives, no assumption of running on the event loop's own thread)
    - it is genuinely executed on a worker thread via asyncio.to_thread.
    Reading plain, already-set attributes off a live object (as
    list_skills does with an agent's profile name) is fine, matching what
    background DeferredTasks elsewhere in this codebase already do; do
    not use this for anything that mutates shared state or touches
    asyncio.Lock/Event/etc.

    A per-key asyncio.Lock avoids a thundering herd: if several turns
    arrive while a walk for the same key is already in flight, only the
    first actually runs it, and the rest wait on the lock rather than
    each starting their own redundant walk.
    """
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # Re-check after acquiring the lock: whoever held it may have
        # just refreshed this exact key while we were waiting.
        cached = _cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < ttl_seconds:
            return cached[1]

        result = await asyncio.to_thread(func, *args, **kwargs)
        _cache[key] = (time.monotonic(), result)
        return result


def clear(key: str | None = None) -> None:
    """Drop a cached entry (or everything, if key is None).

    Exists mainly for tests; production code has no current need to
    invalidate early since entries expire on their own via ttl_seconds.
    """
    if key is None:
        _cache.clear()
        _locks.clear()
    else:
        _cache.pop(key, None)
        _locks.pop(key, None)
