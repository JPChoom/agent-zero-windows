"""
Pure file operations for the text_editor plugin.

No agent/tool dependencies — only stdlib + tokens helper.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import TypedDict

from helpers import tokens
from plugins._text_editor.helpers.context_patch import (
    apply_context_patch_with_metadata,
)

_BINARY_PEEK = 8192


# ------------------------------------------------------------------
# Path containment
#
# All text_editor file access is confined to the configured workdir root
# (settings["workdir_path"], defaults to usr/workdir) plus any external
# project folders _code_execution's terminal is also allowed into
# (allowed_external_roots) - otherwise the agent could `dotnet build` an
# external project via the terminal's "cwd" arg but never be able to
# actually read/patch the files that build depends on, which defeats the
# point of allowing that project at all. Uses the same boundary-check
# logic (helpers/path_containment.py) as _code_execution's cwd validation,
# with a real path-boundary check (Path.relative_to) instead of a
# string-prefix comparison, resolving symlinks/junctions before the
# boundary check so an escape can't hide behind a reparse point.
# ------------------------------------------------------------------

class PathNotAllowedError(PermissionError):
    """Raised when a path resolves outside every allowed root."""


def get_workdir_root() -> Path:
    from helpers import settings

    return Path(settings.get_settings()["workdir_path"]).resolve(strict=False)


def _get_access_config() -> tuple[str, list[str]]:
    """_code_execution's access_tier + allowed_external_roots, global scope
    only.

    This module is deliberately agent/tool-agnostic (see module
    docstring), so it has no agent/project context to resolve a
    per-project override of this setting through - only the global
    config is visible here. A per-project-aware version would need
    file_ops's read/write/patch functions to accept an agent parameter,
    which is a larger change than this fix warrants.
    """
    try:
        from helpers import plugins as plugins_helper

        cfg = plugins_helper.get_plugin_config("_code_execution") or {}
    except Exception:
        return "workdir_only", []
    tier = str(cfg.get("access_tier", "workdir_only") or "workdir_only").strip().lower()
    if tier not in ("workdir_only", "allowlist", "unrestricted"):
        tier = "workdir_only"
    raw = cfg.get("allowed_external_roots", "")
    lines = raw.splitlines() if isinstance(raw, str) else (raw or [])
    roots = [str(line).strip() for line in lines if str(line or "").strip()]
    return tier, roots


def confine_to_workdir(path: str) -> str:
    """Resolve `path` and enforce containment according to
    _code_execution's access_tier: workdir root only ("workdir_only",
    the default), workdir root plus allowed_external_roots ("allowlist"),
    or no containment at all ("unrestricted") - kept in lockstep with
    _code_execution's own cwd resolution so an agent that can `cd` a
    terminal into a folder can also read/patch the files in it.

    Relative paths resolve against the workdir root specifically (not the
    process cwd, and not any external root). Absolute paths are allowed
    only if they resolve (after following symlinks/junctions) inside one
    of the allowed roots, unless the tier is unrestricted. Returns the
    resolved absolute path as a string; raises PathNotAllowedError
    otherwise.
    """
    from helpers import path_containment

    workdir = get_workdir_root()
    tier, external_roots = _get_access_config()
    roots = [str(workdir)] + (external_roots if tier == "allowlist" else [])
    try:
        return path_containment.resolve_with_tier(
            path, tier, roots, default_root=str(workdir)
        )
    except path_containment.PathNotAllowedError as exc:
        raise PathNotAllowedError(str(exc)) from exc


# ------------------------------------------------------------------
# Line-ending preservation
#
# Reads/writes below use newline="" to stop Python's own universal-newline
# translation from silently rewriting a file's line endings (e.g. an LF repo
# file getting flipped to CRLF just because it was opened on Windows).
# Content coming from the agent (edit/patch/replacement text) normally uses
# bare "\n", so it is re-normalized to match the target file's existing
# convention before being written back in.
# ------------------------------------------------------------------

def _detect_line_ending(sample: str) -> str:
    crlf = sample.count("\r\n")
    lf_only = sample.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _detect_line_ending_from_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            sample = f.read(65536)
    except OSError:
        return "\n"
    return _detect_line_ending(sample)


def _normalize_line_ending(content: str, line_ending: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if line_ending == "\n":
        return normalized
    return normalized.replace("\n", line_ending)


# ------------------------------------------------------------------
# Binary detection
# ------------------------------------------------------------------

def is_binary(path: str) -> bool:
    """Detect binary file by checking for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(_BINARY_PEEK)
        return b"\x00" in chunk
    except OSError:
        return False


