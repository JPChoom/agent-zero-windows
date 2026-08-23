"""Shared plumbing behind plugins/_plugin_scan and plugins/_plugin_validator.

Both plugins build a checklist-driven prompt from a {checks.json,
prompt.md} pair in their own webui/ directory, then run that prompt once
in a disposable agent context and return the model's report. This module
holds the parts of that pattern that were identical between the two
(the temp-context run+cleanup, the queue/start API bodies, and the
checklist-substitution rendering) - each plugin's own helpers/prompt.py
still owns its plugin-specific substitution fields and asset paths.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent import AgentContext, UserMessage
from helpers import guids, message_queue as mq
from helpers.api import Output, Response
from helpers.persist_chat import remove_chat


async def run_scoped_review(handler, prompt: str) -> str:
    """Run `prompt` in a fresh disposable agent context and return the
    model's final text response, always cleaning up the context/chat
    afterward regardless of outcome. `handler` is the calling ApiHandler
    instance (its use_context() creates the context)."""
    ctxid = guids.generate_id()
    try:
        context = handler.use_context(ctxid)
        mq.log_user_message(context, prompt, [])
        task = context.communicate(UserMessage(prompt, []))
        report: str = await task.result()
        return report or ""
    finally:
        try:
            AgentContext.remove(ctxid)
            remove_chat(ctxid)
        except Exception:
            pass


def queue_prompt_message(ctxid: str, text: str, *, queued_message: str | None = None) -> Output:
    """Shared body for the *_queue API handlers: log the prompt into the
    chat so it's visible before the agent actually starts. queued_message,
    if given, is set as the context's progress text (used by the
    validator's "waiting for another validation to finish" state; the
    scanner runs scans in parallel and never sets this)."""
    if not ctxid or not text:
        return Response("Missing 'context' or 'text'.", 400)
    context = AgentContext.get(ctxid)
    if context is None:
        return Response(f"Context {ctxid} not found.", 404)

    mq.log_user_message(context, text, [])
    if queued_message:
        context.log.set_progress(queued_message, 0, True)

    return {"ok": True, "context": ctxid}


def start_queued_agent(ctxid: str, text: str) -> Output:
    """Shared body for the *_start API handlers: start the agent on a
    context whose prompt was already logged by the paired *_queue
    handler."""
    if not ctxid or not text:
        return Response("Missing 'context' or 'text'.", 400)
    context = AgentContext.get(ctxid)
    if context is None:
        return Response(f"Context {ctxid} not found.", 404)

    context.communicate(UserMessage(text, []))

    return {"ok": True, "context": ctxid}


class ChecklistPromptBuilder:
    """Loads a {checks.json, prompt.md} pair (cached after first load) and
    fills in the fields both _plugin_scan and _plugin_validator share:
    SELECTED_CHECKS, CHECK_DETAILS, STATUS_LEGEND, RATING_ICONS,
    RATING_PASS/WARNING/FAIL. Callers add their own plugin-specific
    substitution keys on top before calling render()."""

    def __init__(self, checks_path: Path, template_path: Path, no_checks_selected_label: str):
        self._checks_path = checks_path
        self._template_path = template_path
        self._no_checks_selected_label = no_checks_selected_label
        self._cfg: dict | None = None
        self._tmpl: str | None = None

    def config(self) -> dict:
        if self._cfg is None:
            try:
                self._cfg = json.loads(self._checks_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise RuntimeError(f"Unable to load checks from {self._checks_path}: {e}") from e
        return self._cfg

    def template(self) -> str:
        if self._tmpl is None:
            try:
                self._tmpl = self._template_path.read_text(encoding="utf-8")
            except Exception as e:
                raise RuntimeError(f"Unable to load prompt template from {self._template_path}: {e}") from e
        return self._tmpl

    def shared_substitutions(self, checks: list | None) -> dict[str, str]:
        cfg = self.config()
        ratings, all_checks = cfg["ratings"], cfg["checks"]
        keys = list(all_checks.keys()) if checks is None else [k for k in checks if k in all_checks]

        return {
            "SELECTED_CHECKS": (
                "\n".join(f"- **{all_checks[k]['label']}**" for k in keys)
                if keys
                else f"- ({self._no_checks_selected_label})"
            ),
            "CHECK_DETAILS": (
                "\n\n".join(
                    f"#### {c['label']}\n{c['detail']}\n\nCriteria:\n"
                    + "\n".join(f"  - {ratings[level]['icon']} {desc}" for level, desc in c["criteria"].items())
                    for c in (all_checks[k] for k in keys)
                )
                if keys
                else f"({self._no_checks_selected_label})"
            ),
            "STATUS_LEGEND": "\n".join(f"- {r['icon']} **{r['label']}**" for r in ratings.values()),
            "RATING_ICONS": "/".join(r["icon"] for r in ratings.values()),
            "RATING_PASS": ratings["pass"]["icon"],
            "RATING_WARNING": ratings["warning"]["icon"],
            "RATING_FAIL": ratings["fail"]["icon"],
        }

    def render(self, subs: dict[str, str]) -> str:
        prompt = self.template()
        for key, val in subs.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", val)
        return prompt
