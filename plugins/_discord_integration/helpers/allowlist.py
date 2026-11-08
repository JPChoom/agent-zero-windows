"""Whether this chat's Discord bot has a non-empty allowlist, for
helpers/channel_approvals.py: phone approvals only on a closed channel."""

from __future__ import annotations


def channel_allowlist_set(context) -> bool:
    from plugins._discord_integration.helpers import constants as C

    cfg = (getattr(context, "data", None) or {}).get(C.CTX_BOT_CFG) or {}
    return bool(isinstance(cfg, dict) and cfg.get("allowed_users"))
