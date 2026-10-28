"""Thinking budget for the Main model (Settings > Agent > Models > Thinking).

Reasoning models think before every answer, and on a local GPU that hidden
thinking is often most of a step's time. Many steps do not need it: after a
tool result the next call is usually obvious (read the file it just listed,
run the command it just wrote). Modes:

- `on` (default): the model decides, as before.
- `off`: never think (fastest; weaker on hard problems).
- `auto` (EXPERIMENTAL): think on the first step of a turn, where the plan is
  made, and after a step that failed, errored or was refused; skip it on the
  routine steps in between.

Turning thinking off is provider-specific and only done where it is known to
work: llama.cpp (the chat template's `enable_thinking`) and LM Studio
(`reasoning_effort: none` on the chat-completions route). Other providers
are left alone.
"""

from __future__ import annotations

import re

MODES = ("on", "off", "auto")
LAST_DECISION_KEY = "_thinking_last"

# A tool result or warning that means the next step needs a fresh look.
_TROUBLE = re.compile(
    r"\b(error|exception|traceback|failed|failure|denied|refused|not found|cannot|could not|"
    r"misformat\w*|timed out|timeout|invalid|unexpected)\b",
    re.IGNORECASE,
)


def mode(cfg: dict) -> str:
    value = str((cfg or {}).get("thinking") or "on").strip().lower()
    return value if value in MODES else "on"


def should_think(mode_: str, iteration: int, last_message_text: str) -> bool:
    if mode_ == "on":
        return True
    if mode_ == "off":
        return False
    if iteration <= 0:
        return True  # the first step of a turn: understand the request, plan
    return bool(_TROUBLE.search(last_message_text or ""))


def no_thinking_kwargs(provider: str) -> dict:
    """Call kwargs that turn thinking off for this provider ({} = not supported)."""
    if provider == "llama_cpp":
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    if provider == "lm_studio":
        return {"a0_api_mode": "chat_completions", "extra_body": {"reasoning_effort": "none"}}
    return {}


def apply(model, provider: str) -> bool:
    """Merge no_thinking_kwargs into a model's call kwargs. True if applied."""
    extra = no_thinking_kwargs(provider)
    kwargs = getattr(model, "kwargs", None)
    if not extra or not isinstance(kwargs, dict):
        return False
    body = dict(kwargs.get("extra_body") or {}) if isinstance(kwargs.get("extra_body"), dict) else {}
    for key, value in extra.get("extra_body", {}).items():
        if isinstance(value, dict):
            body[key] = {**dict(body.get(key) or {}), **value}
        else:
            body[key] = value
    kwargs.update({k: v for k, v in extra.items() if k != "extra_body"})
    kwargs["extra_body"] = body
    return True


def last_message_text(agent) -> str:
    """Text of the newest message in the agent's current topic."""
    try:
        messages = agent.history.current.messages
        if not messages:
            return ""
        return str(messages[-1].output_text())[-4000:]
    except Exception:
        return ""
