"""Preflight validation of local inference-server settings.

Motivation (all observed live in this fork, each costing real debugging
time before it was traceable):

  * Agent Zero's configured ctx_length silently disagreeing with the
    context the local server actually loaded the model at. Too high and
    the framework feeds the server more tokens than it can hold; too low
    and the model is starved of room to both reason and emit a tool call
    within one turn - the latter produced a chat that generated megabytes
    of output and zero tool calls before anyone noticed the ceiling.
  * A configured model name that isn't on the server at all (renamed,
    removed, or a typo), which surfaces much later as an opaque
    provider-side load failure mid-conversation.

Both are invisible from inside Agent Zero without asking the server what
it actually has. LM Studio's REST API (`/api/v0/models`) reports, per
model, its `state`, `loaded_context_length` and `max_context_length`,
which is exactly the missing information.

Strictly advisory: every failure path here returns "no findings" rather
than raising. An unreachable server, an unsupported provider, a changed
response shape, or a timeout must never block startup or break the
banner pipeline - the worst acceptable outcome is that the user simply
doesn't get the hint.
"""

from __future__ import annotations

import httpx

# Local providers exposing a queryable "what is actually loaded right
# now" endpoint. Other local servers (ollama, llama_cpp, vllm, omlx)
# have no equivalent that reports the *loaded* context length today, so
# they're skipped rather than guessed at - a wrong warning is worse than
# no warning.
RUNTIME_INFO_PROVIDERS = {"lm_studio"}

_TIMEOUT_SECONDS = 4.0


def runtime_info_url(api_base: str) -> str:
    """Build LM Studio's REST models URL from a configured api_base.

    api_base normally points at the OpenAI-compatible surface
    (".../v1"), but the richer REST API that reports context lengths
    lives at the server root, so the /v1 suffix is trimmed.
    """
    base = (api_base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/v0/models"


async def fetch_server_models(provider: str, api_base: str) -> dict[str, dict]:
    """Return {model_id: {state, loaded_context_length, max_context_length}}.

    Returns {} for unsupported providers, unreachable servers, non-200
    responses, or any parsing problem.
    """
    if (provider or "").lower() not in RUNTIME_INFO_PROVIDERS:
        return {}

    url = runtime_info_url(api_base)
    if not url:
        return {}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return {}
        payload = resp.json()
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    out: dict[str, dict] = {}
    for entry in payload.get("data", []) or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        out[str(model_id)] = {
            "state": entry.get("state"),
            "loaded_context_length": entry.get("loaded_context_length"),
            "max_context_length": entry.get("max_context_length"),
        }
    return out


def _coerce_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def check_slot(
    slot_label: str,
    slot_cfg: dict,
    server_models: dict[str, dict],
) -> list[dict]:
    """Compare one configured model slot against what the server reports.

    Returns a list of finding dicts: {level, title, detail}. `level` is
    "warning" for things that will actively misbehave, "info" for
    configuration that merely leaves capability unused.
    """
    findings: list[dict] = []
    if not isinstance(slot_cfg, dict):
        return findings

    name = str(slot_cfg.get("name") or "").strip()
    if not name:
        return findings

    entry = server_models.get(name)
    if entry is None:
        findings.append(
            {
                "level": "warning",
                "title": f"{slot_label} model not found on server",
                "detail": (
                    f"'{name}' is configured but the local server does not list it. "
                    "It may have been renamed, removed, or mistyped - calls will "
                    "fail at request time."
                ),
            }
        )
        return findings

    # Context comparison is only meaningful once the server has actually
    # loaded the model; LM Studio reports null until then (it JIT-loads
    # on first use, which is normal and not worth warning about).
    loaded_ctx = _coerce_int(entry.get("loaded_context_length"))
    max_ctx = _coerce_int(entry.get("max_context_length"))
    configured_ctx = _coerce_int(slot_cfg.get("ctx_length"))
    if loaded_ctx is None or configured_ctx is None:
        return findings

    if configured_ctx > loaded_ctx:
        headroom = f" The model supports up to {max_ctx:,}." if max_ctx else ""
        findings.append(
            {
                "level": "warning",
                "title": f"{slot_label} context exceeds what the server loaded",
                "detail": (
                    f"Agent Zero is set to {configured_ctx:,} tokens but '{name}' is "
                    f"loaded at only {loaded_ctx:,}. Requests may be truncated or "
                    f"rejected. Lower the setting, or reload the model at a larger "
                    f"context.{headroom}"
                ),
            }
        )
    elif configured_ctx < loaded_ctx:
        findings.append(
            {
                "level": "info",
                "title": f"{slot_label} context below the loaded capacity",
                "detail": (
                    f"Agent Zero is set to {configured_ctx:,} tokens but '{name}' is "
                    f"loaded at {loaded_ctx:,}. Raising the setting gives the model "
                    "more room to reason and still emit a tool call in one turn."
                ),
            }
        )

    return findings


async def run_preflight(config: dict) -> list[dict]:
    """Check every configured model slot against its provider's server.

    Servers are queried once per (provider, api_base) pair so three slots
    on one local server cost one request, not three.
    """
    slots = [
        ("Chat", config.get("chat_model")),
        ("Utility", config.get("utility_model")),
        ("Embedding", config.get("embedding_model")),
    ]

    cache: dict[tuple[str, str], dict[str, dict]] = {}
    findings: list[dict] = []

    for label, slot_cfg in slots:
        if not isinstance(slot_cfg, dict):
            continue
        provider = str(slot_cfg.get("provider") or "").lower()
        if provider not in RUNTIME_INFO_PROVIDERS:
            continue
        api_base = str(slot_cfg.get("api_base") or "").strip()
        if not api_base:
            api_base = _default_api_base(provider, label)
        if not api_base:
            continue

        key = (provider, api_base)
        if key not in cache:
            cache[key] = await fetch_server_models(provider, api_base)
        server_models = cache[key]
        if not server_models:
            continue  # server unreachable or reported nothing - stay quiet

        findings.extend(check_slot(label, slot_cfg, server_models))

    return findings


def _default_api_base(provider: str, slot_label: str) -> str:
    """Fall back to the provider's own default api_base when a slot
    leaves it blank (the normal case - see conf/model_providers.yaml)."""
    try:
        # helpers.providers.ModelType is a Literal["chat", "embedding"]
        # string alias, not an enum - pass the literal value.
        from helpers.providers import get_provider_config

        model_type = "embedding" if slot_label == "Embedding" else "chat"
        provider_cfg = get_provider_config(model_type, provider) or {}
        kwargs = provider_cfg.get("kwargs", {}) or {}
        return str(kwargs.get("api_base") or "").strip()
    except Exception:
        return ""
