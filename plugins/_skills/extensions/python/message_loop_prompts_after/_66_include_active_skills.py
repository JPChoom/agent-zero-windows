from __future__ import annotations

from helpers import skills
from agent import LoopData
from helpers.extension import Extension


class IncludeActiveSkills(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        protocol = loop_data.protocol_persistent
        protocol.pop("active_skills", None)

        content = skills.build_active_skills_prompt(self.agent)
        if not content:
            return

        protocol["active_skills"] = self.agent.read_prompt(
            "agent.system.active_skills.md",
            skills=content,
        )
