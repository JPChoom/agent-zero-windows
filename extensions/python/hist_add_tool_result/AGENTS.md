# History Tool Result Extensions DOX

## Purpose

- Own processing after tool results are added to history.

## Ownership

- `_50_mark_untrusted_content.py` wraps external tool results in `<untrusted_content id="...">` blocks (random id per result) and taints the chat (`helpers/untrusted_content.py`); it runs before `_90_save_tool_call_file.py` so the saved copy carries the same marker.
- `_90_save_tool_call_file.py` owns tool-call file persistence.

## Local Contracts

- Preserve tool result traceability without leaking secrets.
- Keep file artifacts inside expected runtime/user-owned paths.
- Skip BACKGROUND contexts; background workers must remain ephemeral and must not create chat message files.

## Work Guidance

- Coordinate changes with tool output storage and chat persistence behavior.

## Verification

- Smoke-test a tool call that produces persisted output after changes.

## Child DOX Index

No child DOX files.
