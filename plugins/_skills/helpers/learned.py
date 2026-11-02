"""Agent-learned skills: drafting, checks, install, review, versions, stats.

A learned skill is a normal `usr/skills/<name>/SKILL.md` whose frontmatter
carries `origin: agent-learned`, `learned_by` (auto | asked), a `version` and
the `source_chat`.

Where it goes depends on what the task that taught it read
(`outside_source`): a task that only used the user's own files and commands
installs the skill directly; a task that read the web, email/chat messages,
downloads or network command output could have picked up injected
instructions, so its skill waits for the user ("Needs a look").

    draft    -> usr/skills/.pending/<name>/SKILL.md (+ REVIEW.json: why)
    install  -> usr/skills/<name>/SKILL.md            (active)
               previous version kept as usr/skills/<name>/.versions/SKILL.v<N>.md
    disable  -> usr/skills/.disabled/<name>/
    delete   -> usr/skills/.deleted/<name>-<time>/    (recoverable by hand)

Skill discovery skips hidden folders (helpers/skills.py), which is what
keeps drafts, old versions, disabled and deleted skills inert.
Stats (how long the task that taught a skill took, and every later task
that loaded it) live in usr/skills/.learned-stats.json.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from helpers import files
from helpers.untrusted_content import looks_like_injected_instruction

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
TRUST_LEVELS = ("built-in", "user", "agent-learned", "downloaded")
# How a learned skill came about: the agent on its own after a long task, or
# because the user asked ("learn that skill").
LEARNED_BY = ("auto", "asked")

# Procedure text that should never end up in a skill the agent will follow
# on its own later: data leaving the machine, obfuscated or downloaded code,
# security switches, and secrets.
_DANGEROUS = [
    (re.compile(r"-e(nc(odedcommand)?)?\s+[A-Za-z0-9+/=]{20,}", re.I), "an encoded PowerShell command"),
    (re.compile(r"\b(iex|invoke-expression)\b", re.I), "Invoke-Expression"),
    (re.compile(r"(curl|wget|iwr|invoke-webrequest|irm|invoke-restmethod)[^\n|]*\|\s*(iex|sh|bash|python|pwsh|powershell)", re.I), "piping a download into a shell"),
    (re.compile(r"set-mppreference|disable(realtime|behavior)monitoring|netsh\s+advfirewall\s+set", re.I), "disabling Defender or the firewall"),
    (re.compile(r"\b(api[_-]?key|password|token|secret)\s*[:=]\s*\S{6,}", re.I), "a hard-coded credential"),
    (re.compile(r"permissions_bypass|security_audit|permissions_mode", re.I), "the permission or audit controls"),
]


def skills_dir() -> Path:
    return Path(files.get_abs_path("usr", "skills"))


def pending_dir(name: str = "") -> Path:
    base = skills_dir() / ".pending"
    return base / name if name else base


def validate_name(name: str) -> str:
    name = str(name or "").strip().lower().replace(" ", "-")
    if not NAME_RE.match(name):
        raise ValueError("name must be 3-64 characters of lowercase letters, digits and hyphens, e.g. 'export-monthly-report'.")
    return name


def check_draft(description: str, body: str) -> list[str]:
    """Problems that refuse the draft outright."""
    problems = []
    text = f"{description}\n{body}"
    if looks_like_injected_instruction(text):
        problems.append("it contains instruction-injection phrasing (ignore previous instructions, always send/upload, hide from the user...)")
    for pattern, label in _DANGEROUS:
        if pattern.search(text):
            problems.append(f"it contains {label}")
    if len(body.strip()) < 40:
        problems.append("the procedure is too short to be reusable")
    if len(body) > 20000:
        problems.append("the procedure is longer than 20,000 characters; keep SKILL.md lean")
    return problems


def current_version(name: str) -> int:
    path = skills_dir() / name / "SKILL.md"
    if not path.is_file():
        return 0
    meta = read_frontmatter(path)
    try:
        return int(str(meta.get("version", "1")).split(".")[0])
    except ValueError:
        return 1


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def render(name: str, description: str, body: str, version: int, source_chat: str, triggers=None,
           learned_by: str = "asked") -> str:
    meta = {
        "name": name,
        "description": " ".join(str(description).split()),
        "origin": "agent-learned",
        "learned_by": learned_by if learned_by in LEARNED_BY else "asked",
        "version": version,
        "created": datetime.now().strftime("%Y-%m-%d"),  # the user's own date
        "source_chat": source_chat,
    }
    if triggers:
        meta["triggers"] = [str(t) for t in triggers][:10]
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n\n{body.strip()}\n"


def write_draft(name: str, content: str, review: dict | None = None) -> Path:
    """Write a draft; `review` (why it waits: outside sources) goes next to it."""
    folder = pending_dir(name)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    review_path = folder / "REVIEW.json"
    if review:
        review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    elif review_path.exists():
        review_path.unlink()
    return path


def install(name: str) -> tuple[Path, int]:
    """Move an approved draft into place, keeping the previous version."""
    draft = pending_dir(name) / "SKILL.md"
    if not draft.is_file():
        raise FileNotFoundError(f"no pending draft for {name}")
    target_dir = skills_dir() / name
    target = target_dir / "SKILL.md"
    old = current_version(name)
    if target.is_file():
        versions = target_dir / ".versions"
        versions.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, versions / f"SKILL.v{old or 1}.md")
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(draft), str(target))
    discard(name)
    return target, old


def discard(name: str) -> None:
    folder = pending_dir(name)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def list_learned() -> tuple[list[dict], list[str]]:
    active = []
    base = skills_dir()
    if base.is_dir():
        for path in sorted(base.glob("*/SKILL.md")):
            meta = read_frontmatter(path)
            if meta.get("origin") == "agent-learned":
                active.append({"name": path.parent.name, "version": meta.get("version"),
                               "created": meta.get("created"), "description": meta.get("description", "")})
    pending = sorted(p.parent.name for p in pending_dir().glob("*/SKILL.md")) if pending_dir().is_dir() else []
    return active, pending


# ------------------------------------------------------------ outside sources

# Tools whose results come from outside the user's PC (or from other people):
# a skill learned from a task that used one waits for the user's review.
_OUTSIDE_TOOLS = {
    "search_engine": "web search",
    "browser": "a web page",
    "browser_agent": "a web page",
    "document_query": "a document or web page",
    "a2a_chat": "another agent",
}
# Command lines that fetch from the network (their output is outside text).
_NETWORK_COMMAND = re.compile(
    r"\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|start-bitstransfer|"
    r"git\s+(clone|pull|fetch)|npm\s+(view|info|install|i)\b|pip\s+(download|install)|"
    r"yt-dlp|scp|sftp|ssh)\b|https?://",
    re.IGNORECASE,
)


def outside_source(tool_name: str, args: dict | None, mcp: bool = False) -> str:
    """What outside source a tool call read ("" for the user's own PC only)."""
    name = str(tool_name or "").strip().lower().split(":", 1)[0]
    args = args if isinstance(args, dict) else {}
    if mcp:
        return f"an MCP tool ({name})"
    if name in _OUTSIDE_TOOLS:
        if name == "document_query":
            target = " ".join(str(v) for v in args.values() if isinstance(v, (str, list)))
            if not re.search(r"https?://", target, re.IGNORECASE):
                return ""  # a local document the user pointed at
        return _OUTSIDE_TOOLS[name]
    if name in ("code_execution_tool", "code_execution_remote", "terminal_tool", "terminal_access"):
        code = str(args.get("code") or args.get("command") or "")
        if _NETWORK_COMMAND.search(code):
            return "network command output"
    return ""


# ------------------------------------------------------------------- stats

_STATS_LOCK = threading.Lock()


def stats_path() -> Path:
    return skills_dir() / ".learned-stats.json"


def load_stats() -> dict:
    try:
        data = json.loads(stats_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_stats(data: dict) -> None:
    path = stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def record_learned(name: str, seconds: float, steps: int) -> None:
    """How long the task that taught `name` took (the before-number)."""
    with _STATS_LOCK:
        data = load_stats()
        entry = data.setdefault(name, {})
        entry["learned"] = {"seconds": round(float(seconds), 1), "steps": int(steps), "at": time.time()}
        entry.setdefault("uses", [])
        _save_stats(data)


MAX_USES_KEPT = 50


def record_use(name: str, seconds: float, steps: int) -> None:
    """A later task that loaded `name` (the after-numbers)."""
    with _STATS_LOCK:
        data = load_stats()
        entry = data.setdefault(name, {"uses": []})
        uses = entry.setdefault("uses", [])
        uses.append({"seconds": round(float(seconds), 1), "steps": int(steps), "at": time.time()})
        del uses[:-MAX_USES_KEPT]
        _save_stats(data)


def learned_names() -> set[str]:
    base = skills_dir()
    if not base.is_dir():
        return set()
    return {p.parent.name for p in base.glob("*/SKILL.md") if read_frontmatter(p).get("origin") == "agent-learned"}


# ---------------------------------------------------------------- managing

def disabled_dir(name: str = "") -> Path:
    base = skills_dir() / ".disabled"
    return base / name if name else base


def deleted_dir() -> Path:
    return skills_dir() / ".deleted"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4:].lstrip("\n")
    return text


def _summary(path: Path, state: str, stats: dict) -> dict:
    meta = read_frontmatter(path)
    name = path.parent.name
    entry = stats.get(name, {})
    uses = entry.get("uses") or []
    summary = {
        "name": name,
        "state": state,  # active | review | disabled
        "description": meta.get("description", ""),
        "version": meta.get("version"),
        "created": str(meta.get("created", "")),
        "learned_by": meta.get("learned_by", "asked"),
        "source_chat": meta.get("source_chat", ""),
        "learned": entry.get("learned"),
        "uses": len(uses),
        "last_used": max((u.get("at", 0) for u in uses), default=None),
        "avg_seconds": round(sum(u.get("seconds", 0) for u in uses) / len(uses), 1) if uses else None,
        "avg_steps": round(sum(u.get("steps", 0) for u in uses) / len(uses), 1) if uses else None,
        "versions": sorted(int(m.group(1)) for p in (path.parent / ".versions").glob("SKILL.v*.md")
                           if (m := re.match(r"SKILL\.v(\d+)\.md$", p.name))) if state != "review" else [],
    }
    if state == "review":
        try:
            summary["review"] = json.loads((path.parent / "REVIEW.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary["review"] = {}
    return summary


def list_all() -> list[dict]:
    """Every learned skill: active, waiting for review, turned off."""
    stats = load_stats()
    out = []
    base = skills_dir()
    if base.is_dir():
        for path in sorted(base.glob("*/SKILL.md")):
            if read_frontmatter(path).get("origin") == "agent-learned":
                out.append(_summary(path, "active", stats))
    for folder, state in ((pending_dir(), "review"), (disabled_dir(), "disabled")):
        if folder.is_dir():
            for path in sorted(folder.glob("*/SKILL.md")):
                out.append(_summary(path, state, stats))
    return out


def _locate(name: str) -> tuple[Path, str]:
    name = validate_name(name)
    for path, state in ((skills_dir() / name / "SKILL.md", "active"),
                        (pending_dir(name) / "SKILL.md", "review"),
                        (disabled_dir(name) / "SKILL.md", "disabled")):
        if path.is_file() and (state != "active" or read_frontmatter(path).get("origin") == "agent-learned"):
            return path, state
    raise FileNotFoundError(f"no learned skill named {name}")


def get_content(name: str) -> dict:
    path, state = _locate(name)
    return {"name": path.parent.name, "state": state, "content": path.read_text(encoding="utf-8", errors="replace")}


def save_edit(name: str, content: str) -> int:
    """The user's edit of a learned skill. Checked like a draft; the old text
    becomes a version. Returns the new version number."""
    path, state = _locate(name)
    content = str(content or "").replace("\r\n", "\n")
    meta = read_frontmatter(path)
    new_meta = {}
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end >= 0:
            try:
                new_meta = yaml.safe_load(content[3:end]) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"the frontmatter is not valid YAML: {exc}")
    body = _strip_frontmatter(content)
    description = str((new_meta or {}).get("description") or meta.get("description") or "")
    problems = check_draft(description, body)
    if problems:
        raise ValueError("Not saved: " + "; ".join(problems) + ".")
    # an active skill gets a new version; a draft or turned-off one keeps its number
    version = current_version(path.parent.name) + 1 if state == "active" else int(meta.get("version") or 1)
    triggers = (new_meta or {}).get("triggers", meta.get("triggers"))
    rendered = render(path.parent.name, description, body, version, str(meta.get("source_chat", "")), triggers,
                      learned_by=str(meta.get("learned_by", "asked")))
    if state == "active":
        versions = path.parent / ".versions"
        versions.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, versions / f"SKILL.v{version - 1}.md")
    path.write_text(rendered, encoding="utf-8")
    return version


def has_review_waiting(name: str) -> bool:
    return (pending_dir(name) / "SKILL.md").is_file()


def approve(name: str) -> Path:
    """The user looked at a skill that waited for review: make it active."""
    target, _old = install(validate_name(name))
    return target


def disable(name: str) -> None:
    path, state = _locate(name)
    if state != "active":
        raise ValueError(f"{name} is not active")
    dest = disabled_dir(path.parent.name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path.parent), str(dest))


def enable(name: str) -> None:
    path, state = _locate(name)
    if state != "disabled":
        raise ValueError(f"{name} is not turned off")
    dest = skills_dir() / path.parent.name
    if dest.exists():
        raise ValueError(f"a skill named {path.parent.name} already exists")
    shutil.move(str(path.parent), str(dest))


def delete(name: str) -> Path:
    """Move a learned skill (any state, with its versions) out of use. It is
    kept under usr/skills/.deleted/ so a mistake can be undone by hand."""
    path, _state = _locate(name)
    dest = deleted_dir() / f"{path.parent.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path.parent), str(dest))
    with _STATS_LOCK:
        data = load_stats()
        if data.pop(path.parent.name, None) is not None:
            _save_stats(data)
    return dest


def restore_version(name: str, version: int) -> int:
    """Make an older version current again (the current one is kept too)."""
    path, state = _locate(name)
    if state != "active":
        raise ValueError(f"{name} is not active")
    old = path.parent / ".versions" / f"SKILL.v{int(version)}.md"
    if not old.is_file():
        raise FileNotFoundError(f"{name} has no version {version}")
    return save_edit(name, old.read_text(encoding="utf-8"))
