# safety_policy_approve.py DOX

## Purpose

- Own the `safety_policy_approve.py` API endpoint.
- Resolves a pending `_safety_policy` approve-tier decision: the backend of the Allow once / Always allow / Deny buttons on a `safety_policy_approval_request` chat message and its popup.
- Keep this file-level DOX profile synchronized with `safety_policy_approve.py` because this directory is intentionally flat.

## Ownership

- `safety_policy_approve.py` owns the runtime implementation.
- `safety_policy_approve.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `SafetyPolicyApprove` (`ApiHandler`)
  - `async process(self, input: dict, request: Request) -> dict | Response`

## Runtime Contracts

- Request: `approval_id` (str), `approved` (bool), optional `remember` (bool).
- Response: `resolved` (false for an unknown, already-resolved, or timed-out id), `approved`, `remembered` (the host saved, or ""), `error` (a save failure, or "").
- `remember` only acts when `approved` is true. The host is read from `approval_registry.get_meta(approval_id)["remember_host"]`, which the policy extension sets server-side for downloader matches; a host in the request body is never trusted.
- The host is persisted with `plugins._safety_policy.helpers.config.add_allowed_host` (global scope, also enables the allowlist) before the decision is resolved, so a failed save is reported while the command is still held.
- Default auth and CSRF requirements apply; this is a browser-facing state-changing endpoint.

## Key Concepts

- Mirrors `api/permissions_respond.py`, which does the same for `_permissions` rules.
- Pending decisions are in-memory futures; they do not survive a restart.

## Work Guidance

- Preserve authentication and CSRF checks.
- Update `plugins/_safety_policy/extensions/webui/get_message_handler/approval-handler.js`, `plugins/_safety_policy/webui/approval-popup*`, and tests together when payload shape changes.

## Verification

- `pytest tests/test_safety_policy.py`

## Child DOX Index

No child DOX files.
