"""Thin wrapper around the subordinate-spawn pattern for scoped, one-shot
coding sub-agent calls (independent review, root-cause diagnosis).

Deliberately does NOT use tools/call_subordinate.py's Delegation tool or
its single-subordinate-slot mechanism (Agent.DATA_NAME_SUBORDINATE) - that
slot may already be in use for an unrelated, ongoing delegation the agent
or user initiated, and clobbering it here would silently lose that state.
Instead this spawns a throwaway Agent instance directly (initialize_agent +
Agent(...) + monologue()), the same way tools/call_subordinate.py does
internally, scoped entirely to one call.

This is the single implementation of "spawn a scoped subordinate and run
it to completion" - plugins/_coding_controller/helpers/reviewer.py and
diagnostician.py both call through here rather than each duplicating the
spawn/wire-up logic.
"""

from dataclasses import dataclass


@dataclass
class RoleAgent:
    """Wraps a spawned sub-agent instance with the profile it was created
    for, so callers (and error messages) don't need to reach into agent
    internals."""

    agent: object
    profile: str


async def create_role(parent_agent, profile: str) -> RoleAgent:
    """Spawn a fresh Agent running the given profile, wired as a
    subordinate of parent_agent (shares parent_agent's AgentContext, so it
    shows up in the same chat/log rather than opening a new one)."""
    from agent import Agent
    from initialize import initialize_agent

    config = initialize_agent(override_settings={"agent_profile": profile})
    role_agent = Agent(parent_agent.number + 1, config, parent_agent.context)
    role_agent.set_data(Agent.DATA_NAME_SUPERIOR, parent_agent)
    return RoleAgent(agent=role_agent, profile=profile)


async def send_task(role: RoleAgent, message: str) -> str:
    """Send a task message to the role agent and run it to completion,
    returning its final response text."""
    from agent import UserMessage

    role.agent.hist_add_user_message(UserMessage(message=message, attachments=[]))
    return await role.agent.monologue()


def terminate_role(role: RoleAgent) -> None:
    """Best-effort cleanup after a role agent's task is done.

    role_agent shares the parent's AgentContext (see create_role) rather
    than owning its own, so there is no context to tear down here - this
    just drops the role agent's own scratch data so it isn't held onto
    past its one-shot use.
    """
    try:
        role.agent.data.clear()
    except Exception:
        pass
