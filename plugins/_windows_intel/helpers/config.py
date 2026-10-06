"""Resolved plugin settings.

`get_plugin_config` returns only values that have actually been set, so the
YAML defaults are not merged in: these DEFAULTS are what really applies.
Keep them in step with default_config.yaml.
"""

from __future__ import annotations

DEFAULTS = {
    "default_limit": 50,
    "max_limit": 500,
    "max_output_chars": 12000,
    "redact_secrets": True,
    "ps_timeout_seconds": 30,
}


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def resolve(raw: dict | None) -> dict:
    raw = raw or {}
    max_limit = _int(raw.get("max_limit", DEFAULTS["max_limit"]), DEFAULTS["max_limit"], 10, 5000)
    return {
        "max_limit": max_limit,
        "default_limit": _int(raw.get("default_limit", DEFAULTS["default_limit"]), DEFAULTS["default_limit"], 1, max_limit),
        "max_output_chars": _int(raw.get("max_output_chars", DEFAULTS["max_output_chars"]), DEFAULTS["max_output_chars"], 1000, 100000),
        "redact_secrets": bool(raw.get("redact_secrets", DEFAULTS["redact_secrets"])),
        "ps_timeout_seconds": _int(raw.get("ps_timeout_seconds", DEFAULTS["ps_timeout_seconds"]), DEFAULTS["ps_timeout_seconds"], 5, 120),
    }


def get_config(agent=None) -> dict:
    from helpers import plugins

    try:
        raw = plugins.get_plugin_config("_windows_intel", agent=agent) or {}
    except Exception:
        raw = {}
    return resolve(raw)
