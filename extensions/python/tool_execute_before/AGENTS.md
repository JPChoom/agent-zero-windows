# Tool Execute Before Extensions DOX

## Purpose

- Own backend processing immediately before tool execution.

## Ownership

- Ordered Python files own the host-bound secret guard (`_09_`), prior tool-output replacement and secret unmasking (`_10_`), parallel recursion guards (`_20_`), and audit capture (`_95_`).
- `_09_secret_destination_guard.py` must run before `_10_unmask_secrets.py`: it refuses calls that would send a secret bound with a `# hosts:` comment (`helpers/secrets.py get_host_bindings`) anywhere but those hosts, including browser typing into a page on another host or an undeterminable destination. It is `FAIL_LOUD`.

## Local Contracts

- Unmask only values required by the target tool.
- Preserve safety checks and do not expose secrets to logs or unrelated tools.
- Keep ordering stable where replacement must occur before unmasking or execution.

## Work Guidance

- Coordinate with secret handling, tool argument preparation, and plugin tool gates.

## Verification

- Smoke-test tool execution with masked secret arguments and prior-output references after changes.

## Child DOX Index

No child DOX files.
