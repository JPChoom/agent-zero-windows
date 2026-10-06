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


# Skill families listed as one line instead of one line each (name prefix ->
# collapsed). The always-on catalog costs prompt tokens on every turn, and the
# plugin-development family (a0-*) is rarely needed. Collapsed skills are
# still searchable and loadable by name.
DEFAULT_COLLAPSE_PREFIXES = ("a0-",)
MIN_COLLAPSE_COUNT = 3


def _collapse_prefixes(agent: Agent) -> tuple[str, ...]:
    from helpers import plugins

    try:
        cfg = plugins.get_plugin_config("_skills", agent=agent) or {}
    except Exception:
        cfg = {}
    raw = cfg.get("catalog_collapse_prefixes", DEFAULT_COLLAPSE_PREFIXES)
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_COLLAPSE_PREFIXES
    return tuple(str(p).strip() for p in raw if str(p).strip())


def _collapse_prefixed(skills: list, prefixes: tuple[str, ...], lines: list[str]) -> list:
    """Remove each prefix family from `skills` and add one summary line to `lines`."""
    remaining = list(skills)
    for prefix in prefixes:
        family = [s for s in remaining if s.name.startswith(prefix)]
        if len(family) < MIN_COLLAPSE_COUNT:
            continue
        remaining = [s for s in remaining if s not in family]
        names = ", ".join(s.name for s in family)
        lines.append(
            f"- {prefix}* ({len(family)} skills; search or load by name): {names}"
        )
    return remaining


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
    available = _collapse_prefixed(available, _collapse_prefixes(agent), result)
    for skill in available:
        name = skill.name.strip().replace("\n", " ")[:100]
        descr = skill.description.replace("\n", " ").strip()
        if len(descr) > 100:
            descr = descr[:100].rstrip() + "..."
        result.append(f"- {name}: {descr}" if descr else f"- {name}")

    if not result:
        return ""

    return agent.read_prompt("agent.system.skills.md", skills="\n".join(result))
