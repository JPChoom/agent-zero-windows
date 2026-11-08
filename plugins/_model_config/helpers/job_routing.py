"""Which model runs which job, and what happens when the Utility model is away.

The Utility model can live on another PC, which can be off or asleep. Without
this, every memory save, chat name and compression then fails. Three settings
(`job_routing` in the model config, Settings > Agent > Models > Background jobs):

- `fallback_to_main`: a Utility call goes to the Main model when the Utility
  server does not answer. A short TCP check comes first, so a sleeping PC costs
  1.5 s once rather than a connection timeout on every call.
- `jobs`: job name -> "main" sends that job to the Main model. Anything else
  uses Utility. The job comes from perf.CALLER, set by perf.tagged on each job.
- `profile_models` (and the older `subordinate_profiles`): the model target of
  each agent profile's subordinates and child agents (model_config
  .subordinate_target). Targets are `main`, `utility` or `preset:<name>`.

The safety check is not a job here: it has its own Model setting, and it never
follows a subordinate onto the Utility model.
"""

from __future__ import annotations

import asyncio
import collections
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from helpers import model_concurrency, perf
from helpers.print_style import PrintStyle
from plugins._model_config.helpers import model_config

# Job -> the perf.tagged names that belong to it. The Settings list in
# webui/config.html shows the same jobs.
JOBS: dict[str, tuple[str, ...]] = {
    "rename_chat": ("rename_chat",),
    "memory_recall": ("memory_recall",),
    "memorize": ("memorize_fragments", "memorize_solutions"),
    "memory_consolidation": ("memory_consolidation",),
    "history_compression": ("history_compression",),
    "skill_learn": ("skill_learn_auto",),
}
_JOB_OF_CALLER = {caller: job for job, callers in JOBS.items() for caller in callers}
# Worth doing only away from the Main model: its point is to save Main's time.
UTILITY_ONLY_CALLERS = {"tool_digest"}

CHECK_TIMEOUT_SECONDS = 1.5
UP_FOR_SECONDS = 10.0  # a good check is trusted this long
DOWN_FOR_SECONDS = 30.0  # a failed server is left alone this long
# The Utility call gets this long, so the Main model still has time inside
# Agent.UTILITY_MODEL_TIMEOUT_SECONDS (180 s) when a server stalls.
PRIMARY_TIMEOUT_SECONDS = 120.0

_checked: dict[str, tuple[bool, float]] = {}  # server -> (up, valid until)
_reasons: dict[str, str] = {}  # server -> why it is down
HISTORY: collections.deque = collections.deque(maxlen=50)  # fallbacks, newest last
HEALTH_TIMEOUT_SECONDS = 2.0


def settings(agent=None) -> dict:
    routing = model_config.get_config(agent).get("job_routing")
    return routing if isinstance(routing, dict) else {}


def _address(api_base) -> tuple[str, int] | None:
    parts = urlsplit(str(api_base or ""))
    if not parts.hostname:
        return None
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def _is_outage(exc: Exception) -> bool:
    """The server is away, as opposed to refusing this one request (a prompt
    over its context is a BadRequest, and the next call can be fine)."""
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    name = type(exc).__name__
    return any(word in name for word in ("Connection", "Timeout", "ServiceUnavailable", "InternalServer", "APIError"))


_CONTEXT_WORDS = ("context", "n_ctx", "too long", "maximum length", "max_tokens", "token limit")


def classify(exc: Exception) -> str:
    """outage (the server is away: fall back), context (the prompt does not fit
    that model: fall back to the larger Main model), request (a malformed or
    refused request: re-sending it elsewhere would only hide the problem)."""
    if _is_outage(exc):
        return "outage"
    text = f"{type(exc).__name__} {exc}".lower()
    if any(word in text for word in _CONTEXT_WORDS):
        return "context"
    return "request"


def note_fallback(server, reason: str, target: str = "main") -> None:
    HISTORY.append({"ts": time.time(), "caller": perf.CALLER.get() or "step", "server": str(server or ""),
                    "reason": reason, "to": target})


def server_states() -> list[dict]:
    now = time.monotonic()
    return [{"server": server, "up": up, "checked": True, "reason": "" if up else _reasons.get(server, ""),
             "fresh": until > now} for server, (up, until) in _checked.items()]


def mark_down(api_base, reason: str = "failed") -> None:
    if api_base:
        _checked[str(api_base)] = (False, time.monotonic() + DOWN_FOR_SECONDS)
        _reasons[str(api_base)] = reason


def is_marked_down(api_base) -> bool:
    known = _checked.get(str(api_base or ""))
    return bool(known) and not known[0] and known[1] > time.monotonic()