# ------------------------------------------------------------------
# File metadata
# ------------------------------------------------------------------

class FileInfo(TypedDict):
    exists: bool
    is_file: bool
    realpath: str
    expanded: str
    mtime: float | None
    error: str


def file_info(path: str) -> FileInfo:
    """Return file metadata for mtime tracking and path resolution."""
    try:
        path = confine_to_workdir(path)
    except PathNotAllowedError as exc:
        return FileInfo(
            exists=False, is_file=False, realpath="", expanded=path, mtime=None,
            error=str(exc),
        )
    rp = os.path.realpath(path)
    exists = os.path.exists(path)
    is_file = os.path.isfile(path)
    mtime = None
    if exists:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            pass
    return FileInfo(
        exists=exists,
        is_file=is_file,
        realpath=rp,
        expanded=path,
        mtime=mtime,
        error="",
    )


# ------------------------------------------------------------------
# Read
# ------------------------------------------------------------------

class ReadResult(TypedDict):
    content: str
    total_lines: int
    warnings: str
    error: str


def read_file(
    path: str,
    line_from: int = 1,
    line_to: int | None = None,
    max_line_tokens: int = 500,
    default_line_count: int = 100,
    max_total_read_tokens: int = 4000,
) -> ReadResult:
    """
    Read a text file and return numbered lines with token budgeting.

    Line numbers are 1-based (matching grep, sed, editors).
    line_from and line_to are both inclusive.
    None line_to defaults to line_from + default_line_count - 1.
    """
    try:
        path = confine_to_workdir(path)
    except PathNotAllowedError as exc:
        return ReadResult(content="", total_lines=0, warnings="", error=str(exc))

    if not os.path.isfile(path):
        return ReadResult(
            content="", total_lines=0, warnings="",
            error="file not found",
        )

    if is_binary(path):
        return ReadResult(
            content="", total_lines=0, warnings="",
            error="file appears binary, use terminal instead",
        )

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            all_lines = f.readlines()
    except OSError as exc:
        return ReadResult(
            content="", total_lines=0, warnings="",
            error=str(exc),
        )

    total_lines = len(all_lines)
    line_from = max(line_from, 1)
    if line_to is None:
        line_to = line_from + default_line_count - 1
    line_to = min(line_to, total_lines)

    # Convert 1-based inclusive range to 0-based slice
    idx_from = line_from - 1
    idx_to = line_to  # slice is exclusive, line_to is inclusive 1-based
    selected = all_lines[idx_from:idx_to]
    num_width = len(str(line_to))

    warn_parts: list[str] = []
    cropped_lines: list[int] = []
    output_lines: list[str] = []
    running_tokens = 0
    trimmed_by_total = False

    for i, raw_line in enumerate(selected):
        line_no = line_from + i  # 1-based
        stripped = raw_line.rstrip("\n").rstrip("\r")
        line_tok = tokens.count_tokens(stripped)

        if line_tok > max_line_tokens:
            chars_per_tok = max(len(stripped) / line_tok, 1)
            keep_chars = int(max_line_tokens * chars_per_tok * tokens.TRIM_BUFFER)
            stripped = stripped[:keep_chars] + "..."
            cropped_lines.append(line_no)
            line_tok = max_line_tokens

        if running_tokens + line_tok > max_total_read_tokens:
            trimmed_by_total = True
            break

        running_tokens += line_tok
        output_lines.append(f"{line_no:>{num_width}} {stripped}")

    if cropped_lines:
        nums = " ".join(str(n) for n in cropped_lines)
        warn_parts.append(
            f"long lines {nums} cropped - use terminal for precise manipulation"
        )
    if trimmed_by_total:
        actual_end = line_from + len(output_lines)
        warn_parts.append(
            f"output trimmed at line {actual_end} due to token limit"
            " - use line_from/line_to for remaining"
        )

    warn_str = ""
    if warn_parts:
        warn_str = "\nwarning: " + "; ".join(warn_parts)

    return ReadResult(
        content="\n".join(output_lines),
        total_lines=total_lines,
        warnings=warn_str,
        error="",
    )


