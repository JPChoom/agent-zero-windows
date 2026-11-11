from typing import Any

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class DrainChannelOutbox(Extension):
    """Retry channel replies that could not be delivered (helpers/channel_delivery.py)."""

    async def execute(self, data: dict[str, Any] | None = None, **kwargs):
        try:
            from helpers import channel_delivery

            await channel_delivery.drain()
        except Exception as e:
            PrintStyle.error(f"Channel outbox retry failed: {e}")
