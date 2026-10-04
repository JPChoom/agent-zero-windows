# sync_async.py DOX

## Purpose

- Own `run_sync(coro)`: run a coroutine to completion from synchronous code without nesting event loops.

## Ownership

- `sync_async.py` owns the runtime implementation; this file owns its contracts.

## Runtime Contracts

- No loop running in the calling thread -> plain `asyncio.run`. A loop running -> the coroutine runs on a fresh loop in a one-shot worker thread and the caller blocks for the result.
- Never call `asyncio.run` / `run_until_complete` from code that can execute inside a running loop: under `nest_asyncio` it re-enters the loop mid-task and can drop that task's wakeup ("cannot enter context ... already entered"), freezing the agent permanently with no error (diagnosed 2026-09-29).
- Only for coroutines that don't need objects bound to the caller's loop; do not use where long-lived sessions must stay on the caller's loop (e.g. `helpers/mcp_handler.py` server init).
- Callers: `helpers/plugins.py call_plugin_hook` (async hooks), `models.py apply_rate_limiter_sync`, `helpers/task_scheduler.py SchedulerTaskList.get`.

## Verification

- `pytest tests/test_sync_async_and_stream_timeout.py`

## Child DOX Index

No child DOX files.
