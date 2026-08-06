from __future__ import annotations

from typing import Any

from helpers.extension import Extension
from plugins._office.api.ws_office import WsOffice


class OfficeWebuiWsDisconnect(Extension):
    async def execute(
        self,
        instance: Any = None,
        sid: str = "",
        **kwargs: Any,
    ) -> None:
        if instance is None:
            return
        handler = WsOffice(
            instance.socketio,
            instance.lock,
            manager=instance.manager,
            namespace=instance.namespace,
        )
        await handler.on_disconnect(sid)
