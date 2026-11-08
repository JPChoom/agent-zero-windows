"""Whether this chat's WhatsApp account has a non-empty allowlist, for
helpers/channel_approvals.py: phone approvals only on a closed channel."""

from __future__ import annotations


def channel_allowlist_set(context) -> bool:
    from helpers import plugins

    return bool((plugins.get_plugin_config("_whatsapp_integration") or {}).get("allowed_numbers"))
