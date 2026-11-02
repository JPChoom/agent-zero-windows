"""The Learned skills window: list, view, edit, approve, turn off, delete.

Signed-in, CSRF-checked WebUI only (ApiHandler). Approving a skill that
waits for review is the user's decision; edits go through the same checks
as a draft (learned.check_draft) and keep the old text as a version.
"""

from __future__ import annotations

from helpers.api import ApiHandler, Request
from plugins._skills.helpers import auto_learn, learned


class LearnedSkills(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "list").strip().lower()
        name = str(input.get("name") or "")
        try:
            if action == "list":
                return {"ok": True, "skills": learned.list_all(), "settings": auto_learn.settings()}
            if action == "get":
                return {"ok": True, **learned.get_content(name)}
            if action == "save":
                version = learned.save_edit(name, str(input.get("content") or ""))
                return {"ok": True, "version": version}
            if action == "approve":
                learned.approve(name)
            elif action == "discard":
                learned.discard(learned.validate_name(name))
            elif action == "disable":
                learned.disable(name)
            elif action == "enable":
                learned.enable(name)
            elif action == "delete":
                learned.delete(name)
            elif action == "restore":
                version = learned.restore_version(name, int(input.get("version") or 0))
                return {"ok": True, "version": version}
            else:
                return {"ok": False, "error": f"Unknown action {action!r}."}
            return {"ok": True}
        except (ValueError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}
