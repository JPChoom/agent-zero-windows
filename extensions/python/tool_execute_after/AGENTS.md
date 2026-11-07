# Tool Execute After Extensions DOX

## Purpose

- Own backend processing immediately after tool execution.

## Ownership

- Ordered Python files own post-tool secret masking and future tool-result postprocessing.

## Local Contracts

- Mask secrets before tool results reach history, UI, or model-visible context.
- Hooks numbered below `_90` see the full result: `plugins/_model_config`'s `_90_tool_digest.py` may shorten `response.message` after them.
- Do not alter tool `break_loop` or response semantics unless the hook contract owns that behavior.

## Work Guidance

- Coordinate with tool implementations and history hooks when changing tool result data.

## Verification

- Smoke-test tool execution with sensitive output after changes.

## Child DOX Index

No child DOX files.
