# Permissions Plugin DOX

## Purpose

- Own the per-tool permission gate (deny/ask/allow rules), the per-chat permission mode, and the password-locked Bypass mode.

## Ownership

- `helpers/rules.py` owns modes, rule parsing, and the decision engine (no Agent Zero imports).
- `helpers/config.py` owns resolved rules/timeouts and reads the chat's mode from `mode_state`.
- `helpers/mode_state.py` owns the in-memory per-chat mode, default mode, and Bypass expiry.
- `helpers/bypass_lock.py` owns the Bypass password (PBKDF2 hash in `usr/permissions_bypass.json`).
- `extensions/python/tool_execute_before/_06_permissions.py` owns the gate; `extensions/webui/` and `webui/` own the selector and the unlock modal.
- Endpoints live in core `api/`: `permissions_mode.py`, `permissions_respond.py`, `permissions_bypass_password.py`.

## Local Contracts

- The mode is per chat (`AgentContext` id) and never persisted: restart, new chat, and project switch return to settings `permissions_default_mode` (default `manual`; can never be `bypass`). A `mode` key in plugin config is ignored.
- `bypass` needs the Bypass password and expires after settings `bypass_auto_off_hours` (0 = only on restart/new chat/project switch). The gate logs a chat warning when it expires.
- The gate refuses, in every mode, any tool call whose args reference `permissions_bypass`, `permissions_mode`, or `security_audit` (the agent must not unlock itself or erase the trail).
- `_safety_policy`'s `_05_` floor runs before this `_06_` gate; deny rules bind even in bypass.
- Honest limit: an agent already in Bypass runs as the same Windows user; the lock protects against other people and accidental Bypass, not a compromised unlocked agent.

## Work Guidance

- Keep selector labels/colors in `api/permissions_mode.py` in rules.MODES order (safest first).

## Verification

- `pytest tests/test_permissions_api.py tests/test_permissions_bypass_lock.py tests/test_permissions_gate.py`

## Child DOX Index

No child DOX files.
