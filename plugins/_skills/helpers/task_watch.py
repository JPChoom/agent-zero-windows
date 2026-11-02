"""What the current task did, for learning skills from it.

A task is one turn of the top agent (A0): from the user's message to the
agent's answer. It is tracked on the chat context, so steps and sources of
subordinate agents count for the task they belong to. Recorded per task:
how long it took, how many tool steps, which outside sources were read
(learned.outside_source) and which learned skills were loaded.

When a task ends, its record becomes the chat's "last task", which is what
"learn that skill" refers to.
"""

from __future__ import annotations

import time

from plugins._skills.helpers import learned

CURRENT = "_skills_task"
LAST = "_skills_last_task"


def _context(agent):
    return getattr(agent, "context", None)


def start(agent) -> None:
    ctx = _context(agent)
    if ctx is None or getattr(agent, "number", 0) != 0:
        return
    message = getattr(getattr(agent, "loop_data", None), "user_message", None)
    text = message.output_text() if message is not None and hasattr(message, "output_text") else ""
    ctx.set_data(CURRENT, {
        "started": time.time(),
        "steps": 0,
        "sources": [],
        "used_skills": [],
        "user_message": str(text or "")[:4000],
    })


def on_tool(agent, tool_name: str, tool_args: dict | None, mcp: bool = False) -> None:
    ctx = _context(agent)
    task = ctx.get_data(CURRENT) if ctx is not None else None
    if not isinstance(task, dict):
        return
    if str(tool_name).split(":", 1)[0] not in ("response", "notify_user", "wait"):
        task["steps"] += 1
    source = learned.outside_source(tool_name, tool_args, mcp=mcp)
    if source and source not in task["sources"]:
        task["sources"].append(source)
    if str(tool_name).split(":", 1)[0] == "skills_tool":
        args = tool_args or {}
        action = str(args.get("action") or args.get("method") or "").lower()
        skill = str(args.get("skill_name") or args.get("name") or "").strip()
        if action == "load" and skill in learned.learned_names() and skill not in task["used_skills"]:
            task["used_skills"].append(skill)


def finish(agent, ok: bool) -> dict | None:
    """End the task; returns its record (also kept as the chat's last task)."""
    ctx = _context(agent)
    if ctx is None or getattr(agent, "number", 0) != 0:
        return None
    task = ctx.get_data(CURRENT)
    if not isinstance(task, dict):
        return None
    ctx.set_data(CURRENT, None)
    task["seconds"] = round(time.time() - task["started"], 1)
    task["ok"] = bool(ok)
    ctx.set_data(LAST, task)
    return task


def current(agent) -> dict | None:
    ctx = _context(agent)
    task = ctx.get_data(CURRENT) if ctx is not None else None
    return task if isinstance(task, dict) else None


def last(agent) -> dict | None:
    ctx = _context(agent)
    task = ctx.get_data(LAST) if ctx is not None else None
    return task if isinstance(task, dict) else None
