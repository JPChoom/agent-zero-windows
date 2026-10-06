"""Agent-learned skills: drafting, checks, approval-gated install and versions.

A learned skill is a normal `usr/skills/<name>/SKILL.md` whose frontmatter
carries `origin: agent-learned`, a `version` and the `source_chat`. It never
becomes active without the user approving it:

    draft  -> usr/skills/.pending/<name>/SKILL.md   (hidden: never loaded)
    approve -> usr/skills/<name>/SKILL.md           (active)
              previous version kept as usr/skills/<name>/.versions/SKILL.v<N>.md

Skill discovery skips hidden folders (helpers/skills.py), which is what
keeps drafts and old versions inert.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from helpers import files
from helpers.untrusted_content import looks_like_injected_instruction

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
TRUST_LEVELS = ("built-in", "user", "agent-learned", "downloaded")

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
        raise ValueError("name must be 3-64 characters of lowercase letters, digits and hyphens, e.g. 'export-blender-step'.")
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


def render(name: str, description: str, body: str, version: int, source_chat: str, triggers=None) -> str:
    meta = {
        "name": name,
        "description": " ".join(str(description).split()),
        "origin": "agent-learned",
        "version": version,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source_chat": source_chat,
    }
    if triggers:
        meta["triggers"] = [str(t) for t in triggers][:10]
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n\n{body.strip()}\n"


def write_draft(name: str, content: str) -> Path:
    folder = pending_dir(name)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(content, encoding="utf-8")
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
