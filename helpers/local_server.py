"""The local model server (llama.cpp) as part of Settings > Agent > Models.

Settings live in the model config under `local_server` (plugins/_model_config),
next to the model slots that use the server. This module turns them into a
`llama_server.ServerConfig`:

- **preset** picks the speed flags, so nobody has to type llama-server
  options. `coding` adds MTP self-drafting when the model file has an MTP
  layer (measured on an RTX 4090 with a 27B Qwen: 47 -> ~130 tokens/s);
  `balanced` is the same without drafting; `low_memory` stores the KV cache
  at 4 bits; `custom` uses `extra_args` as typed.
- **context size** follows the Main model slot when Main runs on this
  server, so the two can never disagree; otherwise `context_size`.
- **vision** adds the model's own `mmproj-*.gguf` from the same folder.
- **thinking_budget** ends a thinking model's thinking after that many
  tokens (`--reasoning-budget`) with a nudge to answer now. Measured on a
  27B Qwen over 4,500 Main-model calls: replies after up to 6k tokens of
  thinking were almost never empty (about 1%), past 8k they were empty 29%
  of the time and past 16k always - the thinking ran until the context
  window was full and no answer came. 0 = no limit. Not for `custom`.

It also lists GGUF files from the usual places (Agent Zero's own models
folder, LM Studio's, and any folders the user adds), reads a GGUF header to
see whether a model has an MTP layer, and copies the settings of the old
`_llama_server` plugin across once.
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path

from helpers import files

PRESETS = ("coding", "balanced", "low_memory", "custom")
FAST_FLAGS = ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--cache-reuse", "256"]
LOW_MEMORY_FLAGS = ["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "--jinja", "--cache-reuse", "256"]
MTP_FLAGS = ["--spec-type", "draft-mtp", "--spec-draft-n-max", "6"]
THINKING_BUDGET_MESSAGE = "\n\nI have thought about this enough. Now I reply with one JSON tool call.\n"
DEFAULT_PORT = 8090

DEFAULTS: dict = {
    "autostart": False,
    "model_path": "",
    "preset": "coding",
    "extra_args": "",
    "vision": False,
    "mmproj_path": "",
    "port": DEFAULT_PORT,
    "context_size": 32768,
    "gpu_layers": 99,
    "threads": 0,
    "parallel": 1,
    "model_folders": [],
    "binary_path": "",
    "download_variant": "",
    "vram_check": True,
    "startup_timeout_seconds": 300,
    "thinking_budget": 6144,
}

# Files that are never a chat model.
_NOT_CHAT = re.compile(r"(^mmproj|embed|(^|[-_])bge[-_]|rerank)", re.IGNORECASE)


# ---------------------------------------------------------------- settings

def model_config() -> dict:
    from helpers import plugins

    return plugins.get_plugin_config("_model_config") or {}


def settings(cfg: dict | None = None) -> dict:
    cfg = model_config() if cfg is None else cfg
    return {**DEFAULTS, **(cfg.get("local_server") or {})}


def api_base(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}/v1"


def _uses_this_server(slot: dict, port: int) -> bool:
    if str(slot.get("provider", "")) != "llama_cpp":
        return False
    base = str(slot.get("api_base") or "").strip()
    if not base:
        return int(port) == DEFAULT_PORT  # the provider default points here
    return f":{int(port)}" in base and ("127.0.0.1" in base or "localhost" in base)


def preset_args(preset: str, model_path: str, extra_args: str = "") -> list[str]:
    from helpers import llama_server

    if preset == "custom":
        return llama_server.parse_extra_args(extra_args)
    if preset == "low_memory":
        return list(LOW_MEMORY_FLAGS)
    args = list(FAST_FLAGS)
    if preset == "coding" and has_mtp(model_path):
        args += MTP_FLAGS
    return args


def thinking_args(preset: str, budget) -> list[str]:
    """Flags that cap thinking (see the module docstring); none for custom."""
    budget = _as_int(budget, 0)
    if preset == "custom" or budget <= 0:
        return []
    return ["--reasoning-budget", str(budget), "--reasoning-budget-message", THINKING_BUDGET_MESSAGE]


def server_config(cfg: dict | None = None):
    """The ServerConfig the current settings describe."""
    from helpers import llama_server

    cfg = model_config() if cfg is None else cfg
    s = settings(cfg)
    port = _as_int(s.get("port"), DEFAULT_PORT)
    context = _as_int(s.get("context_size"), DEFAULTS["context_size"])
    chat = cfg.get("chat_model") or {}
    if _uses_this_server(chat, port):
        context = _as_int(chat.get("ctx_length"), context)
    model = str(s.get("model_path") or "").strip()
    preset = str(s.get("preset") or "coding")
    extra = preset_args(preset, model, str(s.get("extra_args") or ""))
    extra += thinking_args(preset, s.get("thinking_budget"))
    if s.get("vision"):
        override = str(s.get("mmproj_path") or "").strip()
        projector = override if override and os.path.isfile(override) else mmproj_for(model)
        if projector:
            extra += ["--mmproj", projector]
    return llama_server.ServerConfig(
        binary=str(s.get("binary_path") or "").strip() or llama_server.default_binary(),
        model=model,
        port=port,
        context_size=context,
        gpu_layers=_as_int(s.get("gpu_layers"), 99),
        threads=_as_int(s.get("threads"), 0),
        parallel=max(1, _as_int(s.get("parallel"), 1)),
        extra_args=extra,
        vram_check=bool(s.get("vram_check", True)),
        startup_timeout=float(_as_int(s.get("startup_timeout_seconds"), 300)),
    )


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- models

def own_models_dir() -> str:
    return files.get_abs_path("usr", "llama-cpp", "models")


def lm_studio_models_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".lmstudio", "models")


def model_folders(s: dict | None = None) -> list[tuple[str, str]]:
    """(label, folder) pairs that exist, in display order."""
    s = settings() if s is None else s
    folders = [("Agent Zero", own_models_dir()), ("LM Studio", lm_studio_models_dir())]
    for extra in s.get("model_folders") or []:
        extra = str(extra or "").strip()
        if extra:
            folders.append((extra, extra))
    seen, out = set(), []
    for label, folder in folders:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen and os.path.isdir(folder):
            seen.add(key)
            out.append((label, folder))
    return out


def list_models(s: dict | None = None) -> list[dict]:
    items = []
    for label, folder in model_folders(s):
        for root, _, names in os.walk(folder):
            for name in names:
                if not name.lower().endswith(".gguf") or _NOT_CHAT.search(name):
                    continue
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                items.append({
                    "name": os.path.relpath(path, folder),
                    "folder": label,
                    "path": path,
                    "alias": Path(path).stem,
                    "size_mb": round(size / (1024 * 1024)),
                    "has_mmproj": bool(mmproj_for(path)),
                })
    return sorted(items, key=lambda m: (m["folder"] != "Agent Zero", m["folder"] != "LM Studio", m["name"].lower()))


_QUANT_TOKEN = re.compile(r"^(q\d.*|iq\d.*|f16|f32|bf16|fp16|mxfp4|gguf|mmproj|nomtp)$", re.IGNORECASE)


def _name_tokens(stem: str) -> set[str]:
    return {t.lower() for t in re.split(r"[^A-Za-z0-9.]+", stem) if t and not _QUANT_TOKEN.match(t)}


def mmproj_for(model_path: str) -> str:
    """The vision projector that belongs to a model, or "".

    Looks for mmproj-*.gguf next to the model. One file is taken as is; with
    several, the one whose name shares the most words with the model's name
    (quantization words left out) wins, and when none shares any the answer
    is "" rather than a guess - a projector from another model loads without
    complaint and then produces nonsense. The user can always name one
    (local_server.mmproj_path).
    """
    folder = os.path.dirname(model_path or "")
    if not folder or not os.path.isdir(folder):
        return ""
    candidates = sorted(n for n in os.listdir(folder) if n.lower().startswith("mmproj") and n.lower().endswith(".gguf"))
    if not candidates:
        return ""
    if len(candidates) == 1:
        return os.path.join(folder, candidates[0])
    wanted = _name_tokens(Path(model_path).stem)
    scored = sorted(((len(wanted & _name_tokens(Path(n).stem)), n) for n in candidates), key=lambda x: (-x[0], x[1]))
    return os.path.join(folder, scored[0][1]) if scored[0][0] > 0 else ""


# ---------------------------------------------------------------- GGUF header

_GGUF_SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_mtp_cache: dict[tuple[str, float], bool] = {}


def has_mtp(model_path: str) -> bool:
    """Does the GGUF file carry an MTP (next-token prediction) layer?

    Reads only the metadata header: a `<arch>.nextn_predict_layers` value
    above zero. Unreadable or missing files count as no.
    """
    try:
        key = (os.path.abspath(model_path), os.path.getmtime(model_path))
    except OSError:
        return False
    if key not in _mtp_cache:
        try:
            _mtp_cache[key] = _read_nextn_layers(model_path) > 0
        except Exception:
            _mtp_cache[key] = False
    return _mtp_cache[key]


def _read_nextn_layers(path: str) -> int:
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return 0
        version = struct.unpack("<I", f.read(4))[0]
        if version < 2:
            return 0
        _tensors, kv_count = struct.unpack("<QQ", f.read(16))

        def read_str() -> str:
            (n,) = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", "replace")

        def read_value(kind: int):
            if kind == 8:
                return read_str()
            if kind == 9:
                item_kind, count = struct.unpack("<IQ", f.read(12))
                if item_kind == 8:
                    for _ in range(count):
                        (n,) = struct.unpack("<Q", f.read(8))
                        f.seek(n, 1)
                    return None
                f.seek(struct.calcsize("<" + _GGUF_SCALARS[item_kind]) * count, 1)
                return None
            fmt = "<" + _GGUF_SCALARS[kind]
            return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]

        for _ in range(kv_count):
            name = read_str()
            (kind,) = struct.unpack("<I", f.read(4))
            value = read_value(kind)
            if name.endswith(".nextn_predict_layers"):
                return int(value or 0)
    return 0


# ---------------------------------------------------------------- migration

def old_plugin_config_path() -> str:
    return files.get_abs_path("usr", "plugins", "_llama_server", "config.json")


def migrated_settings() -> dict:
    """Settings for `local_server`: the old plugin's, if it was set up, else defaults."""
    from helpers import llama_server

    path = old_plugin_config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            old = json.load(handle)
    except (OSError, ValueError):
        return dict(DEFAULTS)
    s = dict(DEFAULTS)
    for key in ("autostart", "model_path", "port", "context_size", "gpu_layers", "threads", "parallel",
                "binary_path", "download_variant", "vram_check", "startup_timeout_seconds"):
        if key in old:
            s[key] = old[key]
    try:
        args = llama_server.parse_extra_args(old.get("extra_args", ""))
    except Exception:
        args = None
    if not args or args == FAST_FLAGS:
        s["preset"] = "balanced"
    elif args == FAST_FLAGS + MTP_FLAGS:
        s["preset"] = "coding"
    elif args == LOW_MEMORY_FLAGS:
        s["preset"] = "low_memory"
    else:
        s["preset"], s["extra_args"] = "custom", str(old.get("extra_args", ""))
    return s
