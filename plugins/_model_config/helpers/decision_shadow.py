"""Decision model in shadow mode (off by default): log, change nothing.

A decision model such as Laya answers a bounded question in one pass instead of
writing text. Two questions could save real time, but its accuracy on this kind
of work is unknown (Laya's own card calls zero-shot use weak), so first it only
predicts next to what really happens:

- `thinking`: does the Main model's next step need thinking, or is it routine?
  Logged with how much the step really thought and whether the next step hit
  trouble, which is what a wrong "routine" would cost.
- `subordinate`: is this delegated task simple or hard? Logged with how long
  it really took.

Nothing reads a prediction back into a decision, and the request runs beside
the step, never in front of it. The log holds predictions, timings and a hash
of the input, never the text. `tests/manual/decision_shadow_report.py`
compares them.

Calls `POST <api_base>/systemone`, the route Jev, laya-serve, llama.cpp and
LM Studio share.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import urllib.request

from helpers import files
from plugins._model_config.helpers import job_routing, model_config, thinking

LOG_FILE = "usr/perf/decision_shadow.jsonl"
MAX_LOG_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 5.0
MAX_REQUEST_CHARS = 1000
MAX_RESULT_CHARS = 1500
MAX_PENDING = 100

THINKING_QUESTION = {
    "next_step": {
        "type": "choice",
        "instructions": "What does the AI agent's next step need?",
        "criteria": {
            "routine": "an obvious follow-up: the next action follows directly from the latest result",
            "deep": "real reasoning: making a plan, diagnosing an error, or choosing between approaches",
        },
    }
}
SUBORDINATE_QUESTION = {
    "difficulty": {
        "type": "choice",
        "instructions": "How hard is this delegated task?",
        "criteria": {
            "simple": "searching, reading, summarizing, or a small well-defined job",
            "hard": "writing or changing code, debugging, or a task that needs careful judgment",
        },
    }
}

# (context id, agent number, decision) -> runs waiting for their outcome. Kept
# here, not in agent data: that is saved with the chat, and tasks can't be.
_pending: dict[tuple, list[dict]] = {}
_tasks: set[asyncio.Task] = set()
_log_lock = threading.Lock()


def config(agent) -> dict:
    value = job_routing.settings(agent).get("decision_shadow")
    return value if isinstance(value, dict) else {}


def enabled(agent) -> bool:
    return bool(config(agent).get("enabled"))


def _keep(task: asyncio.Task) -> asyncio.Task:
    _tasks.add(task)  # a task nothing refers to can be collected mid-run
    task.add_done_callback(_tasks.discard)
    return task


def _post(url: str, body: bytes) -> dict:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


async def ask(agent, state: str, questions: dict) -> dict:
    """{choice, probabilities, confidence, ms} for the only question, or
    {error, ms}. Never raises."""
    started = time.monotonic()
    try:
        cfg = config(agent)
        api_base = cfg.get("api_base") or model_config.get_utility_model_config(agent).get("api_base")
        body = json.dumps({"model": cfg.get("model") or "laya", "state": state, "questions": questions}).encode()
        reply = await asyncio.to_thread(_post, f"{str(api_base).rstrip('/')}/systemone", body)
        answer = next(iter(reply["answers"].values()))
        result = {key: answer.get(key) for key in ("choice", "probabilities", "confidence")}
    except Exception as exc:
        result = {"error": type(exc).__name__}
    result["ms"] = round((time.monotonic() - started) * 1000)
    return result


def _user_request(agent) -> str:
    try:
        message = agent.loop_data.user_message
        return str(message.output_text())[:MAX_REQUEST_CHARS]
    except Exception:
        return ""


def step_state(agent) -> str:
    result = thinking.last_message_text(agent)[-MAX_RESULT_CHARS:]
    return f"User request:\n{_user_request(agent)}\n\nLatest result:\n{result}"


def _key(agent, decision: str) -> tuple:
    return (getattr(getattr(agent, "context", None), "id", ""), getattr(agent, "number", 0), decision)


def _hold(agent, decision: str, entry: dict) -> None:
    if len(_pending) >= MAX_PENDING:
        _pending.clear()  # outcomes that never came; a shadow can lose rows
    _pending.setdefault(_key(agent, decision), []).append(entry)


def _take(agent, decision: str) -> dict | None:
    waiting = _pending.get(_key(agent, decision))
    entry = waiting.pop(0) if waiting else None
    if waiting == []:
        _pending.pop(_key(agent, decision), None)
    return entry


def _common(agent, decision: str, state: str) -> dict:
    return {
        "ts": time.time(),
        "decision": decision,
        "context_id": getattr(getattr(agent, "context", None), "id", ""),
        "agent": getattr(agent, "number", 0),
        "profile": getattr(getattr(agent, "config", None), "profile", ""),
        "input_sha256": hashlib.sha256(state.encode("utf-8", "replace")).hexdigest(),
    }


def start_thinking(agent) -> None:
    state = step_state(agent)
    iteration = int(getattr(getattr(agent, "loop_data", None), "iteration", 0) or 0)
    latest = thinking.last_message_text(agent)
    row = _common(agent, "thinking", state)
    row.update(step=iteration, trouble_before=bool(thinking._TROUBLE.search(latest)),
               rule_thinks=thinking.should_think("auto", iteration, latest),
               thinking_mode=thinking.mode(model_config.get_config(agent)))
    _hold(agent, "thinking", {"row": row, "started": time.monotonic(),
                              "task": _keep(asyncio.create_task(ask(agent, state, THINKING_QUESTION)))})


def finish_thinking(agent, response, reasoning) -> None:
    entry = _take(agent, "thinking")
    if entry:
        entry["row"].update(seconds=round(time.monotonic() - entry["started"], 2),
                            reasoning_chars=len(reasoning or ""), response_chars=len(response or ""))
        _keep(asyncio.create_task(_finish(entry)))


def start_subordinate(agent, tool_args: dict | None) -> None:
    state = f"Delegated task:\n{str((tool_args or {}).get('message') or '')[:MAX_REQUEST_CHARS + MAX_RESULT_CHARS]}"
    row = _common(agent, "subordinate", state)
    row["subordinate_profile"] = str((tool_args or {}).get("profile") or "")
    _hold(agent, "subordinate", {"row": row, "started": time.monotonic(),
                                 "task": _keep(asyncio.create_task(ask(agent, state, SUBORDINATE_QUESTION)))})


def finish_subordinate(agent, response) -> None:
    entry = _take(agent, "subordinate")
    if entry:
        message = str(getattr(response, "message", "") or "")
        entry["row"].update(seconds=round(time.monotonic() - entry["started"], 2), response_chars=len(message))
        _keep(asyncio.create_task(_finish(entry)))


async def _finish(entry: dict) -> None:
    try:
        entry["row"].update(await entry["task"])
        await asyncio.to_thread(_write, entry["row"])
    except Exception:
        pass  # a comparison log must never disturb a chat


def _write(row: dict) -> None:
    path = files.get_abs_path(LOG_FILE)
    with _log_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as log:
            log.write(json.dumps(row) + "\n")
