"""POST /api/plugins/_a0_connector/v1/skills_delete."""
from __future__ import annotations

import json

from helpers.api import Request, Response
import plugins._a0_connector.api.v1.base as connector_base


class SkillsDelete(connector_base.ProtectedConnectorApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        from helpers import files, skills

        skill_path = str(input.get("skill_path") or "").strip()
        if not skill_path:
            return Response(
                response='{"error":"skill_path is required"}',
                status=400,
                mimetype="application/json",
            )

        normalized_path = files.normalize_a0_path(files.fix_dev_path(skill_path))
        catalog = skills.list_skill_catalog(project_name=str(input.get("project_name") or ""))
        match = next(
            (item for item in catalog if str(item.get("path") or "").rstrip("/") == normalized_path.rstrip("/")),
            None,
        )
        if not match:
            return Response(
                response='{"error":"skill_path is not in the enabled skill catalog"}',
                status=404,
                mimetype="application/json",
            )
        if match.get("origin") not in {"User", "Project"}:
            return Response(
                response='{"error":"only user or project skills can be deleted"}',
                status=403,
                mimetype="application/json",
            )

        try:
            skills.delete_skill(normalized_path)
        except PermissionError as exc:
            return Response(
                response=json.dumps({"error": str(exc)}),
                status=403,
                mimetype="application/json",
            )
        return {
            "ok": True,
            "data": {
                "skill_path": normalized_path,
            },
        }