async def available(api_base) -> bool:
    """Does this server accept a connection? True when there is no address to
    check (a cloud provider's own default)."""
    address = _address(api_base)
    if address is None:
        return True
    key = str(api_base)
    known = _checked.get(key)
    if known and known[1] > time.monotonic():
        return known[0]
    reason = ""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(*address), CHECK_TIMEOUT_SECONDS)
        writer.close()
        up = True
    except (OSError, asyncio.TimeoutError):
        up, reason = False, "no connection"
    if up:
        # An open port is not a ready model: ask the server for its models
        # (llama.cpp and LM Studio both answer /models; 503 while loading).
        up, reason = await asyncio.to_thread(_models_answer, str(api_base))
    if not up:
        _reasons[key] = reason
    if known and known[0] and not up:
        PrintStyle(font_color="orange").print(f"Utility model at {key} does not answer: using the Main model")
    _checked[key] = (up, time.monotonic() + (UP_FOR_SECONDS if up else DOWN_FOR_SECONDS))
    return up


def _models_answer(api_base: str) -> tuple[bool, str]:
    url = api_base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=HEALTH_TIMEOUT_SECONDS):
            return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            return False, f"not ready (HTTP {exc.code})"
        return True, ""  # 401/404: the server answers; it just has no such list or needs a key
    except Exception:
        return False, "no answer"


def _same_server(agent) -> bool:
    chat = model_config.get_chat_model_config(agent, routed=False)
    utility = model_config.get_utility_model_config(agent)
    return all(chat.get(key) == utility.get(key) for key in ("provider", "name", "api_base"))


def utility_is_separate(agent) -> bool:
    """False when Utility is the Main model, so nothing can move between them."""
    return not model_config.is_single_model_mode(agent) and not _same_server(agent)


class RoutedUtilityModel:
    """A Utility model that falls back to the Main model. Everything except
    the two call methods goes straight to the Utility model object."""

    def __init__(self, primary, make_fallback, api_base, target: str = "utility"):
        self._primary = primary
        self._make_fallback = make_fallback
        self._api_base = api_base
        self._target = target

    def __getattr__(self, name):
        return getattr(self._primary, name)

    async def unified_call(self, *args, **kwargs):
        return await self._run("unified_call", args, kwargs)

    async def unified_turn(self, *args, **kwargs):
        return await self._run("unified_turn", args, kwargs)

    async def _run(self, method: str, args: tuple, kwargs: dict):
        if not await available(self._api_base):
            note_fallback(self._api_base, _reasons.get(str(self._api_base), "unavailable"))
            return await getattr(self._make_fallback(), method)(*args, **kwargs)

        streamed = False
        given = kwargs.get("response_callback")
        if given is not None:
            async def noting_callback(*a, **k):
                nonlocal streamed
                streamed = True
                return await given(*a, **k)

            kwargs = {**kwargs, "response_callback": noting_callback}
        try:
            return await asyncio.wait_for(
                getattr(self._primary, method)(*args, **kwargs), PRIMARY_TIMEOUT_SECONDS
            )
        except model_concurrency.Preempted:
            raise  # the turn wanted the model: the job is retried, not moved
        except Exception as exc:
            if streamed:
                raise  # part of an answer is out: a second one would mix with it
            kind = classify(exc)
            if kind == "request":
                raise  # a refused request would be refused or hidden elsewhere too
            if kind == "outage":
                mark_down(self._api_base, type(exc).__name__)
            note_fallback(self._api_base, f"{kind}: {type(exc).__name__}")
            PrintStyle(font_color="orange").print(
                f"{self._target} model failed ({type(exc).__name__}): using the Main model"
            )
            kwargs = {**kwargs, "response_callback": given} if given is not None else kwargs
            return await getattr(self._make_fallback(), method)(*args, **kwargs)


def utility_model_for_call(agent):
    """The model for a Utility call, by the job making it."""
    routing = settings(agent)
    caller = perf.CALLER.get()
    if caller in UTILITY_ONLY_CALLERS:
        return model_config.build_utility_model(agent)
    job = _JOB_OF_CALLER.get(caller, "")
    jobs = routing.get("jobs") if isinstance(routing.get("jobs"), dict) else {}
    target = str(jobs.get(job) or "utility")
    if target == "main":
        return model_config.build_main_for_utility(agent)
    if target.startswith("preset:") and model_config.target_slot(agent, target) is not None:
        model = model_config.build_model_for_target(agent, target, utility=True)
        if not routing.get("fallback_to_main", True):
            return model
        api_base = (model_config.target_slot(agent, target) or {}).get("api_base")
        return RoutedUtilityModel(model, lambda: model_config.build_main_for_utility(agent), api_base, target)
    model = model_config.build_utility_model(agent)
    if not routing.get("fallback_to_main", True) or not utility_is_separate(agent):
        return model
    api_base = model_config.get_utility_model_config(agent).get("api_base")
    return RoutedUtilityModel(model, lambda: model_config.build_main_for_utility(agent), api_base)
