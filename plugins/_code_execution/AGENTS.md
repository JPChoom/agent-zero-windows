# Code Execution Plugin DOX

## Purpose

- Own terminal, Python, and Node.js code execution through persistent local or SSH-backed sessions.

## Ownership

- `tools/` owns the code execution and input tools.
- `helpers/` owns local shell, SSH shell, and TTY session management.
- `prompts/` owns execution prompt and runtime response fragments.
- `default_config.yaml`, `plugin.yaml`, `extensions/`, and `webui/` own settings, metadata, hooks, and UI config.

## Local Contracts

- Keep session concurrency, timeout, streaming, and reset behavior predictable.
- Explicitly target local versus SSH execution runtimes.
- Do not hardcode secrets, SSH credentials, or local user paths.
- `__del__` methods on session objects (`TTYSession`, `LocalInteractiveSession`) must stay synchronous and never run or nest an event loop (`asyncio.run`, `run_until_complete`): garbage collection can fire mid-task-step, and a nested loop there drops that task's wakeup and freezes the agent permanently. Graceful shutdown belongs to callers that `await close()`.
- Use `tty_session._SIGKILL`, not `signal.SIGKILL`, which does not exist on Windows.

## Work Guidance

- Preserve long-running command output retrieval and busy-session guards when changing execution flow.

## Verification

- Smoke-test terminal, Python, Node.js, output polling, and reset paths after tool changes.

## Child DOX Index

No child DOX files.
