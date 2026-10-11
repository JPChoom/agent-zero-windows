"""EXPERIMENTAL dynamic sampling (off by default; Settings > Agent > Models).

Before each Main-model call, the unlocked sampling values are nudged by what
the agent is doing:
- "code" when one of the last tools it used is a coding tool,
- "creative" when the user's message asks for creative writing,
- "reasoning" (no change) otherwise.
The rules and offsets are plain settings (`sampling.dynamic_rules`), so they
are visible and editable. Locked values are never touched. There is no
measured benefit yet: the Windows workflow benchmark is the yardstick before
this can stop being experimental.
"""

from __future__ import annotations

import re

RECENT_TOOLS_KEY = "_dynamic_sampling_recent_tools"
RECENT_TOOLS = 3
ADJUSTED_KEYS = ("temperature", "top_p", "repeat_penalty")


def classify(recent_tools: list[str], user_text: str, rules: dict) -> str:
    code_tools = {str(t).strip() for t in rules.get("code_tools", [])}
    if any(tool in code_tools for tool in recent_tools[-RECENT_TOOLS:]):
        return "code"
    words = [str(w).strip().lower() for w in rules.get("creative_words", []) if str(w).strip()]
    text = str(user_text or "").lower()
    if words and re.search(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", text):
        return "creative"
    return "reasoning"


def adjusted_values(sampling: dict, mode: str) -> dict:
    """The sampling values for this call: base + offset for each unlocked key."""
    rules = sampling.get("dynamic_rules") or {}
    offsets = (rules.get("offsets") or {}).get(mode) or {}
    base = rules.get("base") or {}
    locks = sampling.get("locks") or {}
    values = {}
    for key in ADJUSTED_KEYS:
        if locks.get(key):
            continue
        offset = offsets.get(key)
        if offset in (None, 0):
            continue
        start = sampling.get(key)
        if start in (None, ""):
            start = base.get(key)
        if start in (None, ""):
            continue
        value = float(start) + float(offset)
        if key == "temperature":
            value = min(2.0, max(0.0, value))
        elif key == "top_p":
            value = min(1.0, max(0.01, value))
        else:
            value = max(0.0, value)
        values[key] = round(value, 4)
    return values
