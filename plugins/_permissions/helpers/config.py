"""Resolved permission settings.

Kept separate from rules.py so the decision engine stays free of Agent
Zero imports and remains testable on its own.
"""

from __future__ import annotations

from plugins._permissions.helpers import rules


# Must match default_config.yaml. get_plugin_config returns only values
# that have actually been set, so the YAML defaults are never merged in
# and these fallbacks are what really apply - a mismatch here silently
# beats the documented default.
DEFAULTS = {
    "deny": "",
    "ask": "",
    "allow": "",
    "approval_timeout_seconds": 300,
    "audit_decisions": True,
}


def get_config(agent=None) -> dict:
    """Rules and timeouts from plugin config; the *mode* is per chat and
    in memory (helpers/mode_state.py). A `mode` key left in an old
    config.json is ignored - persisted config can't switch on bypass."""
    from helpers import plugins
    from plugins._permissions.helpers import mode_state

    cfg = plugins.get_plugin_config("_permissions", agent=agent) or {}

    context = getattr(agent, "context", None)
    state = mode_state.get_mode(
        getattr(context, "id", None),
        mode_state.context_project(context) if context is not None else "",
    )

    try:
        timeout = int(cfg.get("approval_timeout_seconds",
                              DEFAULTS["approval_timeout_seconds"]))
    except (TypeError, ValueError):
        timeout = DEFAULTS["approval_timeout_seconds"]

    return {
        "mode": state["mode"],
        "bypass_expired": state["expired"],
        "ruleset": rules.Ruleset.from_config(cfg),
        "approval_timeout_seconds": max(5, timeout),
        "audit_decisions": bool(
            cfg.get("audit_decisions", DEFAULTS["audit_decisions"])
        ),
    }


def _save(updates: dict, project_name: str = "", agent_profile: str = "") -> None:
    """Merge `updates` into the stored config.

    Written at global scope by default (empty project and profile), which
    is where the mode selector and the "always allow" button belong: a
    permission decision the user makes once should not silently apply to
    only the project that happened to be open.
    """
    from helpers import plugins

    current = plugins.get_plugin_config(
        "_permissions", project_name=project_name, agent_profile=agent_profile
    ) or {}
    plugins.save_plugin_config(
        "_permissions", project_name, agent_profile, {**current, **updates}
    )


def add_rule(kind: str, rule_text: str) -> str:
    """Append a rule to deny/ask/allow, ignoring exact duplicates.

    Backs the "always allow" affordance on an approval prompt: answering a
    question once should stop it being asked again.
    """
    from helpers import plugins

    if kind not in ("deny", "ask", "allow"):
        raise ValueError(f"unknown rule list {kind!r}")
    parsed = rules.Rule.parse(rule_text)  # raises RuleError if malformed

    current = plugins.get_plugin_config(
        "_permissions", project_name="", agent_profile=""
    ) or {}
    lines = [
        line.strip()
        for line in str(current.get(kind) or "").splitlines()
        if line.strip()
    ]
    if parsed.source not in lines:
        lines.append(parsed.source)

    _save({kind: "\n".join(lines)})
    return parsed.source
