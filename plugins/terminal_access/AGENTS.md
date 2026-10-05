# terminal_access Plugin DOX

## Purpose

- Hardened, authenticated, workspace-confined Windows command execution. Disabled by default.

## Ownership

- `helpers/safe_executor.py` owns command screening, confinement, timeouts, secret filtering, and output limits.
- `api/execute.py`, `tools/terminal_tool.py`, and `webui/` are the API, agent tool, and UI entry points; `hooks.py`/`execute.py` own lifecycle setup.

## Local Contracts

- Keep it disabled by default and keep authentication, CSRF, and workspace confinement on every entry point.
- `execute_record.json` is a runtime marker and is git-ignored.

## Work Guidance

## Verification

- Smoke-test that disallowed commands and paths outside the workspace are refused.

## Child DOX Index

No child DOX files.
