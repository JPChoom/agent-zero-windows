# permissions_respond.py DOX

## Purpose

- Backend for the Approve / Deny / Always allow buttons on a permissions approval request.

## Ownership

- `permissions_respond.py` owns the runtime implementation; this file owns its contracts.
- Class: `PermissionsRespond`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST handler (`helpers.api.ApiHandler`).
- Mirrors `api/safety_policy_approve.py`; the optional `remember` rule is saved so the user is not asked again, and a failed save is returned as an error rather than hidden.
- Resolves the pending request in the shared approval registry.

## Verification

- `pytest tests/test_permissions_api.py tests/test_permissions_gate.py`
