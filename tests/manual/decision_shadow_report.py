"""Manual report: would the decision model's predictions have been any good?

Reads usr/perf/decision_shadow.jsonl (Settings > Models > Background jobs >
Decision model in shadow mode).

Thinking: a "routine" prediction is only worth acting on if routine steps
really think little and don't run into trouble. "trouble after" is how often
the next step's input looked like a failure. Compare it with the Thinking Auto
rule on the same steps.

Subordinates: "simple" tasks should really finish faster than "hard" ones.

    .venv\\Scripts\\python.exe tests\\manual\\decision_shadow_report.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "usr" / "perf" / "decision_shadow.jsonl"
CONFIDENT = 0.5


def _median(values: list) -> float | None:
    return round(statistics.median(values), 1) if values else None


def with_trouble_after(rows: list[dict]) -> list[dict]:
    """Each thinking row with `trouble_after`: the next step of the same run."""
    out = [dict(row) for row in rows]
    for current, following in zip(out, out[1:]):
        same_run = all(current.get(key) == following.get(key) for key in ("context_id", "agent"))
        if same_run and following.get("step") == current.get("step", 0) + 1:
            current["trouble_after"] = bool(following.get("trouble_before"))
    return out


def _group(rows: list[dict]) -> dict:
    known = [row["trouble_after"] for row in rows if "trouble_after" in row]
    return {
        "steps": len(rows),
        "median_reasoning_chars": _median([row.get("reasoning_chars", 0) for row in rows]),
        "median_seconds": _median([row.get("seconds", 0) for row in rows]),
        "trouble_after_%": round(100 * sum(known) / len(known), 1) if known else None,
    }


def summarize(rows: list[dict]) -> dict:
    thinking = with_trouble_after([row for row in rows if row.get("decision") == "thinking"])
    answered = [row for row in thinking if row.get("choice")]
    subordinates = [row for row in rows if row.get("decision") == "subordinate" and row.get("choice")]
    report = {
        "rows": len(rows),
        "failed_requests": sum(1 for row in rows if row.get("error")),
        "median_decide_ms": _median([row["ms"] for row in rows if "ms" in row and not row.get("error")]),
        "thinking": {
            "predicted routine": _group([row for row in answered if row["choice"] == "routine"]),
            "predicted routine, confident": _group([
                row for row in answered if row["choice"] == "routine" and (row.get("confidence") or 0) >= CONFIDENT]),
            "predicted deep": _group([row for row in answered if row["choice"] == "deep"]),
            "Thinking Auto rule skips": _group([row for row in thinking if row.get("rule_thinks") is False]),
        },
        "subordinate": {
            choice: {
                "tasks": len([row for row in subordinates if row["choice"] == choice]),
                "median_seconds": _median([row.get("seconds", 0) for row in subordinates if row["choice"] == choice]),
            }
            for choice in ("simple", "hard")
        },
    }
    return report


def main() -> int:
    if not LOG.exists():
        print(f"No log yet: {LOG}")
        return 0
    rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(summarize(rows), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
