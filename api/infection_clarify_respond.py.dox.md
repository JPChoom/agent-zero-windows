# infection_clarify_respond.py DOX

## Purpose

- Backend for the Allow / Block buttons on an infection-check clarification request.

## Ownership

- `infection_clarify_respond.py` owns the runtime implementation; this file owns its contracts.
- Class: `InfectionClarifyRespond`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST handler (`helpers.api.ApiHandler`).
- Resolves the pending request in the shared approval registry (same registry as `api/safety_policy_approve.py`).
- An unknown or already-resolved id must not grant anything.

## Verification

- `pytest tests/test_infection_clarify_user.py`
