from typing import Any, TYPE_CHECKING
from helpers.files import VariablesPlugin
from helpers import projects, subagents

if TYPE_CHECKING:
    from agent import Agent

# One line per profile. Each profile used to be injected as a JSON object
# with its full title, description and delegation context - about 2,100
# tokens of always-on system prompt for ~10 profiles, the single largest
# tool entry. A short line is enough to pick a profile; the subordinate
# loads its own full prompt when called.
PROFILE_LINE_CHARS = 160


def _first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    for stop in (". ", "; "):
        cut = text.find(stop)
        if 0 < cut < PROFILE_LINE_CHARS:
            return text[: cut + 1]
    return text if len(text) <= PROFILE_LINE_CHARS else text[: PROFILE_LINE_CHARS - 3].rstrip() + "..."


class CallSubordinate(VariablesPlugin):
    def get_variables(
        self, file: str, backup_dirs: list[str] | None = None, **kwargs
    ) -> dict[str, Any]:

        # current agent instance
        agent: Agent | None = kwargs.get("_agent", None)
        # current project
        project = projects.get_context_project_name(agent.context) if agent else None
        # available agents in project (or global)
        agents = subagents.get_available_agents_dict(project)

        if not agents:
            return {"agent_profiles": None}

        lines = []
        for name, subagent in agents.items():
            summary = _first_sentence(subagent.context or subagent.description or subagent.title)
            lines.append(f"- {name}: {summary}" if summary else f"- {name}")
        return {"agent_profiles": "\n".join(lines)}
