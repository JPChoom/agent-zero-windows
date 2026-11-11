"""Problems an edit introduces that a syntax check cannot see.

After the agent writes or patches a Python file, `ruff` (when it is installed)
looks for the mistakes that make code fail at run time while still parsing:
a name that is not defined, a name used before it is assigned, a redefined
function, a tuple asserted as always true. Only the problems the edit
*added* are reported, in the same tool result, so a file that already had
one is not blamed on the agent and unfinished code (unused imports and
variables) is not flagged at all. Nothing runs the project's code.

Ruff is found on PATH or next to the running Python. A PC without it gets no
lint results and no message: the check is optional by design (no new
dependency). Type checking (pyright, mypy) is not covered here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Rules that mean "this fails when it runs": syntax-level (E9), invalid
# comparisons and asserts (F63), statements in the wrong place (F7),
# undefined names (F82), a redefined unused name (F811), a loop variable
# shadowing an import (F402).
RULES = ("E9", "F63", "F7", "F82", "F811", "F402")
TIMEOUT_SECONDS = 8
WRITING_ACTIONS = {"write", "patch"}  # text_editor actions that change a file
BEFORE_KEY = "_lint_before"  # loop_data.params_temporary: {path: [problems]} taken before the edit
MAX_REPORTED = 5
MAX_BYTES = 1024 * 1024


def ruff_path() -> str:
    """The ruff executable, or "" when there is none."""
    found = shutil.which("ruff")
    if found:
        return found
    for name in ("ruff.exe", "ruff"):
        candidate = Path(sys.executable).parent / name
        if candidate.is_file():
            return str(candidate)
    return ""


def supports(path: str) -> bool:
    return Path(path).suffix.lower() == ".py"


def parse(output: str) -> list[dict]:
    """Ruff's JSON report as [{"code", "message", "line"}]."""
    try:
        items = json.loads(output or "[]")
    except ValueError:
        return []
    found = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("code"):
            continue
        location = item.get("location") or {}
        found.append({"code": str(item["code"]), "message": str(item.get("message") or "").strip(),
                      "line": int(location.get("row") or 0)})
    return found


def run(path: str) -> list[dict] | None:
    """The problems ruff finds in `path`, or None when it cannot say (no ruff,
    a file that is missing or too large, a timeout, a ruff failure)."""
    exe = ruff_path()
    file = Path(path)
    if not exe or not supports(path):
        return None
    try:
        if not file.is_file() or file.stat().st_size > MAX_BYTES:
            return None
        result = subprocess.run(
            [exe, "check", "--isolated", "--no-cache", "--select", ",".join(RULES), "--output-format", "json", str(file)],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):  # 1 = problems found; anything else is ruff failing
        return None
    return parse(result.stdout)


def new_problems(before: list[dict], after: list[dict]) -> list[dict]:
    """The problems in `after` that `before` did not have (matched by rule and
    message, not line: an edit moves lines)."""
    remaining = Counter((p["code"], p["message"]) for p in before)
    added = []
    for problem in after:
        key = (problem["code"], problem["message"])
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            added.append(problem)
    return added


def report(label: str, problems: list[dict]) -> str:
    """The note appended to the tool result, or "" when there is nothing to say."""
    if not problems:
        return ""
    lines = [f"- line {p['line']}: {p['code']} {p['message']}" for p in problems[:MAX_REPORTED]]
    more = len(problems) - MAX_REPORTED
    if more > 0:
        lines.append(f"- and {more} more")
    plural = "problem" if len(problems) == 1 else "problems"
    return f"\n\nLint check: this edit to {label} added {len(problems)} {plural}:\n" + "\n".join(lines) + "\nFix them before going on."
