# audit_log.py DOX

## Purpose

- General-purpose, hash-chained, append-only audit log for consequential actions anywhere in the codebase.

## Ownership

- `audit_log.py` owns the runtime implementation; this file owns its contracts.
- Functions: `get_audit_log_path`, `append_record`, `verify_chain`.

## Runtime Contracts

- Each record carries `prev_hash` and its own `hash`; editing or deleting a line breaks the chain, which `verify_chain` reports as `(False, reason)`.
- Distinct from `plugins/_safety_policy/helpers/audit_log.py`, a simple non-chained log for that plugin.
- Writes under `usr/` (git-ignored); never put secrets in records.

## Verification

- `pytest tests/test_audit_log.py`
