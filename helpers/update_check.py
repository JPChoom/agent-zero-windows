from helpers import windows_update


async def check_version() -> dict:
    """Notification payload when a newer Agent Zero for Windows release is
    published on GitHub. Nothing about this install is sent."""
    result = await windows_update.check()
    if not result.get("update_available"):
        return {}
    latest = result["latest"]
    return {
        "notification": {
            "id": f"update_check_{latest['tag']}",
            "group": "update_check",
            "type": "info",
            "title": f"Agent Zero for Windows {latest['tag']} is available",
            "message": f"You have {result.get('current_version') or 'an older version'}. "
                       "Open Settings > Check for updates to review and install it.",
            "display_time": 10,
        }
    }