# ------------------------------------------------------------------
# Write
# ------------------------------------------------------------------

class WriteResult(TypedDict):
    total_lines: int
    error: str


def write_file(path: str, content: str | None) -> WriteResult:
    """Create or overwrite a file atomically, preserving its existing line ending."""
    if content is None:
        content = ""
    try:
        path = confine_to_workdir(path)
    except PathNotAllowedError as exc:
        return WriteResult(total_lines=0, error=str(exc))
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.isfile(path):
            content = _normalize_line_ending(content, _detect_line_ending_from_file(path))

        dir_name = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            shutil.move(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except OSError as exc:
        return WriteResult(total_lines=0, error=str(exc))

    total = content.count("\n") + (
        1 if content and not content.endswith("\n") else 0
    )
    return WriteResult(total_lines=total, error="")


# ------------------------------------------------------------------
# Patch
# ------------------------------------------------------------------

class PatchResult(TypedDict):
    total_lines: int
    edit_count: int
    error: str


class ContextPatchFileResult(TypedDict):
    total_lines: int
    hunk_count: int
    line_from: int
    line_to: int


class ExactReplaceFileResult(TypedDict):
    total_lines: int
    replacement_count: int
    line_from: int
    line_to: int


def validate_edits(edits: list | None) -> tuple[list[dict], str]:
    """
    Normalise and validate an edits array.

    Line numbers are 1-based (matching grep, sed, editors).
    Semantics (to is inclusive):
      {from:2, to:2, content:"x\\n"} - replace line 2
      {from:1, to:3, content:"x\\n"} - replace lines 1-3
      {from:2, to:2}                 - delete line 2
      {from:5}  or {from:5, to:-1}   - insert before line 5 (no deletion)

    Returns (parsed_edits, error_string). error_string is empty on success.
    """
    if not edits or not isinstance(edits, list):
        return [], "edits array is required"

    parsed: list[dict] = []
    for e in edits:
        if not isinstance(e, dict):
            return [], f"invalid edit entry: {e}"
        frm = int(e.get("from", 0))
        if frm < 1:
            return [], f"edit missing or invalid from (must be >= 1): {e}"
        # to == -1 or absent means pure insert (no lines removed)
        to = int(e.get("to", -1))
        is_insert = to < 0 or to < frm
        if is_insert:
            to = frm - 1  # normalise: marks zero-width range
        parsed.append({
            "from": frm,
            "to": to,
            "content": e.get("content", ""),
            "insert": is_insert,
        })

    parsed.sort(key=lambda x: (x["from"], 0 if x["insert"] else 1))
    for i in range(1, len(parsed)):
        prev, cur = parsed[i - 1], parsed[i]
        # Inserts at the same line don't overlap with each other or
        # with a replace that starts at the same line.
        if prev["insert"]:
            continue
        # prev is a replace/delete: its range is [from..to] inclusive
        if cur["from"] <= prev["to"]:
            return [], (
                f"overlapping edits: edit at {prev['from']}"
                f" (to {prev['to']}) and {cur['from']}"
                f" (to {cur['to']})"
            )

    return parsed, ""


def apply_patch(path: str, edits: list[dict]) -> int:
    """
    Apply sorted, validated edits by streaming to a temp file.

    Line numbers are 1-based. Edits use inclusive 'to'.
    Inserts have 'insert': True.
    Returns total line count after patching.
    """
    # Normalize edit content to the file's existing line ending, and ensure
    # content always ends with a newline to prevent line merging
    line_ending = _detect_line_ending_from_file(path)
    for e in edits:
        if e["content"]:
            e["content"] = _normalize_line_ending(e["content"], line_ending)
            if not e["content"].endswith(line_ending):
                e["content"] += line_ending

    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with (
            open(path, "r", encoding="utf-8", errors="replace", newline="") as src,
            os.fdopen(fd, "w", encoding="utf-8", newline="") as dst,
        ):
            edit_idx = 0
            line_no = 1  # 1-based
            total_written = 0

            for raw_line in src:
                # Process all inserts targeting this line first
                while (
                    edit_idx < len(edits)
                    and edits[edit_idx]["insert"]
                    and edits[edit_idx]["from"] == line_no
                ):
                    edit = edits[edit_idx]
                    if edit["content"]:
                        dst.write(edit["content"])
                        total_written += _count_content_lines(edit["content"])
                    edit_idx += 1

                # Check if current line falls in a replace/delete range
                if edit_idx < len(edits) and not edits[edit_idx]["insert"]:
                    edit = edits[edit_idx]
                    if edit["from"] <= line_no <= edit["to"]:
                        # Write replacement content once at range start
                        if line_no == edit["from"] and edit["content"]:
                            dst.write(edit["content"])
                            total_written += _count_content_lines(
                                edit["content"]
                            )
                        # Skip original line; advance edit at range end
                        if line_no == edit["to"]:
                            edit_idx += 1
                        line_no += 1
                        continue

                dst.write(raw_line)
                total_written += 1
                line_no += 1

            # Remaining edits past end of file
            while edit_idx < len(edits):
                edit = edits[edit_idx]
                if edit["content"]:
                    dst.write(edit["content"])
                    total_written += _count_content_lines(edit["content"])
                edit_idx += 1

        shutil.move(tmp_path, path)
        return total_written
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def patch_file(path: str, edits: list | None) -> PatchResult:
    """Validate and apply edits to a file."""
    try:
        path = confine_to_workdir(path)
    except PathNotAllowedError as exc:
        return PatchResult(total_lines=0, edit_count=0, error=str(exc))
    if not os.path.isfile(path):
        return PatchResult(total_lines=0, edit_count=0, error="file not found")

    parsed, err = validate_edits(edits)
    if err:
        return PatchResult(total_lines=0, edit_count=0, error=err)

    try:
        total = apply_patch(path, parsed)
    except Exception as exc:
        return PatchResult(total_lines=0, edit_count=0, error=str(exc))

    return PatchResult(total_lines=total, edit_count=len(parsed), error="")


def apply_context_patch_file(path: str, patch_text: str) -> ContextPatchFileResult:
    """Apply a context patch to an existing text file."""
    path = confine_to_workdir(path)
    if not os.path.isfile(path):
        raise FileNotFoundError("file not found")

    with open(path, "r", encoding="utf-8", errors="replace", newline="") as src:
        raw_content = src.read()
    line_ending = _detect_line_ending(raw_content)
    content = raw_content.replace("\r\n", "\n").replace("\r", "\n")

    result = apply_context_patch_with_metadata(content, patch_text)
    final_content = _normalize_line_ending(result.content, line_ending)
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as dst:
            dst.write(final_content)
        shutil.move(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return ContextPatchFileResult(
        total_lines=_count_content_lines(final_content),
        hunk_count=result.hunk_count,
        line_from=result.line_from,
        line_to=result.line_to,
    )


def apply_exact_replace_file(
    path: str, old_text: str, new_text: str
) -> ExactReplaceFileResult:
    """Replace exactly one text span in an existing text file."""
    path = confine_to_workdir(path)
    if not os.path.isfile(path):
        raise FileNotFoundError("file not found")
    if not old_text:
        raise ValueError("old_text is required for exact replace")

    with open(path, "r", encoding="utf-8", errors="replace", newline="") as src:
        raw_content = src.read()
    line_ending = _detect_line_ending(raw_content)
    content = raw_content.replace("\r\n", "\n").replace("\r", "\n")
    old_text = old_text.replace("\r\n", "\n").replace("\r", "\n")
    new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")

    match_count = content.count(old_text)
    if match_count == 0:
        raise ValueError("old_text not found")
    if match_count > 1:
        raise ValueError(
            f"old_text matched {match_count} times; provide a longer exact span"
        )
    if old_text == new_text:
        raise ValueError("old_text and new_text are identical")

    start = content.index(old_text)
    line_from = content[:start].count("\n") + 1
    line_to = line_from + max(_count_content_lines(old_text) - 1, 0)
    new_content = content.replace(old_text, new_text, 1)
    final_content = _normalize_line_ending(new_content, line_ending)

    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as dst:
            dst.write(final_content)
        shutil.move(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return ExactReplaceFileResult(
        total_lines=_count_content_lines(final_content),
        replacement_count=1,
        line_from=line_from,
        line_to=line_to,
    )


# ------------------------------------------------------------------
# Internal
# ------------------------------------------------------------------

def _count_content_lines(content: str) -> int:
    return content.count("\n") + (
        1 if content and not content.endswith("\n") else 0
    )
