"""Run a coroutine to completion from synchronous code without nesting
event loops.

Several sync entry points used to call `asyncio.run(...)` under
`nest_asyncio`, which re-enters the *running* loop when called from inside
an async task. Re-entering the loop mid-task can run that task's own wakeup
while its context is still entered ("cannot enter context ... is already
entered"); the wakeup is dropped and the task never resumes - the agent
freezes with no error (diagnosed 2026-09-29, see
plugins/_code_execution/helpers/tty_session.py).

run_sync() never nests: with no loop running in this thread it uses a plain
asyncio.run(); with one running, it runs the coroutine on a fresh loop in a
worker thread and blocks for the result. Only use it for coroutines that
don't need objects bound to the caller's loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="run_sync") as pool:
        return pool.submit(asyncio.run, coro).result()
