"""How much of the model's context window a prompt may really use.

Three things the configured `ctx_length` alone does not know:

1. The window the server actually loaded. LM Studio can unload a model and
   load it again on the next request with a different (often smaller)
   context length; then a prompt that fitted yesterday overflows. For local
   servers that report it (LM Studio, llama.cpp) the smaller of the
   configured and the reported window is used. Cached briefly; any failure
   falls back to the configured value.
2. That a provider has just refused a prompt as too long. After that the
   chat works with a smaller window (`shrink_after_overflow`), because the
   token estimate evidently runs low for this model and content.
3. That the extras (recalled memories and solutions, matched skills, file
   listings) are not history and are never compressed. `shrink_extras`
   trims them, cheapest-to-lose first, when the fixed part of the prompt
   leaves too little room.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from urllib.parse import urlparse

from helpers import tokens

DETECT_CACHE_SECONDS = 30.0
DETECT_TIMEOUT = 1.0
OVERFLOW_FACTOR_KEY = "_ctx_overflow_factor"
OVERFLOW_STEP = 0.85
OVERFLOW_MIN_FACTOR = 0.5

# Extras that can be trimmed, in the order they are given up. Memories and
# solutions are shortened before they are dropped; skills and file listings
# are dropped whole. Time, agent info, goal and parallel jobs are never
# touched (small, and needed to act correctly).
SHORTEN_FIRST = ("solutions", "memories")
DROP_ORDER = ("solutions", "relevant_skills", "remote_file_structure", "project_file_structure",
              "memories", "editor_open_files", "desktop_state")

_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, int | None]] = {}

_DEFAULT_BASES = {"lm_studio": "http://127.0.0.1:1234", "llama_cpp": "http://127.0.0.1:8090"}


def _server_root(cfg: dict) -> str:
    provider = str(cfg.get("provider") or "").lower()
    base = str(cfg.get("api_base") or "").strip()
    if not base:
        try:
            from helpers.providers import get_provider_config

            pcfg = get_provider_config("chat", provider) or {}
            base = str((pcfg.get("kwargs") or {}).get("api_base") or "")
        except Exception:
            base = ""
    base = base or _DEFAULT_BASES.get(provider, "")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        return ""
    host = parsed.hostname or ""
    if host == "host.docker.internal":  # a Docker-era default; natively the server is on this PC
        host = "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=DETECT_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _query_window(provider: str, root: str, model: str) -> int | None:
    if provider == "lm_studio":
        data = _get_json(f"{root}/api/v0/models")
        for item in data.get("data", []):
            if item.get("id") == model and item.get("state") == "loaded":
                value = item.get("loaded_context_length")
                return int(value) if value else None
        return None
    if provider == "llama_cpp":
        data = _get_json(f"{root}/props")
        value = (data.get("default_generation_settings") or {}).get("n_ctx") or data.get("n_ctx")
        return int(value) if value else None
    return None


def detect_server_window(cfg: dict) -> int | None:
    """The context window a local server reports for this model, or None."""
    provider = str(cfg.get("provider") or "").lower()
    if provider not in _DEFAULT_BASES:
        return None
    root = _server_root(cfg)
    model = str(cfg.get("name") or "")
    if not root or not model:
        return None
    key = (provider, root, model)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < DETECT_CACHE_SECONDS:
            return hit[1]
    try:
        value = _query_window(provider, root, model)
    except Exception:
        value = None
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def overflow_factor(agent) -> float:
    try:
        value = float(agent.get_data(OVERFLOW_FACTOR_KEY) or 1.0) if agent is not None else 1.0
    except (TypeError, ValueError, AttributeError):
        value = 1.0
    return min(1.0, max(OVERFLOW_MIN_FACTOR, value))


def shrink_after_overflow(agent) -> float:
    """The provider refused a prompt as too long: work with a smaller window from now on."""
    factor = max(OVERFLOW_MIN_FACTOR, overflow_factor(agent) * OVERFLOW_STEP)
    agent.set_data(OVERFLOW_FACTOR_KEY, factor)
    return factor


def effective_ctx_length(cfg: dict, agent=None) -> int:
    configured = int(cfg.get("ctx_length", 128000) or 128000)
    detected = detect_server_window(cfg)
    window = min(configured, detected) if detected else configured
    return max(1024, int(window * overflow_factor(agent)))


def is_context_overflow(exc: BaseException | str) -> bool:
    """Whether a provider error means the prompt (plus reply) did not fit."""
    text = str(exc).lower()
    return any(marker in text for marker in (
        "context size has been exceeded",
        "exceeds the available context",
        "context_length_exceeded",
        "maximum context length",
        "prompt is too long",
        "input is too long",
    ))
    # Not "too many tokens": rate-limited cloud APIs say that per minute.


def shrink_extras(extras: dict, excess: int) -> tuple[dict, list[str]]:
    """A copy of `extras` that is about `excess` tokens smaller, and what changed.

    Never modifies the input: the persistent extras (recalled memories) stay
    as they are for the next turn, which may have more room.
    """
    result = dict(extras)
    changed: list[str] = []
    if excess <= 0:
        return result, changed

    def size(value) -> int:
        return tokens.approximate_prompt_tokens(str(value))

    for key in SHORTEN_FIRST:
        if excess <= 0:
            break
        if key in result and result[key]:
            before = size(result[key])
            half = max(150, before // 2)
            if before > half:
                result[key] = tokens.trim_to_tokens(str(result[key]), half, "start", "\n[...shortened to fit the context window]")
                excess -= before - size(result[key])
                changed.append(f"shortened {key}")
    for key in DROP_ORDER:
        if excess <= 0:
            break
        if key in result and result[key]:
            excess -= size(result[key])
            del result[key]
            changed.append(f"left out {key}")
    return result, changed
