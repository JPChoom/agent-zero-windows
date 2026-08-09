"""General-purpose, hash-chained append-only audit log.

Distinct from plugins/_safety_policy/helpers/audit_log.py, which stays as
it is - a simple, non-chained JSONL log scoped to that plugin's own
allow/deny decisions. This one is core (not plugin-scoped) and generic:
any consequential action anywhere in the codebase can append a record.

Each record carries `prev_hash` (the previous record's `hash`, or None
for the first record) and its own `hash` = sha256 of the record's other
fields serialized as canonical (sorted-key) JSON, including `prev_hash`.
This makes the log tamper-evident: editing or removing any past line
breaks the chain from that point forward, detectable by verify_chain()
without needing a separate signature or external ledger. It does not
prevent tampering (anyone with filesystem access can rewrite the whole
file and recompute a self-consistent chain) - it only makes an
inconsistent edit (changing one line without recomputing everything after
it) detectable, which is the realistic threat model for a local,
single-machine log.

Single-process, best-effort locking (matches the existing safety_policy
audit log's posture): concurrent writers within the same process are
serialized by an asyncio.Lock; concurrent writers across separate OS
processes could still interleave. Not attempted here - this repo has no
existing cross-process file-locking primitive to build on, and a broken
chain is detectable (via verify_chain) even if it happens, which is the
main property this module is trying to provide.
"""

import asyncio
import hashlib
import json
import time

from helpers import files

_AUDIT_LOG_FILENAME = "audit_log.jsonl"
_write_lock = asyncio.Lock()


def get_audit_log_path() -> str:
    return files.get_abs_path(files.USER_DIR, _AUDIT_LOG_FILENAME)


def _canonical_json(record: dict) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)


def _compute_hash(record_without_hash: dict) -> str:
    return hashlib.sha256(_canonical_json(record_without_hash).encode("utf-8")).hexdigest()


def _read_last_hash(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1]).get("hash")
    except (OSError, ValueError, json.JSONDecodeError):
        return None


async def append_record(record: dict) -> dict:
    """Append `record` to the audit log with timestamp/prev_hash/hash
    fields added, and return the full stored entry. Never raises - audit
    logging must never itself break the action being logged."""
    async with _write_lock:
        try:
            path = get_audit_log_path()
            prev_hash = _read_last_hash(path)
            entry = {"time": time.time(), **record, "prev_hash": prev_hash}
            entry["hash"] = _compute_hash(entry)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_canonical_json(entry) + "\n")
            return entry
        except OSError:
            return {}


def verify_chain(path: str | None = None) -> tuple[bool, str]:
    """Walk the whole log recomputing each record's hash. Returns
    (True, "") if the chain is intact, or (False, reason) at the first
    inconsistency found - either a record whose stored hash doesn't match
    its own recomputed content, or whose prev_hash doesn't match the
    actual previous record's hash (evidence of a deleted/reordered/edited
    line)."""
    path = path or get_audit_log_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return True, ""  # no log yet - vacuously intact

    expected_prev_hash = None
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return False, f"line {i + 1} is not valid JSON: {exc}"

        stored_hash = record.get("hash")
        if record.get("prev_hash") != expected_prev_hash:
            return False, (
                f"line {i + 1}: prev_hash mismatch (expected {expected_prev_hash!r}, "
                f"got {record.get('prev_hash')!r}) - a record was likely deleted, "
                "reordered, or edited"
            )

        without_hash = {k: v for k, v in record.items() if k != "hash"}
        recomputed = _compute_hash(without_hash)
        if recomputed != stored_hash:
            return False, f"line {i + 1}: hash does not match its own content - the line was likely edited"

        expected_prev_hash = stored_hash

    return True, ""
