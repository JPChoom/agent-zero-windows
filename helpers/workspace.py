"""The Agent Workspace: which agent owns which Windows resources.

Apps an agent launches (Computer Use) are recorded here with their owner: the
chat (context), the agent inside it (A0, A1, ...), and the parallel job that
started them. Terminals and browser tabs already belong to an agent/context
by construction, so they are *read live* from their plugins (`PROVIDERS`)
rather than duplicated here.

Why it exists: a parallel worker runs in its own temporary context. An app it
launched used to be remembered only in that context, which is deleted when the
job ends, so the chat that started the job could no longer close the app or
type into it without an approval, and nothing listed it. Now, when a worker's
context ends, what it launched passes to the chat that started it; when a
normal chat is deleted its apps are marked orphaned (still running, listed,
never closed automatically: they may hold unsaved work).

Process ids are reused by Windows, so every app entry records the process's
start time and is trusted only while that same process is still running.
"""

from __future__ import annotations

import importlib
import threading
import time
import uuid
from dataclasses import asdict, dataclass

KIND_APP = "app"
ACTIVE = "active"
ORPHANED = "orphaned"

# Modules that list resources which already belong to an agent or context
# (terminal sessions, browser tabs). Each exposes `async def resources()`.
PROVIDERS = (
    "plugins._code_execution.helpers.workspace_provider",
    "plugins._browser.helpers.workspace_provider",
)

PARALLEL_PARENT_KEY = "_parallel_parent_context_id"  # helpers.parallel_tools
MAX_ENTRIES = 500

_lock = threading.RLock()
_resources: dict[str, "Resource"] = {}


