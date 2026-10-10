"""Terminal sessions for the Agent Workspace view (helpers/workspace.py), and
deterministic cleanup of them.

Sessions are stored per agent (`agent.get_data("_cet_state")`), so a
subordinate already has its own terminals; they used to be killed only when
the garbage collector got around to the session object. `kill_agent_terminals`
ends them at a known moment: when the chat is deleted or reset, when a
parallel worker finishes, or when a subordinate is replaced.

Only the shell itself is ended, never its process tree: a GUI app the agent
started from a terminal is a child of that shell and may hold unsaved work.
"""

from __future__ import annotations

from helpers import workspace

STATE_KEY = "_cet_state"


def _shells(agent) -> dict:
    state = agent.get_data(STATE_KEY) if agent is not None else None
    return dict(getattr(state, "shells", None) or {})


def _tty(wrap):
    return getattr(getattr(wrap, "session", None), "session", None)


def _children(pid) -> list[str]:
    try:
        import psutil

        return [p.name() for p in psutil.Process(int(pid)).children(recursive=True)][:8]
    except Exception:
        return []


def kill_agent_terminals(agent) -> int:
    """End every local shell this agent opened. Synchronous and idempotent."""
    killed = 0
    for wrap in _shells(agent).values():
        session = getattr(wrap, "session", None)
        kill = getattr(session, "kill", None)  # local sessions only; SSH shells keep their own lifecycle
        if callable(kill):
            try:
                kill()
                killed += 1
            except Exception:
                pass
    if killed:
        agent.set_data(STATE_KEY, None)
    return killed


def end_agent(agent) -> None:
    """Called by helpers.workspace.end_agent for a replaced agent chain."""
    for member in workspace.iter_chain(agent):
        kill_agent_terminals(member)


def kill_context_terminals(context) -> int:
    if context is None:
        return 0
    return sum(kill_agent_terminals(agent) for agent in workspace.iter_agents(context))


async def resources() -> list[dict]:
    from agent import AgentContext

    items = []
    for context in AgentContext.all():
        for agent in workspace.iter_agents(context):
            for number, wrap in sorted(_shells(agent).items()):
                tty = _tty(wrap)
                pid = getattr(getattr(tty, "_proc", None), "pid", None)
                children = _children(pid) if pid else []
                items.append({
                    "id": f"terminal:{context.id}:{agent.number}:{number}",
                    "kind": "terminal",
                    "label": f"Terminal session {number}",
                    "detail": str(getattr(wrap.session, "cwd", "") or ""),
                    "handle": {"pid": pid, "session": number, "agent": agent.number},
                    "owner_context": context.id,
                    "owner_agent": agent.agent_name,
                    "state": "active",
                    "note": ("Running: " + ", ".join(children)) if children else "",
                })
    return items


async def close_terminal(resource_id: str) -> bool:
    """Close one terminal listed by `resources()` (id `terminal:<context>:<agent>:<session>`)."""
    from agent import AgentContext

    try:
        _, context_id, agent_number, session = resource_id.split(":")
        number, session_no = int(agent_number), int(session)
    except ValueError:
        return False
    context = AgentContext.get(context_id)
    for agent in workspace.iter_agents(context) if context else []:
        if agent.number != number:
            continue
        state = agent.get_data(STATE_KEY)
        wrap = (getattr(state, "shells", None) or {}).pop(session_no, None)
        if wrap is None:
            return False
        try:
            await wrap.session.close()
        except Exception:
            kill = getattr(wrap.session, "kill", None)
            if callable(kill):
                kill()
        return True
    return False
