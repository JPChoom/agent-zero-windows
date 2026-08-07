"""Minimal append-only JSONL audit log for denied commands.

No generic audit-log utility exists elsewhere in this codebase to build on
(helpers/log.py is an in-memory per-chat transcript for the UI, not a
durable on-disk record). This is intentionally simple: one JSON line per
denial, append-only, not hash-chained/tamper-evident - a genuinely
immutable audit trail (per the hand-off doc's own suggestion) is future
work, not attempted here.
"""

import json
import time

from helpers import files

_AUDIT_LOG_FILENAME = "safety_policy_audit.jsonl"


def get_audit_log_path() -> str:
    return files.get_abs_path(files.USER_DIR, _AUDIT_LOG_FILENAME)


def append_denial(record: dict) -> None:
    entry = {"timestamp": time.time(), **record}
    path = get_audit_log_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # audit logging must never itself break command denial
