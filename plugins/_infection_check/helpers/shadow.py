"""Shadow safety check (off by default): the Utility model judges the same
input in the background and only the comparison is recorded.

It never affects a verdict. The action has been decided by the time this
runs, and nothing reads the result back. It exists to collect the evidence the
safety check would need before it could ever move to a smaller model: on
2026-11-06 the Dell's 9B model allowed a hostile encoded command that the Main
model blocks.

The log holds verdicts, timings and a hash of the input, never the text.
`tests/manual/safety_shadow_report.py` summarizes it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time

from helpers import files, model_concurrency, perf
from plugins._model_config.helpers import job_routing, model_config

LOG_FILE = "usr/perf/safety_shadow.jsonl"
MAX_LOG_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 120.0

_running = False
_tasks: set[asyncio.Task] = set()
_log_lock = threading.Lock()


def start(agent, messages: list, verdict: str, parse_result) -> None:
    """One shadow at a time: a slower model skips checks rather than queueing."""
    global _running
    if _running or not job_routing.utility_is_separate(agent):
        return
    _running = True
    task = asyncio.create_task(_run(agent, list(messages), verdict, parse_result))
    _tasks.add(task)  # a task nothing refers to can be collected mid-run
    task.add_done_callback(_tasks.discard)


@perf.tagged("infection_check_shadow", background=True)
async def _run(agent, messages: list, verdict: str, parse_result) -> None:
    global _running
    started = time.monotonic()
    shadow, error = "", ""
    try:
        api_base = model_config.get_utility_model_config(agent).get("api_base")
        if not await job_routing.available(api_base):
            return
        # build_utility_model, not get_utility_model: a fallback to the Main
        # model would compare the Main model with itself.
        model = model_config.build_utility_model(agent)
        response, _ = await asyncio.wait_for(model.unified_call(messages=messages), TIMEOUT_SECONDS)
        shadow = parse_result(response)[0]
    except model_concurrency.Preempted:
        return
    except Exception as exc:
        error = type(exc).__name__
    finally:
        _running = False
    _record(messages, verdict, shadow, error, time.monotonic() - started)


def _record(messages: list, verdict: str, shadow: str, error: str, seconds: float) -> None:
    text = "\n".join(str(getattr(message, "content", "")) for message in messages[1:])
    row = {
        "ts": time.time(),
        "main": verdict,
        "shadow": shadow,
        "error": error,
        "seconds": round(seconds, 2),
        "input_sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
    }
    path = files.get_abs_path(LOG_FILE)
    try:
        with _log_lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as log:
                log.write(json.dumps(row) + "\n")
    except OSError:
        pass  # a comparison log must never disturb a chat
