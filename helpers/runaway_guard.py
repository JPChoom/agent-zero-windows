"""Stop a model reply that has fallen into repeating itself.

Local models can get stuck writing the same line with one small change, such
as endless rows of a made-up lookup table. Seen 2026-11-06: 15,900 tokens over
37 minutes until the user stopped it. A loop like that never ends in a tool
call, so nothing else catches it: Agent's repeat detector only sees finished
replies, and a stream that keeps moving never trips the idle timeout.

Digits and hex are ignored when comparing, because the rows differ in exactly
those. The check is cheap and only runs every CHECK_EVERY_CHARS once a reply
is long. A stopped reply reaches the model as a note, so it can do the job
another way.
"""

from __future__ import annotations

import re

MIN_CHARS = 20000
CHECK_EVERY_CHARS = 2000
WINDOW_CHARS = 8000
PATTERN_CHARS = 80
MIN_REPEATS = 40

NOTE = (
    "Automatic stop: your reply kept repeating the same pattern, so it was cut off and nothing from it was run. "
    "Do not write long tables or lists out by hand. Use a short approach instead, such as generating the data in "
    "code, using an installed library, or keeping only the entries you are sure of."
)

_NUMBERS = re.compile(r"[0-9A-Fa-f]+")
_CHECKED_KEY = "_runaway_guard_checked"


def is_repeating(text: str) -> bool:
    if len(text) < MIN_CHARS:
        return False
    window = _NUMBERS.sub("#", text[-WINDOW_CHARS:])
    pattern = window[-PATTERN_CHARS:]
    return len(pattern) >= PATTERN_CHARS / 2 and window.count(pattern) >= MIN_REPEATS


def check(agent, stream_data: dict) -> None:
    """Called per chunk: asks the agent to stop when the reply is repeating."""
    text = (stream_data or {}).get("full") or ""
    loop_data = getattr(agent, "loop_data", None)
    if loop_data is None or len(text) < MIN_CHARS or agent.intervention:
        return
    checked = loop_data.params_temporary.get(_CHECKED_KEY, 0)
    if checked <= len(text) < checked + CHECK_EVERY_CHARS:
        return
    loop_data.params_temporary[_CHECKED_KEY] = len(text)
    if is_repeating(text):
        from agent import UserMessage

        agent.intervention = UserMessage(message=NOTE)
