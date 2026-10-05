# path_containment.py DOX

## Purpose

- Shared path containment: resolve a path and verify it lies inside an allowed set of root directories.

## Ownership

- `path_containment.py` owns the runtime implementation; this file owns its contracts.
- Class: `PathNotAllowedError`. Functions: `resolve_within_roots`, `resolve_with_tier`.

## Runtime Contracts

- `resolve_within_roots` resolves relative paths against `default_root` and raises `PathNotAllowedError` when the result is outside every root.
- `resolve_with_tier` honors a tiered-access setting; only `tier == "unrestricted"` bypasses containment.
- Use for any tool or plugin that exposes filesystem access to the agent.

## Verification

- `pytest tests/test_code_execution_access_tier.py`
