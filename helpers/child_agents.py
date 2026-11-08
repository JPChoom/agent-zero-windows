"""Independent child agents: named agents in chats of their own.

`call_subordinate` runs one subordinate inside the parent's chat: they share
its log and lifecycle, and the subordinate is replaced when the profile
changes. A child agent instead gets its own chat (shown nested under the
parent in the sidebar), its own history and its own task, so it can:

- keep its work across messages and restarts, by name (`message` resumes it);
- run while the parent continues (`wait: false`), several at once;
- be stopped from its own chat or by the parent, without stopping the parent;
- use its own profile, and so its own model (job routing).

It acts for the parent's chat: that chat's permission mode, messaging limits
and the parent's capability limits apply (helpers/parallel_tools
.governing_context, plugins/_capabilities). A parent waiting on a child that
is stopped stops the child too; resetting or deleting a parent chat stops its
children.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from helpers import parallel_tools

if TYPE_CHECKING:
    from agent import Agent, AgentContext

CHILDREN_KEY = "child_agents"  # parent context data: {name: child context id}; persisted
CHILD_OF_KEY = "child_of"  # child context data: parent context id; persisted
MAX_CHILDREN = 8
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class ChildAgentError(ValueError):
    pass


def normalize_name(name: Any) -> str:
    value = str(name or "").strip().lower().replace(" ", "-")
    if not NAME_RE.match(value):
        raise ChildAgentError("A child agent needs a short name: letters, digits, - or _ (for example tests or research).")
    return value


def registry(parent: "AgentContext") -> dict[str, str]:
    value = parent.get_data(CHILDREN_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _save_registry(parent: "AgentContext", value: dict[str, str]) -> None:
    parent.set_data(CHILDREN_KEY, value)


def _get_context(context_id: str) -> "AgentContext | None":
    from agent import AgentContext

    return AgentContext.get(context_id)


def find(parent: "AgentContext", name: str) -> "AgentContext | None":
    child_id = registry(parent).get(name)
    return _get_context(child_id) if child_id else None


def _bind(child: "AgentContext", parent: "AgentContext", agent: "Agent") -> None:
    """Runtime links: re-applied on every run, because keys starting with _
    are not saved with a chat."""
    child.set_data(parallel_tools.PARALLEL_WORKER_PARENT_CONTEXT_KEY, parent.id)
    child.set_data(parallel_tools.PARALLEL_WORKER_KIND_KEY, "subordinate")
    child.set_data(CHILD_OF_KEY, parent.id)
    try:
        from plugins._capabilities.helpers import policy

        child.set_data(policy.CONTEXT_SCOPES_KEY, policy.worker_scopes(agent))
    except Exception:
        pass


def _create(parent: "AgentContext", agent: "Agent", name: str, profile: str) -> "AgentContext":
    from agent import AgentContext, AgentContextType

    child = AgentContext(
        config=parallel_tools._clone_config(parent.config, profile=profile),
        name=f"{name} (child of {parent.name or parent.id})",
        type=AgentContextType.USER,
    )
    child.set_output_data(parallel_tools.CHILD_PARENT_CONTEXT_ID_KEY, parent.id)
    child.set_output_data(parallel_tools.CHILD_PARENT_CONTEXT_KIND_KEY, "child")
    child.set_output_data(parallel_tools.CHILD_PARENT_CONTEXT_LABEL_KEY, name)
    parallel_tools._copy_project(parent, child)
    return child


def _state(child: "AgentContext | None") -> str:
    if child is None:
        return "gone"
    return "running" if child.is_running() else "idle"


def describe(parent: "AgentContext") -> list[dict[str, Any]]:
    result = []
    for name, child_id in registry(parent).items():
        child = find(parent, name)
        profile = getattr(getattr(child, "config", None), "profile", "") if child else ""
        result.append({"name": name, "id": child_id, "state": _state(child), "profile": profile or "default"})
    return result


async def send(agent: "Agent", name: str, message: str, profile: str = "", wait: bool = True,
               timeout: float | None = None) -> dict[str, Any]:
    """Start the child `name`, or give an existing one its next task."""
    from agent import UserMessage
    from helpers import message_queue, persist_chat

    parent = agent.context
    name = normalize_name(name)
    if not str(message or "").strip():
        raise ChildAgentError("A child agent needs a message: its role, goal and task.")
    children = registry(parent)
    child = find(parent, name)
    if child is None:
        if name not in children and len(children) >= MAX_CHILDREN:
            raise ChildAgentError(f"This chat already has {MAX_CHILDREN} child agents. Forget one first.")
        child = _create(parent, agent, name, profile)
        children[name] = child.id
        _save_registry(parent, children)
    else:
        current = str(getattr(child.config, "profile", "") or "")
        if profile and profile != current:
            raise ChildAgentError(f"Child '{name}' uses profile '{current or 'default'}'. Forget it and start a new one to change profile.")
        if child.is_running():
            raise ChildAgentError(f"Child '{name}' is still working. Wait for its result, or stop it first.")

    _bind(child, parent, agent)
    message_queue.log_user_message(child, message, [], source=f" (from {agent.agent_name})")
    task = child.communicate(UserMessage(message=message, attachments=[]))
    persist_chat.save_tmp_chat(child)
    persist_chat.save_tmp_chat(parent)
    if not wait:
        return {"name": name, "id": child.id, "state": "running"}
    return await result(agent, name, timeout=timeout, task=task)


async def result(agent: "Agent", name: str, timeout: float | None = None, task=None) -> dict[str, Any]:
    """Wait for the child's current task; stopping the waiting parent stops it."""
    from helpers import persist_chat

    parent = agent.context
    name = normalize_name(name)
    child = find(parent, name)
    if child is None:
        raise ChildAgentError(f"No child agent called '{name}' in this chat.")
    task = task or child.task
    if task is None:  # never given a task since a restart: report its last answer
        return {"name": name, "id": child.id, "state": _state(child), "result": _last_reply(child)}
    try:
        reply = await task.result(timeout=timeout)
    except asyncio.CancelledError:
        child.kill_process()  # the parent was stopped while it waited
        raise
    except (TimeoutError, asyncio.TimeoutError):
        return {"name": name, "id": child.id, "state": "running", "note": "still working; ask for its result again later"}
    finally:
        persist_chat.save_tmp_chat(child)
    return {"name": name, "id": child.id, "state": _state(child), "result": str(reply or "")}


