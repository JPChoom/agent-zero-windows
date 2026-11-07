# Response Stream Chunk Extensions DOX

## Purpose

- Own handling of incremental assistant response chunks.

## Ownership

- Ordered Python files own chunk-level response masking; `_20_runaway_guard.py` stops a repeating reply (`helpers/runaway_guard.py`). `reasoning_stream_chunk/` runs the same guard.

## Local Contracts

- Mask secrets before response chunks reach UI or persisted logs.
- Keep chunk processing compatible with final response stream masking.

## Work Guidance

- Keep per-chunk work lightweight for streaming responsiveness.

## Verification

- Smoke-test streaming responses with sensitive patterns after changes.

## Child DOX Index

No child DOX files.
