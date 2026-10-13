# debounced.py DOX

## Purpose

- Run a blocking call in a worker thread and reuse its result for a short TTL, so async extensions stop walking the filesystem on every call.

## Ownership

- `debounced.py` owns the runtime implementation; this file owns its contracts.
- Functions: `run_debounced`, `clear`.

## Runtime Contracts

- `await run_debounced(key, ttl_seconds, func, *args, **kwargs)` returns the cached result within the TTL and runs `func` on a worker thread (`asyncio.to_thread`); `func` must not depend on the calling thread or touch asyncio primitives.
- A per-key, per-event-loop lock means only the first of several concurrent callers on a loop runs the call; the rest wait and reuse its result. Locks are keyed by running loop because an `asyncio.Lock` binds to one loop and A0 runs agents on several; the result cache is shared.
- `clear` exists mainly for tests.

## Verification

- `pytest tests/test_debounced.py tests/test_debounce_integration_sites.py`