@dataclass
class Resource:
    id: str
    kind: str
    handle: dict
    label: str
    owner_context: str
    owner_agent: str
    owner_profile: str
    origin_context: str
    origin_agent: str
    origin_job: str
    created_at: float
    state: str = ACTIVE
    note: str = ""
    changed_at: float = 0.0

    def public(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ processes

def process_start_time(pid) -> float | None:
    try:
        import psutil

        return psutil.Process(int(pid)).create_time()
    except Exception:
        return None


def _same_process(handle: dict) -> bool | None:
    """True while the recorded process is still the same one, False when it
    exited or its pid was reused, None when it cannot be told."""
    pid, started = handle.get("pid"), handle.get("started")
    if pid in (None, ""):
        return None
    try:
        import psutil

        process = psutil.Process(int(pid))
        if started is None:
            return True if process.is_running() else False
        return abs(process.create_time() - float(started)) < 1.0
    except ImportError:
        return None
    except Exception:  # NoSuchProcess, AccessDenied
        return False


# ------------------------------------------------------------------ registry

def _audit(event: str, **fields) -> None:
    try:
        from helpers import access_control

        access_control.audit(event, **fields)
    except Exception:
        pass


def _trim() -> None:
    if len(_resources) <= MAX_ENTRIES:
        return
    for rid in sorted(_resources, key=lambda r: _resources[r].created_at)[: len(_resources) - MAX_ENTRIES]:
        del _resources[rid]


def register_app(pid, label: str, *, context_id: str, agent_name: str = "", profile: str = "", job_id: str = "") -> Resource:
    """Record an app this agent launched (a new process, not one that was
    already running)."""
    handle = {"pid": int(pid), "started": process_start_time(pid)}
    with _lock:
        for existing in _resources.values():
            if existing.kind == KIND_APP and existing.handle.get("pid") == handle["pid"] and _same_process(existing.handle) is not False:
                existing.owner_context, existing.owner_agent = context_id, agent_name
                existing.state, existing.changed_at = ACTIVE, time.time()
                return existing
        now = time.time()
        resource = Resource(
            id="res-" + uuid.uuid4().hex[:8], kind=KIND_APP, handle=handle, label=label or f"pid {pid}",
            owner_context=context_id, owner_agent=agent_name, owner_profile=profile,
            origin_context=context_id, origin_agent=agent_name, origin_job=job_id,
            created_at=now, changed_at=now,
        )
        _resources[resource.id] = resource
        _trim()
    return resource


def find_app(pid) -> Resource | None:
    with _lock:
        for resource in list(_resources.values()):
            if resource.kind == KIND_APP and resource.handle.get("pid") == _as_int(pid):
                if _same_process(resource.handle) is False:
                    del _resources[resource.id]  # exited, or the pid now belongs to another process
                    continue
                return resource
    return None


def owns_app(context_id: str, pid) -> bool:
    """Whether this chat owns the (still running) app with that pid."""
    resource = find_app(pid)
    return bool(resource and resource.state == ACTIVE and resource.owner_context == context_id)


def forget_app(pid) -> None:
    with _lock:
        for resource in list(_resources.values()):
            if resource.kind == KIND_APP and resource.handle.get("pid") == _as_int(pid):
                del _resources[resource.id]


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def prune() -> None:
    """Drop apps that are no longer running."""
    with _lock:
        for resource in list(_resources.values()):
            if resource.kind == KIND_APP and _same_process(resource.handle) is False:
                del _resources[resource.id]


def apps(context_id: str | None = None) -> list[Resource]:
    prune()
    with _lock:
        items = list(_resources.values())
    if context_id is not None:
        items = [r for r in items if r.owner_context == context_id]
    return sorted(items, key=lambda r: r.created_at)


# ------------------------------------------------------------------ hand-over

def parent_context_id(context_id: str) -> str:
    """The chat that started this context as a parallel worker, if it is still alive."""
    try:
        from agent import AgentContext

        context = AgentContext.get(context_id)
        parent_id = context.get_data(PARALLEL_PARENT_KEY) if context else None
        return parent_id if parent_id and AgentContext.get(parent_id) else ""
    except Exception:
        return ""


def release_context(context_id: str) -> dict:
    """A context is ending. A parallel worker's apps pass to the chat that
    started it; any other chat's apps become orphans (kept running)."""
    parent = parent_context_id(context_id)
    handed = orphaned = 0
    with _lock:
        for resource in list(_resources.values()):
            if resource.owner_context != context_id or resource.state != ACTIVE:
                continue
            if _same_process(resource.handle) is False:
                del _resources[resource.id]
                continue
            resource.changed_at = time.time()
            if parent:
                resource.owner_context, resource.owner_agent = parent, ""
                resource.note = f"Handed over when {resource.origin_agent or 'a worker'}'s parallel job ended"
                handed += 1
                _audit("workspace_handover", resource=resource.id, kind=resource.kind, label=resource.label,
                       pid=resource.handle.get("pid"), from_context=context_id, to_context=parent)
            else:
                resource.state = ORPHANED
                resource.note = "Its chat was deleted; the app is still running"
                orphaned += 1
                _audit("workspace_orphaned", resource=resource.id, kind=resource.kind, label=resource.label,
                       pid=resource.handle.get("pid"), from_context=context_id)
    return {"handed_over": handed, "orphaned": orphaned, "to": parent}


def adopt(resource_id: str, context_id: str, agent_name: str = "", by: str = "") -> Resource | None:
    """Give a listed app to a chat (the user does this from the Workspace view)."""
    with _lock:
        resource = _resources.get(resource_id)
        if not resource or _same_process(resource.handle) is False:
            _resources.pop(resource_id, None)
            return None
        previous = resource.owner_context
        resource.owner_context, resource.owner_agent = context_id, agent_name
        resource.state, resource.changed_at = ACTIVE, time.time()
        resource.note = "Adopted by the user"
    _audit("workspace_adopt", by=by or "local", resource=resource_id, label=resource.label,
           pid=resource.handle.get("pid"), from_context=previous, to_context=context_id)
    return resource


def release(resource_id: str, by: str = "") -> bool:
    """Stop tracking an app: it becomes "the user's" again, so agents must ask
    before typing into it and cannot close it."""
    with _lock:
        resource = _resources.pop(resource_id, None)
    if resource:
        _audit("workspace_release", by=by or "local", resource=resource_id, label=resource.label,
               pid=resource.handle.get("pid"))
    return resource is not None


# ------------------------------------------------------------------ listing

def iter_chain(agent):
    """An agent and the chain of subordinates under it."""
    from agent import Agent

    seen = set()
    while agent is not None and id(agent) not in seen:
        seen.add(id(agent))
        yield agent
        agent = agent.get_data(Agent.DATA_NAME_SUBORDINATE)


def iter_agents(context):
    """The agent a context was created with and the chain of subordinates under it."""
    return iter_chain(getattr(context, "agent0", None))


def end_agent(agent) -> None:
    """An agent (and its subordinates) is being replaced: let each provider end
    what it opened now (terminal shells), instead of whenever garbage
    collection runs. Never raises."""
    for module_name in PROVIDERS:
        try:
            end = getattr(importlib.import_module(module_name), "end_agent", None)
            if callable(end):
                end(agent)
        except Exception:
            continue


def context_label(context_id: str) -> str:
    try:
        from agent import AgentContext

        context = AgentContext.get(context_id)
        if context:
            return str(context.name or f"Chat {str(context_id)[:6]}")
    except Exception:
        pass
    return "(deleted chat)"


async def snapshot() -> dict:
    """Everything the Workspace view lists: tracked apps plus terminals and
    browser tabs read live from their plugins."""
    items = [r.public() for r in apps()]
    for module_name in PROVIDERS:
        try:
            module = importlib.import_module(module_name)
            items.extend(await module.resources())
        except Exception:
            continue
    contexts = sorted({str(i.get("owner_context") or "") for i in items} - {""})
    return {"resources": items, "contexts": {cid: context_label(cid) for cid in contexts}}
