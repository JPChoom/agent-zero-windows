# Tests DOX

## Purpose

- Own pytest regression, security, integration, and contract tests.
- Keep tests focused on behavior that should remain stable across framework changes.

## Ownership

- Test files live directly under `tests/` and are named for the behavior or subsystem they cover.
- Shared fixtures should be added only when multiple tests need them.
- `conftest.py` (autouse) pins the per-chat permission default to `auto` and clears in-memory modes, so tests that run tools through the real `tool_execute_before` chain don't wait on approval prompts or depend on the developer's `usr/settings.json`. Permission tests patch `mode_state` explicitly (their patches win).
- Runtime artifacts created during tests should use pytest temporary directories or existing isolated test helpers.
- `tests/manual/` holds scripts that need a live local model or other local services (e.g. `windows_routing_eval.py`). They are not collected by pytest (no `test_` prefix) and are run by hand.

## Local Contracts

- Tests must not require real API keys, network-only services, private user data, or local `usr/` runtime state.
- Keep tests deterministic and isolated from existing chats, uploads, downloads, plugin state, and settings.
- Prefer exercising public helper/API contracts over fragile implementation details when practical.
- Security regression tests should assert the protected behavior directly.

## Work Guidance

- Add focused tests near the affected subsystem's existing tests.
- Use descriptive test names that state the regression or contract.
- Avoid broad sleeps or real-time dependencies; use monkeypatching or controlled clocks where possible.

## Verification

- Run `pytest` for broad changes.
- Run `pytest tests/test_name.py` for narrow changes and mention any broader test gaps at closeout.

## Child DOX Index

No child DOX files.
