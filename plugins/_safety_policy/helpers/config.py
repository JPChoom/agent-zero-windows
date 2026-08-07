"""Reads and normalizes _safety_policy's plugin config."""

from helpers import plugins


def get_config(agent) -> dict:
    cfg = plugins.get_plugin_config("_safety_policy", agent=agent) or {}
    return {
        "enforce_policy": _as_bool(cfg.get("enforce_policy", True)),
        "custom_deny_patterns": _parse_patterns(cfg.get("custom_deny_patterns", "")),
    }


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_patterns(raw) -> list[str]:
    lines = [str(p) for p in raw] if isinstance(raw, list) else str(raw).splitlines()
    return [p.strip() for p in lines if p.strip()]
