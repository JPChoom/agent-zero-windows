from __future__ import annotations

import shutil
from pathlib import Path


def migrate_retired_state_tree(
    *,
    source: Path,
    destination: Path,
    owner: str,
    migrated: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    """Move retired plugin state into its plugin-owned state directory.

    Existing destination data wins. Colliding source entries are preserved under
    a suffixed name in the destination instead of overwriting live data.
    """

    if not source.exists() and not source.is_symlink():
        return
    if _same_path(source, destination):
        return

    try:
        if source.is_dir() and not source.is_symlink():
            destination.mkdir(parents=True, exist_ok=True)
            for child in list(source.iterdir()):
                try:
                    _move_path(child, destination / child.name, migrated)
                except Exception as exc:
                    errors.append(f"{owner} state migration failed for {child}: {exc}")
            _remove_empty_dir(source, owner=owner, warnings=warnings)
            return

        _move_path(source, destination, migrated)
    except Exception as exc:
        errors.append(f"{owner} state migration failed from {source} to {destination}: {exc}")


def _move_path(source: Path, target: Path, migrated: list[str]) -> None:
    if source.is_dir() and not source.is_symlink() and target.is_dir() and not target.is_symlink():
        for child in list(source.iterdir()):
            _move_path(child, target / child.name, migrated)
        source.rmdir()
        return

    final_target = target
    if target.exists() or target.is_symlink():
        final_target = _next_conflict_path(target)
    final_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(final_target))
    migrated.append(f"{source} -> {final_target}")


def _next_conflict_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.name}.retired")
    counter = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.retired-{counter}")
        counter += 1
    return candidate


def _remove_empty_dir(path: Path, *, owner: str, warnings: list[str]) -> None:
    try:
        path.rmdir()
    except OSError:
        warnings.append(f"Retired {owner} state directory was not empty after migration: {path}")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return False