def _last_reply(child: "AgentContext") -> str:
    try:
        for message in reversed(child.agent0.history.current.messages):
            if getattr(message, "ai", False):
                return str(message.output_text())[-4000:]
    except Exception:
        pass
    return ""


def stop(parent: "AgentContext", name: str) -> dict[str, Any]:
    name = normalize_name(name)
    child = find(parent, name)
    if child is None:
        raise ChildAgentError(f"No child agent called '{name}' in this chat.")
    child.kill_process()
    stop_all(child)  # its own children too
    return {"name": name, "id": child.id, "state": "stopped"}


def forget(parent: "AgentContext", name: str) -> dict[str, Any]:
    """Stop the child and drop it from this chat's list; its chat stays in the
    sidebar so its work can still be read."""
    name = normalize_name(name)
    children = registry(parent)
    if name not in children:
        raise ChildAgentError(f"No child agent called '{name}' in this chat.")
    child = find(parent, name)
    if child is not None:
        child.kill_process()
        stop_all(child)
    children.pop(name)
    _save_registry(parent, children)
    return {"name": name, "state": "forgotten"}


def stop_all(parent: "AgentContext") -> int:
    """Stop every child (and their children); used when a parent chat is
    reset or deleted."""
    stopped = 0
    for name in list(registry(parent)):
        child = find(parent, name)
        if child is not None and child is not parent:
            if child.is_running():
                child.kill_process()
                stopped += 1
            stopped += stop_all(child)
    return stopped
