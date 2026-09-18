from typing import Any

from helpers.extension import Extension, extensible, best_effort
from helpers import skills as skills_helper
from helpers import projects
from helpers import debounced
from agent import Agent, LoopData

# list_skills() walks every configured skill root's directory tree and
# parses each skill.md's frontmatter, with no caching of its own, on
# every single prepare_prompt call - not just every turn, every prompt
# build. Skills change rarely; re-walking the same roots within a short
# window buys nothing.
SKILLS_LIST_TTL_SECONDS = 10.0


class SkillsPrompt(Extension):

    @best_effort("Skills prompt")
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        if prompt:
            system_prompt.append(prompt)


@extensible
async def build_prompt(agent: Agent) -> str:
    # Keyed on profile + project: both feed get_skill_roots()'s search
    # path resolution, so either changing must produce a fresh listing
    # rather than reusing another scope's cached result.
    profile = agent.config.profile or ""
    project_name = projects.get_context_project_name(agent.context) or ""
    cache_key = f"skills_prompt:{profile}:{project_name}"
    available = await debounced.run_debounced(
        cache_key, SKILLS_LIST_TTL_SECONDS, skills_helper.list_skills, agent=agent
    )
    result: list[str] = []
    for skill in available:
        name = skill.name.strip().replace("\n", " ")[:100]
        descr = skill.description.replace("\n", " ").strip()
        if len(descr) > 100:
            descr = descr[:100].rstrip() + "..."
        result.append(f"- {name}: {descr}" if descr else f"- {name}")

    if not result:
        return ""

    return agent.read_prompt("agent.system.skills.md", skills="\n".join(result))
