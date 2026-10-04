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


_DEFAULT_NETWORK_ALLOWLIST = ("nuget.org", "npmjs.org", "pypi.org", "github.com", "localhost", "127.0.0.1")


def get_config(agent) -> dict:
    cfg = plugins.get_plugin_config("_safety_policy", agent=agent) or {}
    return {
        "enforce_policy": _as_bool_fail_closed(cfg.get("enforce_policy", True)),
        "custom_deny_patterns": _parse_patterns(cfg.get("custom_deny_patterns", "")),
        "approval_tier_categories": _resolve_approval_categories(cfg),
        "approval_timeout_seconds": _as_int(cfg.get("approval_timeout_seconds", 300), default=300),
        "enable_network_destination_allowlist": _as_bool(cfg.get("enable_network_destination_allowlist", False)),
        "network_destination_allowlist": _parse_patterns(
            cfg.get("network_destination_allowlist", list(_DEFAULT_NETWORK_ALLOWLIST))
        ),
    }


def add_allowed_host(host: str) -> str:
    """Persist `host` to the global network_destination_allowlist and turn
    the allowlist on - backs the "Always allow <host>" approval button.
    Written at global scope (empty project/profile), same as
    _permissions' "always allow": a decision made once should not apply
    only to whichever project happened to be open. Returns the stored
    host; raises ValueError for an empty/malformed one."""
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized or any(c.isspace() or c in "/:@*" for c in normalized):
        raise ValueError(f"not a plain host name: {host!r}")

    current = plugins.get_plugin_config("_safety_policy", project_name="", agent_profile="") or {}
    allowlist = _parse_patterns(
        current.get("network_destination_allowlist", list(_DEFAULT_NETWORK_ALLOWLIST))
    )
    if normalized not in (h.lower() for h in allowlist):
        allowlist.append(normalized)

    plugins.save_plugin_config(
        "_safety_policy", "", "",
        {**current, "network_destination_allowlist": allowlist, "enable_network_destination_allowlist": True},
    )
    return normalized


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_bool_fail_closed(value) -> bool:
    """Like _as_bool, but for enforce_policy specifically: this flag's
    whole job is gating command denial, and its documented default is
    "on". _as_bool's "unrecognized value -> False" behavior is fine for
    ordinary settings (an opt-in feature staying off on a typo is a
    reasonable failure mode) but wrong here - a corrupted config file or
    a stray placeholder string must not silently turn enforcement off.
    Only an explicit false-like value disables it; anything else
    (including garbage) keeps enforcement on."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


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
