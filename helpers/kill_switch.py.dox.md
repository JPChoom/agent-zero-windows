# kill_switch.py DOX

## Purpose

- Global kill switch the agent cannot control: a flag file (`usr/.kill_switch`) whose tripped state survives restarts.

## Ownership

- `kill_switch.py` owns the runtime implementation; this file owns its contracts.
- Functions: `get_flag_path`, `is_tripped`, `get_reason`, `trip`, `reset`, `denial_message`.

## Runtime Contracts

- No tool exposes `trip()`/`reset()` to the model; the only callers are `api/kill_switch.py` and tests.
- Enforcement points call `is_tripped()` and refuse with `denial_message()`.

## Verification

- `pytest tests/test_kill_switch.py`
