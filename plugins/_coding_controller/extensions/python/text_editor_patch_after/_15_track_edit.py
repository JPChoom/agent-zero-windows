from helpers.extension import Extension
from plugins._coding_controller.helpers import session_state
from plugins._coding_controller.helpers.config import get_config


class CodingControllerTrackPatch(Extension):
    """Marks the patched file's project root dirty so the completion gate
    (tool_execute_after/_80_completion_gate.py) knows to check it."""

    async def execute(self, data: dict | None = None, **kwargs):
        if not self.agent or not data:
            return
        path = str(data.get("path") or "")
        if not path:
            return
        cfg = get_config(self.agent)
        if not cfg["enforce_completion_gate"]:
            return  # opt-in: don't bother tracking when gating is off
        session_state.mark_dirty_for_path(self.agent, path)
