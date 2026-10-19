"""What the safety floor refused in this chat.

A refused command is not the end of an attempt: an agent that wants the
result tries again another way (split strings, another language, another
tool, editing this plugin's settings). The infection check is given this
list so it can judge later calls against it, and it checks every call in a
chat that has one, whether or not untrusted content has been seen.
"""

import time

DATA_KEY = "_plugin._safety_policy.denials"
MAX_DENIALS = 20
MAX_COMMAND_CHARS = 300


def _context(agent):
    return getattr(agent, "context", None)


def record(agent, category: str, matched_text: str, command: str) -> None:
    context = _context(agent)
    if context is None:
        return
    try:
        denials = list(context.get_data(DATA_KEY) or [])
        denials.append({
            "ts": time.time(),
            "category": str(category or ""),
            "matched": str(matched_text or "")[:100],
            "command": str(command or "")[:MAX_COMMAND_CHARS],
        })
        context.set_data(DATA_KEY, denials[-MAX_DENIALS:])
    except Exception:
        pass


def recent(agent) -> list[dict]:
    context = _context(agent)
    if context is None:
        return []
    try:
        denials = context.get_data(DATA_KEY) or []
    except Exception:
        return []
    return list(denials) if isinstance(denials, list) else []


def describe(agent) -> str:
    """The refusals as lines for a reviewer, newest last; "" when none."""
    return "\n".join(
        f"- {item.get('category', '')}: {item.get('command', '')}" for item in recent(agent)
    )
