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

import re
import time

from plugins._skills.helpers import learned

# A tool result that reports a problem: counted per task as a rough measure of
# how smoothly a learned skill worked.
_TROUBLE = re.compile(r"\b(error|exception|traceback|failed|denied|not found|timed out)\b", re.IGNORECASE)
MATCHED_SKILLS = 3

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
        "errors": 0,
        "matched": _matched_skills(agent, str(text or "")),
        "user_message": str(text or "")[:4000],
    })


def _matched_skills(agent, request: str) -> list[str]:
    """Learned skills a search for this request would surface: if one is
    never loaded, matching is the problem, not the skill."""
    if not request.strip():
        return []
    try:
        from helpers import skills as skills_helper

        names = learned.learned_names()
        found = skills_helper.search_skills(request, limit=MATCHED_SKILLS, agent=agent)
        return [skill.name for skill in found if skill.name in names]
    except Exception:
        return []


def on_result(agent, response) -> None:
    ctx = _context(agent)
    task = ctx.get_data(CURRENT) if ctx is not None else None
    if isinstance(task, dict) and _TROUBLE.search(str(getattr(response, "message", "") or "")[:4000]):
        task["errors"] = int(task.get("errors", 0)) + 1


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
