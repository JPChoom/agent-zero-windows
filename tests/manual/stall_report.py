"""Manual report: what blocked the event loop (the UI and every chat wait).

Reads usr/perf/stalls.jsonl, written by helpers/perf.py whenever a loop was
silent for over half a second. Groups stalls by the deepest Agent Zero frame
in the stack, which is usually the code to fix.

    .venv\\Scripts\\python.exe tests\\manual\\stall_report.py
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "usr" / "perf" / "stalls.jsonl"
OWN = ("helpers/", "plugins/", "extensions/", "api/", "tools/", "agent.py", "models.py", "run_ui.py", "initialize.py")


def culprit(stack: list[str]) -> str:
    own = [frame for frame in stack if frame.startswith(OWN) and not frame.startswith("helpers/perf.py")]
    return own[-1] if own else (stack[-1] if stack else "(no stack)")


def summarize(rows: list[dict]) -> list[tuple[str, int, float, float]]:
    groups: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        groups[culprit(row.get("stack") or [])].append(float(row.get("seconds", 0)))
    return sorted(((name, len(v), round(sum(v), 1), round(max(v), 1)) for name, v in groups.items()), key=lambda r: -r[2])


def main() -> int:
    if not LOG.exists():
        print(f"No stalls recorded yet: {LOG}")
        return 0
    rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{len(rows)} stalls, {sum(r.get('seconds', 0) for r in rows):.1f} s in all")
    for name, count, total, longest in summarize(rows)[:15]:
        print(f"{total:8.1f} s  {count:4}x  longest {longest:6.1f} s  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
