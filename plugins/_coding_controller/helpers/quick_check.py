"""A syntax check right after the agent writes a file.

The completion gate runs a project's full lint/build/test, and only when it
is turned on for that project. This is the cheap check every edit gets: is
the file still valid Python, JSON, YAML, TOML or JavaScript? A broken file
is reported in the same tool result, so the agent fixes it on its next step
instead of finding out several steps later.

Python, JSON, YAML and TOML are checked in-process (no code runs: compile()
only parses). JavaScript uses `node --check` when Node is installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
NODE_TIMEOUT_SECONDS = 5


def _python(text: str, path: str) -> str:
    try:
        compile(text, path, "exec", dont_inherit=True)
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return ""


def _json(text: str, path: str) -> str:
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return ""


def _yaml(text: str, path: str) -> str:
    import yaml

    try:
        list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark is not None else ""
        return where + str(getattr(exc, "problem", None) or exc).strip()
    return ""


def _toml(text: str, path: str) -> str:
    import tomllib

    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return str(exc)
    return ""


def _javascript(text: str, path: str) -> str:
    node = shutil.which("node")
    if not node:
        return ""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run([node, "--check", path], capture_output=True, text=True,
                                timeout=NODE_TIMEOUT_SECONDS, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode == 0:
        return ""
    lines = [line for line in (result.stderr or "").splitlines() if line.strip()]
    first = next((line for line in lines if "SyntaxError" in line), lines[-1] if lines else "syntax error")
    where = next((line.rsplit(":", 1)[-1] for line in lines[:1] if line.rsplit(":", 1)[-1].isdigit()), "")
    return (f"line {where}: " if where else "") + first.strip()


CHECKS = {
    ".py": _python,
    ".json": _json,
    ".yaml": _yaml,
    ".yml": _yaml,
    ".toml": _toml,
    ".js": _javascript,
    ".mjs": _javascript,
    ".cjs": _javascript,
}


def check(path: str) -> str:
    """"" when the file parses (or is not a kind checked here), else the error."""
    file = Path(path)
    check_fn = CHECKS.get(file.suffix.lower())
    if check_fn is None or not file.is_file():
        return ""
    try:
        if file.stat().st_size > MAX_BYTES:
            return ""
        text = file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""
    try:
        return check_fn(text, str(file))
    except Exception:
        return ""  # a check that cannot run says nothing


def resolve(path: str) -> str:
    """The file the text_editor call wrote, as a real path."""
    from helpers import files

    value = files.native_path(str(path or "").strip())
    if not value:
        return ""
    if not os.path.isabs(value):
        try:
            from plugins._text_editor.helpers.file_ops import get_workdir_root

            value = str(get_workdir_root() / value)
        except Exception:
            return ""
    return value
