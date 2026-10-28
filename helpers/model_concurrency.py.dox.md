# model_concurrency.py DOX

## Purpose

- Serialize concurrent model calls with a semaphore per inference backend (default limit 1 per backend).

## Ownership

- `model_concurrency.py` owns the runtime implementation; this file owns its contracts.
- Functions: `backend_key`, `get_configured_limit`, `model_call_slot`.

## Runtime Contracts

- Keyed by backend (provider, `api_base` and model), not globally: Main and Utility models on the same local server share one slot, different backends do not block each other.
- The limit comes from `_model_config`'s `max_concurrent_model_calls` setting.
- `async with model_call_slot(key=...)` is held only around the network call.

- Priority: `model_call_slot(key, background=..., preemptible=...)`. Calls for the user's turn (default) count as waiting/active per key; a background call takes a free slot only when no turn call is waiting for that key. When a turn call finds the slot taken, preemptible background holders are cancelled on their own loop (`call_soon_threadsafe`); `models._run_unified` turns that cancel into `Preempted` (uncancelling the task) for the caller. `models.PREEMPTIBLE_CALLERS` (`memorize_fragments`, `memorize_solutions`, `rename_chat`, `history_compression` when run as the early background pass; non-streaming only) decides which background calls may be interrupted; consolidation is background-priority but never interrupted.
- `wait_for_foreground_idle(settle_seconds, max_wait_seconds)` waits until no turn call has waited or run for `settle_seconds`; `run_when_idle(make_call, attempts=5)` waits, calls, and retries after `Preempted`, then raises it. Waiting happens before the call, so the 180 s utility-call limit only covers the call itself.

## Verification

- `pytest tests/test_model_concurrency.py`
