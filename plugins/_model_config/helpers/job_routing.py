"""Which model runs which job, and what happens when the Utility model is away.

The Utility model can live on another PC, which can be off or asleep. Without
this, every memory save, chat name and compression then fails. Three settings
(`job_routing` in the model config, Settings > Agent > Models > Background jobs):

- `fallback_to_main`: a Utility call goes to the Main model when the Utility
  server does not answer. A short TCP check comes first, so a sleeping PC costs
  1.5 s once rather than a connection timeout on every call.
- `jobs`: job name -> "main" sends that job to the Main model. Anything else
  uses Utility. The job comes from perf.CALLER, set by perf.tagged on each job.
- `subordinate_profiles`: agent profiles whose subordinates run on the Utility
  model (model_config.subordinate_on_utility).

The safety check is not a job here: it has its own Model setting, and it never
follows a subordinate onto the Utility model.
"""

from __future__ import annotations

import asyncio
import time
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
    return any(word in name for word in ("Connection", "Timeout", "ServiceUnavailable", "InternalServer"))


def mark_down(api_base) -> None:
    if api_base:
        _checked[str(api_base)] = (False, time.monotonic() + DOWN_FOR_SECONDS)


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
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(*address), CHECK_TIMEOUT_SECONDS)
        writer.close()
        up = True
    except (OSError, asyncio.TimeoutError):
        up = False
    if known and known[0] and not up:
        PrintStyle(font_color="orange").print(f"Utility model at {key} does not answer: using the Main model")
    _checked[key] = (up, time.monotonic() + (UP_FOR_SECONDS if up else DOWN_FOR_SECONDS))
    return up


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

    def __init__(self, primary, make_fallback, api_base):
        self._primary = primary
        self._make_fallback = make_fallback
        self._api_base = api_base

    def __getattr__(self, name):
        return getattr(self._primary, name)

    async def unified_call(self, *args, **kwargs):
        return await self._run("unified_call", args, kwargs)

    async def unified_turn(self, *args, **kwargs):
        return await self._run("unified_turn", args, kwargs)

    async def _run(self, method: str, args: tuple, kwargs: dict):
        if not await available(self._api_base):
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
            if _is_outage(exc):
                mark_down(self._api_base)
            PrintStyle(font_color="orange").print(
                f"Utility model failed ({type(exc).__name__}): using the Main model"
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
    if jobs.get(job) == "main":
        return model_config.build_main_for_utility(agent)
    model = model_config.build_utility_model(agent)
    if not routing.get("fallback_to_main", True) or not utility_is_separate(agent):
        return model
    api_base = model_config.get_utility_model_config(agent).get("api_base")
    return RoutedUtilityModel(model, lambda: model_config.build_main_for_utility(agent), api_base)
