"""Learning a skill on its own after a long, successful task.

Runs after the top agent's turn ends (monologue_end), in the background and
at low priority: the utility model is only asked in a gap between the user's
turns and gives the model back as soon as a turn needs it
(model_concurrency.run_when_idle), like memorizing does.

1. worth_trying(): the task was answered, long enough (settings
   `auto_learn_min_steps` / `auto_learn_min_seconds`), and did not already
   use a learned skill (then that skill covered it; its use is recorded).
2. The utility model reads the task (request + transcript) and the closest
   existing skills and decides: learn a new skill, update one, or nothing
   (one-off, failed, already covered).
3. The draft passes learned.check_draft (injection phrasing, encoded or
   downloaded code, security switches, credentials) or is dropped.
4. A task that only used the user's own PC: the skill goes live at once.
   A task that read outside content (learned.outside_source): it waits for
   the user under "Needs a look" (Learned skills window).
"""

from __future__ import annotations

from helpers import model_concurrency, perf
from helpers.dirty_json import DirtyJson
from plugins._skills.helpers import learned

TRANSCRIPT_CHARS = 30000
SIMILAR_SKILLS = 5


def settings(agent=None) -> dict:
    from helpers import plugins

    cfg = plugins.get_plugin_config("_skills", agent) or {}
    return {
        "enabled": bool(cfg.get("auto_learn", True)),
        "min_steps": int(cfg.get("auto_learn_min_steps", 8) or 8),
        "min_seconds": int(cfg.get("auto_learn_min_seconds", 180) or 180),
    }


def worth_trying(task: dict | None, cfg: dict) -> str:
    """"" when the task is worth a look, else why not."""
    if not task:
        return "no task"
    if not task.get("ok"):
        return "the task did not end with an answer"
    if task.get("used_skills"):
        return "a learned skill already covered it"
    steps, seconds = int(task.get("steps", 0)), float(task.get("seconds", 0))
    if steps >= cfg["min_steps"] or (seconds >= cfg["min_seconds"] and steps >= 4):
        return ""
    return "the task was short"


def _similar_skills(agent, request: str) -> list[dict]:
    from helpers import skills as skills_helper

    try:
        found = skills_helper.search_skills(request, limit=SIMILAR_SKILLS, agent=agent)
    except Exception:
        return []
    names = learned.learned_names()
    return [{"name": s.name, "description": s.description, "learned": s.name in names} for s in found]


def _transcript(agent) -> str:
    try:
        text = agent.history.current.output_text(human_label="user", ai_label="agent")
    except Exception:
        return ""
    return text if len(text) <= TRANSCRIPT_CHARS else "...\n" + text[-TRANSCRIPT_CHARS:]


def build_message(task: dict, similar: list[dict], transcript: str) -> str:
    lines = [
        "## The user's request",
        task.get("user_message", "").strip() or "(empty)",
        "",
        f"## The task took {int(task.get('seconds', 0))} s and {task.get('steps', 0)} tool steps.",
        "",
        "## Existing skills that may cover it",
    ]
    lines += [f"- {s['name']}{' (learned)' if s['learned'] else ''}: {s['description']}" for s in similar] or ["(none)"]
    lines += ["", "## Transcript of the task", transcript or "(not available)"]
    return "\n".join(lines)


def parse_decision(text: str) -> dict | None:
    try:
        data = DirtyJson.parse_string(str(text or "").strip())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def apply_decision(decision: dict | None, task: dict, chat_id: str, similar: list[dict]) -> dict:
    """Turn the model's decision into an installed or waiting skill.

    Returns {"result": "live" | "review" | "skipped", "name", "reason"}.
    """
    if not decision or not decision.get("learn"):
        return {"result": "skipped", "name": "", "reason": str((decision or {}).get("reason") or "not reusable")}
    update = str(decision.get("update") or "").strip()
    learned_similar = {s["name"] for s in similar if s.get("learned")}
    raw_name = update if update in learned_similar else str(decision.get("name") or "")
    try:
        name = learned.validate_name(raw_name)
    except ValueError as exc:
        return {"result": "skipped", "name": raw_name, "reason": str(exc)}
    if (learned.skills_dir() / name / "SKILL.md").is_file() and name not in learned.learned_names():
        # the user's own skill of that name is never overwritten
        return {"result": "skipped", "name": name, "reason": "a skill with that name already exists"}
    description = " ".join(str(decision.get("description") or "").split())
    body = str(decision.get("procedure") or "").strip()
    if len(description) < 20:
        return {"result": "skipped", "name": name, "reason": "no usable description"}
    problems = learned.check_draft(description, body)
    if problems:
        return {"result": "skipped", "name": name, "reason": "; ".join(problems)}
    if learned.has_review_waiting(name):
        return {"result": "skipped", "name": name, "reason": "a version of it already waits for review"}
    triggers = decision.get("triggers") if isinstance(decision.get("triggers"), list) else None
    version = learned.current_version(name) + 1
    content = learned.render(name, description, body, version, chat_id, triggers, learned_by="auto")
    return place(name, content, task)


def place(name: str, content: str, task: dict) -> dict:
    """Live at once for a task on the user's own PC; else wait for review."""
    sources = list(task.get("sources") or [])
    if sources:
        learned.write_draft(name, content, review={"sources": sources, "request": task.get("user_message", "")[:500]})
        result = "review"
    else:
        learned.write_draft(name, content)
        learned.install(name)
        result = "live"
    learned.record_learned(name, task.get("seconds", 0), task.get("steps", 0))
    return {"result": result, "name": name, "reason": ", ".join(sources)}


@perf.tagged("skill_learn_auto", background=True)
async def learn_from_task(agent, task: dict) -> dict:
    """The background job: ask the utility model, then place the skill."""
    similar = _similar_skills(agent, task.get("user_message", ""))
    message = build_message(task, similar, _transcript(agent))
    system = agent.read_prompt("skill_learn.auto.sys.md")
    try:
        reply = await model_concurrency.run_when_idle(
            lambda: agent.call_utility_model(system=system, message=message, background=True)
        )
    except model_concurrency.Preempted:
        return {"result": "skipped", "name": "", "reason": "the chat stayed busy"}
    outcome = apply_decision(parse_decision(reply), task, str(getattr(agent.context, "id", "") or ""), similar)
    _announce(agent, outcome)
    return outcome


def _announce(agent, outcome: dict) -> None:
    if outcome["result"] == "skipped":
        return
    from helpers.notification import NotificationManager, NotificationPriority, NotificationType

    if outcome["result"] == "live":
        message = f"Learned a new skill: {outcome['name']}. It is used from the next matching task on."
        kind = NotificationType.SUCCESS
    else:
        message = (f"Learned a new skill, {outcome['name']}, from a task that read {outcome['reason']}. "
                   "It waits for you under Learned skills > Needs a look.")
        kind = NotificationType.INFO
    try:
        NotificationManager.send_notification(
            type=kind, priority=NotificationPriority.NORMAL, title="Learned skills", message=message,
            display_time=8, group="learned_skills",
        )
    except Exception:
        pass
    try:
        agent.context.log.log(type="util", heading=message)
    except Exception:
        pass
