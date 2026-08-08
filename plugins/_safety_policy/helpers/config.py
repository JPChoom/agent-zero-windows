"""Reads and normalizes _safety_policy's plugin config."""

from helpers import plugins

# Kept in sync with policy._DENY_CATEGORIES' keys - not imported directly to
# avoid a config-module -> policy-module import for what's really just a
# fixed list of category names used to build per-category config keys
# (tier_<category>).
_CATEGORY_KEYS = (
    "downloader",
    "persistence",
    "credential_access",
    "obfuscation",
    "destructive_delete",
    "disk_and_reboot",
    "firewall_and_defender",
    "privilege_escalation",
    "account_changes",
)


def get_config(agent) -> dict:
    cfg = plugins.get_plugin_config("_safety_policy", agent=agent) or {}
    return {
        "enforce_policy": _as_bool(cfg.get("enforce_policy", True)),
        "custom_deny_patterns": _parse_patterns(cfg.get("custom_deny_patterns", "")),
        "approval_tier_categories": _resolve_approval_categories(cfg),
        "approval_timeout_seconds": _as_int(cfg.get("approval_timeout_seconds", 300), default=300),
    }


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_patterns(raw) -> list[str]:
    lines = [str(p) for p in raw] if isinstance(raw, list) else str(raw).splitlines()
    return [p.strip() for p in lines if p.strip()]


def _resolve_approval_categories(cfg: dict) -> set[str]:
    # Deferred import: policy.py doesn't import config.py, so this isn't a
    # cycle, but keeping it local documents that the only reason config.py
    # touches policy.py at all is to read this one default set.
    from plugins._safety_policy.helpers.policy import _APPROVAL_TIER_DEFAULT_CATEGORIES

    result: set[str] = set()
    for category in _CATEGORY_KEYS:
        default = "approve" if category in _APPROVAL_TIER_DEFAULT_CATEGORIES else "deny"
        value = str(cfg.get(f"tier_{category}", default) or default).strip().lower()
        if value not in ("deny", "approve"):
            value = default
        if value == "approve":
            result.add(category)
    return result
