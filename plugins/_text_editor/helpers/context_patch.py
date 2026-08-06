from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class ContextPatchError(ValueError):
    """Raised when a context patch cannot be parsed or applied safely."""


@dataclass(frozen=True)
class ContextPatchApplyResult:
    content: str
    line_from: int
    line_to: int
    hunk_count: int


@dataclass(frozen=True)
class _PatchLine:
    kind: str
    text: str


@dataclass(frozen=True)
class _Hunk:
    anchor: str
    lines: tuple[_PatchLine, ...]


@dataclass(frozen=True)
class _HunkApplyResult:
    cursor: int
    line_from: int
    line_to: int


_FILE_HEADERS = (
    "*** Update File:",
    "*** Add File:",
    "*** Delete File:",
    "*** End Patch",
)


def apply_context_patch(content: str, patch_text: str) -> str:
    """Apply a PseudoPatch-inspired context patch to one text file."""
    return apply_context_patch_with_metadata(content, patch_text).content


def apply_context_patch_with_metadata(
    content: str, patch_text: str
) -> ContextPatchApplyResult:
    """Apply a context patch and report the touched line range."""
    body = _extract_single_file_body(patch_text)
    hunks = _parse_hunks(body)
    if not hunks:
        raise ContextPatchError("patch_text must contain at least one update hunk")

    lines = content.split("\n")
    cursor = 0
    line_from: int | None = None
    line_to = 1
    for hunk in hunks:
        result = _apply_hunk(lines, hunk, cursor)
        cursor = result.cursor
        line_from = (
            result.line_from if line_from is None
            else min(line_from, result.line_from)
        )
        line_to = max(line_to, result.line_to)

    return ContextPatchApplyResult(
        content="\n".join(lines),
        line_from=line_from or 1,
        line_to=line_to,
        hunk_count=len(hunks),
    )


def _extract_single_file_body(patch_text: str) -> list[str]:
    raw_lines = [line.rstrip("\r") for line in str(patch_text).splitlines()]
    lines = _trim_outer_blank_lines(raw_lines)
    if not lines:
        raise ContextPatchError("patch_text is required")

    if not lines[0].startswith("*** Begin Patch"):
        return lines
    if len(lines) < 2 or lines[-1] != "*** End Patch":
        raise ContextPatchError("patch_text missing *** End Patch")

    body: list[str] = []
    in_update = False
    update_count = 0
    for line in lines[1:-1]:
        if line.startswith("*** Update File:"):
            if update_count:
                raise ContextPatchError(
                    "patch_text may update only one file per operation"
                )
            in_update = True
            update_count += 1
            continue
        if line.startswith("*** Move to:"):
            raise ContextPatchError("patch_text does not support file moves")
        if line.startswith(("*** Add File:", "*** Delete File:")):
            raise ContextPatchError("patch_text supports update hunks only")
        if in_update:
            body.append(line)

    if not update_count:
        raise ContextPatchError("patch_text must include an update file block")
    return body


def _trim_outer_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _parse_hunks(lines: list[str]) -> list[_Hunk]:
    hunks: list[_Hunk] = []
    anchor = ""
    current: list[_PatchLine] = []

    def finish_current() -> None:
        nonlocal anchor, current
        if current:
            hunks.append(_Hunk(anchor=anchor, lines=tuple(current)))
            current = []
        anchor = ""

    for line in lines:
        if line.startswith(_FILE_HEADERS):
            finish_current()
            break
        if line.startswith("@@"):
            finish_current()
            anchor = line[2:].strip()
            continue
        if line.startswith("***"):
            raise ContextPatchError(f"invalid patch control line: {line}")

        if line == "":
            current.append(_PatchLine(" ", ""))
            continue
        if line[0] not in {" ", "+", "-"}:
            raise ContextPatchError(f"invalid patch line prefix: {line}")
        current.append(_PatchLine(line[0], line[1:]))

    finish_current()
    return hunks


def _apply_hunk(
    lines: list[str], hunk: _Hunk, cursor: int
) -> _HunkApplyResult:
    old_lines = [line.text for line in hunk.lines if line.kind in {" ", "-"}]
    new_lines = [line.text for line in hunk.lines if line.kind in {" ", "+"}]

    if old_lines == new_lines:
        raise ContextPatchError("patch hunk does not change content")
    if not old_lines:
        if not hunk.anchor:
            raise ContextPatchError("insert-only patch hunk needs an @@ anchor")
        insert_at = _find_anchor(lines, hunk.anchor, cursor)
        lines[insert_at:insert_at] = new_lines
        return _HunkApplyResult(
            cursor=insert_at + len(new_lines),
            line_from=insert_at + 1,
            line_to=insert_at + max(len(new_lines), 1),
        )

    start = cursor
    if hunk.anchor:
        start = _find_anchor(lines, hunk.anchor, cursor)

    try:
        match_index = _find_context(lines, old_lines, start, anchored=bool(hunk.anchor))
    except ContextPatchError:
        if not hunk.anchor:
            raise
        # Models often anchor on the line they want to replace. Preserve the
        # insert-after-anchor rule, but allow replacement context to start at
        # the anchor line when it is not found after the anchor.
        match_index = _find_context(lines, old_lines, start - 1, anchored=True)
    lines[match_index : match_index + len(old_lines)] = new_lines
    return _HunkApplyResult(
        cursor=match_index + len(new_lines),
        line_from=match_index + 1,
        line_to=match_index + max(len(new_lines), 1),
    )


def _find_anchor(lines: list[str], anchor: str, start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index] == anchor:
            return index + 1
    stripped_anchor = anchor.strip()
    for index in range(start, len(lines)):
        if lines[index].strip() == stripped_anchor:
            return index + 1
    raise ContextPatchError(f"anchor not found: {anchor}")


def _find_context(
    lines: list[str],
    context: list[str],
    start: int,
    *,
    anchored: bool,
) -> int:
    matches = _matching_indexes(lines, context, start, mode="exact")
    if not matches:
        matches = _matching_indexes(lines, context, start, mode="rstrip")

    if not matches:
        preview = "\n".join(context[:5])
        raise ContextPatchError(f"context not found:\n{preview}")
    if len(matches) > 1 and not anchored:
        preview = "\n".join(context[:5])
        raise ContextPatchError(
            "context matched multiple locations; add an @@ anchor or more context:\n"
            f"{preview}"
        )
    return matches[0]


def _matching_indexes(
    lines: list[str],
    context: list[str],
    start: int,
    *,
    mode: str,
) -> list[int]:
    if len(lines) < len(context):
        return []

    matches: list[int] = []
    for index in range(max(start, 0), len(lines) - len(context) + 1):
        candidate = lines[index : index + len(context)]
        if _lines_equal(candidate, context, mode=mode):
            matches.append(index)
    return matches


def _lines_equal(left: Iterable[str], right: Iterable[str], *, mode: str) -> bool:
    if mode == "rstrip":
        return [item.rstrip() for item in left] == [item.rstrip() for item in right]
    return list(left) == list(right)
