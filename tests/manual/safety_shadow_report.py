"""Manual report: how the shadow safety check compares with the real one.

Reads usr/perf/safety_shadow.jsonl (Settings > Safety check > Shadow on the
Utility model). The number that matters is "missed": the real check stopped an
action and the shadow would have let it through.

    .venv\\Scripts\\python.exe tests\\manual\\safety_shadow_report.py
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "usr" / "perf" / "safety_shadow.jsonl"


def summarize(rows: list[dict]) -> dict:
    judged = [row for row in rows if row.get("shadow")]
    seconds = [row["seconds"] for row in judged if "seconds" in row]
    return {
        "rows": len(rows),
        "judged": len(judged),
        "errors": len(rows) - len(judged),
        "agreed": sum(1 for row in judged if row.get("main") == row["shadow"]),
        "missed": sum(1 for row in judged if row.get("main") in ("terminate", "clarify") and row["shadow"] == "ok"),
        "softer": sum(1 for row in judged if row.get("main") == "terminate" and row["shadow"] == "clarify"),
        "stricter": sum(1 for row in judged if row.get("main") == "ok" and row["shadow"] in ("terminate", "clarify")),
        "no_verdict": sum(1 for row in judged if row["shadow"] == "none"),
        "median_seconds": round(statistics.median(seconds), 2) if seconds else None,
        "pairs": collections.Counter(f"{row.get('main')} -> {row['shadow']}" for row in judged),
    }


def main() -> int:
    if not LOG.exists():
        print(f"No shadow log yet: {LOG}")
        return 0
    rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = summarize(rows)
    pairs = report.pop("pairs")
    for key, value in report.items():
        print(f"{key:16} {value}")
    for pair, count in pairs.most_common():
        print(f"  {pair:26} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
