from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PatchMode = Literal["edits", "patch_text", "replace"]


@dataclass(frozen=True)
class PatchRequest:
    mode: PatchMode
    edits: Any = None
    patch_text: str = ""
    old_text: str = ""
    new_text: str = ""


def parse_patch_request(
    edits: Any,
    patch_text: Any,
    old_text: Any = None,
    new_text: Any = None,
    *,
    both_error: str = "provide exactly one patch form: edits, patch_text, or old_text/new_text",
    missing_error: str = "edits, patch_text, or old_text/new_text is required for patch",
) -> tuple[PatchRequest | None, str]:
    """Validate the mutually-exclusive patch request shape."""
    has_edits = edits is not None
    has_patch_text = patch_text is not None
    has_replace = old_text is not None or new_text is not None
    if sum([has_edits, has_patch_text, has_replace]) > 1:
        return None, both_error

    if has_replace:
        old = str(old_text or "")
        if not old:
            return None, "old_text is required for exact replace"
        return PatchRequest(
            mode="replace",
            old_text=old,
            new_text=str(new_text or ""),
        ), ""

    if has_patch_text:
        text = str(patch_text)
        if not text.strip():
            return None, "patch_text must not be empty"
        return PatchRequest(mode="patch_text", patch_text=text), ""

    if not edits:
        return None, missing_error

    return PatchRequest(mode="edits", edits=edits), ""


def exact_replace_to_patch_text(path: str, old_text: str, new_text: str) -> str:
    """Represent one exact text replacement as a context patch."""
    lines = [
        "*** Begin Patch",
        f"*** Update File: {path}",
    ]
    lines.extend(f"-{line}" for line in old_text.split("\n"))
    lines.extend(f"+{line}" for line in new_text.split("\n"))
    lines.append("*** End Patch")
    return "\n".join(lines)
