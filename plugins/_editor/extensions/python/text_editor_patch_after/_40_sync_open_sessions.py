from __future__ import annotations

from typing import Any

from helpers.extension import Extension, best_effort
from plugins._editor.helpers import markdown_sessions


class SyncOpenEditorSessionsAfterTextEditorPatch(Extension):
    @best_effort("Editor session sync (patch)")
    async def execute(self, data: dict[str, Any] | None = None, **kwargs: Any):
        path = str((data or {}).get("path") or "").strip()
        if not path:
            return
        markdown_sessions.get_manager().sync_external_file_mutations([path])
