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

## Verification

- `pytest tests/test_model_concurrency.py`
