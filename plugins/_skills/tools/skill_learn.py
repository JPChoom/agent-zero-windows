"""Agent-facing tool: save a procedure the agent just worked out as a skill.

Only after the user said yes in chat. The draft is checked (injection
phrasing, encoded/downloaded code, security switches, credentials), written
to the hidden pending folder, and shown to the user on an Approve/Deny card;
nothing is loaded as a skill until they approve. Updating a learned skill
creates the next version and keeps the old one. See helpers/learned.py.
"""

from __future__ import annotations

from helpers import untrusted_content
from helpers.errors import RepairableException
from helpers.tool import Response, Tool
from plugins._skills.helpers import learned


class SkillLearn(Tool):

    async def execute(self, action: str = "draft", **kwargs) -> Response:
        action = str(action or "draft").strip().lower()
        if action == "list":
            active, pending = learned.list_learned()
            lines = [f"- {s['name']} v{s['version']} ({s['created']}): {s['description']}" for s in active]
            return Response(
                message="Agent-learned skills:\n" + ("\n".join(lines) or "(none)")
                + ("\nAwaiting approval: " + ", ".join(pending) if pending else ""),
                break_loop=False,
            )
        if action != "draft":
            return Response(message="Unknown action. Use draft or list.", break_loop=False)
        return await self._draft(**kwargs)

    async def _draft(self, name: str = "", description: str = "", procedure: str = "", triggers=None, **kwargs) -> Response:
        try:
            name = learned.validate_name(name)
        except ValueError as exc:
            raise RepairableException(f"[skill_learn] {exc}")
        description = str(description or "").strip()
        body = str(procedure or "").strip()
        if len(description) < 20:
            raise RepairableException("[skill_learn] description must say what the skill does and when to use it (20+ characters).")

        problems = learned.check_draft(description, body)
        if problems:
            raise RepairableException(
                "[skill_learn] Refused: " + "; ".join(problems)
                + ". Rewrite the procedure without it, or tell the user why it can't be saved."
            )

        version = learned.current_version(name) + 1
        chat = str(getattr(self.agent.context, "id", "") or "")
        path = learned.write_draft(name, learned.render(name, description, body, version, chat, triggers))

        notes = [f"save '{name}' v{version} as an agent-learned skill ({path})"]
        if version > 1:
            notes.append(f"replaces v{version - 1}, which is kept in .versions/")
        if untrusted_content.is_tainted(self.agent):
            notes.append("this chat read outside content (web pages, files or command output) - check the procedure carefully")
        preview = body if len(body) <= 600 else body[:600] + "..."
        notes.append(f"procedure: {preview}")

        from plugins._permissions.helpers.ask import request_approval
        from plugins._permissions.helpers.config import get_config as perm_config

        pcfg = perm_config(self.agent)
        try:
            # Asked in every mode, Bypass included: a skill is a standing
            # instruction the agent will follow in future chats.
            await request_approval(
                self.agent, "skill_learn", {"action": "draft", "name": name},
                "; ".join(notes), pcfg["mode"], pcfg["approval_timeout_seconds"], offer_rules=False,
            )
        except RepairableException:
            learned.discard(name)
            raise

        target, old = learned.install(name)
        return Response(
            message=f"Saved skill '{name}' v{version} at {target}" + (f" (v{old} kept in .versions/)." if old else ".")
            + " It is available from the next message on.",
            break_loop=False,
        )
