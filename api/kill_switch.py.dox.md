# kill_switch.py DOX

## Purpose

- Trip, reset and query the global kill switch (`helpers/kill_switch.py`) for the always-visible header icon.

## Ownership

- `kill_switch.py` owns the runtime implementation; this file owns its contracts.
- Class: `KillSwitch`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST handler (`helpers.api.ApiHandler`).
- Not a chat or tool action: no agent tool may expose trip/reset.
- Authentication stays required; the tripped state is a flag file that survives restarts.

## Verification

- `pytest tests/test_kill_switch.py`
