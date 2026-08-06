from __future__ import annotations

from typing import Any

from plugins._text_editor.helpers.patch_state import (
    REMOTE_FRESHNESS_KEY as _FRESHNESS_KEY,
    FileMetadata,
    apply_patch_post_state as _apply_patch_post_state,
    check_patch_freshness as _check_patch_freshness,
    coerce_file_metadata,
    mark_file_state_stale as _mark_file_state_stale,
    record_file_state as _record_file_state,
)


def record_file_state(agent, file_data: Any) -> None:
    _record_file_state(agent, file_data, key=_FRESHNESS_KEY)


def mark_file_state_stale(agent, file_data: Any) -> None:
    _mark_file_state_stale(agent, file_data, key=_FRESHNESS_KEY)


def check_patch_freshness(agent, file_data: Any) -> str | None:
    return _check_patch_freshness(agent, file_data, key=_FRESHNESS_KEY)


def apply_patch_post_state(
    agent, file_data: Any, edits: list[Any] | None
) -> None:
    _apply_patch_post_state(agent, file_data, edits, key=_FRESHNESS_KEY)
