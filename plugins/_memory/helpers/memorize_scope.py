"""What the end-of-turn memorize extensions send to the utility model.

They used to send the last 80,000 characters of the whole chat after every
reply - re-reading, and re-memorizing, the same old turns again and again
(each saved item then costs a consolidation call too). Now each one sends
only the messages added since it last ran successfully, with a little
context before them, and skips turns too small to hold anything worth
keeping. Measured in the workflow benchmark (local-speed item B1).
"""

from __future__ import annotations

import re

from helpers.history import output_text

DATA_KEY = "_plugin._memory.memorized_sequence.{kind}"
# Messages shown before the new ones, so a follow-up turn still makes sense.
CONTEXT_MESSAGES = 2
MAX_CHARS = 80000
# Below these sizes a turn has nothing durable to extract.
MIN_CHARS = {"fragments": 400, "solutions": 1500}
# A solution needs the agent to have done something (a tool other than the reply).
_TOOL_USE = re.compile(r'"tool_name"\s*:\s*"(?!response")')


def _key(kind: str) -> str:
    return DATA_KEY.format(kind=kind)


def last_sequence(agent, kind: str) -> int:
    try:
        return int(agent.get_data(_key(kind)) or 0)
    except Exception:
        return 0


def new_messages(agent, kind: str) -> tuple[str, int]:
    """(text to memorize, sequence of the newest message in it)."""
    history = agent.history
    since = last_sequence(agent, kind)
    everything = history.all_messages()
    fresh = [m for m in everything if int(m.sequence or 0) > since]
    if not fresh:
        return "", since
    first = everything.index(fresh[0])
    window = everything[max(0, first - CONTEXT_MESSAGES):]
    outputs = [out for message in window for out in message.output()]
    text = output_text(outputs, ai_label="assistant", human_label="user")
    if len(text) > MAX_CHARS:
        text = text[-MAX_CHARS:]
    newest = max(int(m.sequence or 0) for m in fresh)
    return text, newest


def worth_memorizing(kind: str, text: str) -> bool:
    if len(text) < MIN_CHARS.get(kind, 0):
        return False
    if kind == "solutions" and not _TOOL_USE.search(text):
        return False
    return True


def mark_done(agent, kind: str, sequence: int) -> None:
    try:
        agent.set_data(_key(kind), int(sequence))
    except Exception:
        pass
