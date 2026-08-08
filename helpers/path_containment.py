"""Shared path-containment: resolve a path and verify it falls within one
of a set of allowed root directories.

Used by tools/plugins that expose filesystem or working-directory access to
the agent and need to keep that access confined to a small set of trusted
locations, e.g. the user's own project folders.
"""

import os
from pathlib import Path


class PathNotAllowedError(PermissionError):
    """Raised when a path resolves outside every allowed root directory."""


def resolve_within_roots(
    path: str, roots: list[str], *, default_root: str | None = None
) -> str:
    """Resolve `path` and ensure it falls within one of `roots`.

    Relative paths are resolved against `default_root` (or the first entry
    of `roots` if not given). Absolute paths are allowed only if they
    resolve (after following symlinks/junctions) inside one of `roots`.
    Returns the resolved absolute path as a string; raises
    PathNotAllowedError otherwise.
    """
    resolved_roots = [
        Path(r).resolve(strict=False) for r in roots if str(r or "").strip()
    ]
    if not resolved_roots:
        raise PathNotAllowedError("no allowed working directories are configured")

    base = (
        Path(default_root).resolve(strict=False) if default_root else resolved_roots[0]
    )
    expanded = os.path.expanduser(str(path or ""))
    candidate = Path(expanded)
    target = candidate if candidate.is_absolute() else base / candidate
    resolved = target.resolve(strict=False)

    for root in resolved_roots:
        try:
            resolved.relative_to(root)
            return str(resolved)
        except ValueError:
            continue

    allowed = ", ".join(str(r) for r in resolved_roots)
    raise PathNotAllowedError(
        f"path '{path}' is outside the allowed working directories ({allowed})"
    )


def resolve_with_tier(
    path: str, tier: str, roots: list[str], *, default_root: str | None = None
) -> str:
    """Like `resolve_within_roots`, but honors a tiered-access setting.

    `tier == "unrestricted"` bypasses containment entirely - the path is
    still expanded/resolved (so relative paths and `~` work the same way),
    just not checked against `roots`. Any other tier delegates unchanged to
    `resolve_within_roots`, which is also the fail-safe default: an unknown
    or unset tier value should behave like the strictest setting, not the
    most permissive one.
    """
    if tier == "unrestricted":
        expanded = os.path.expanduser(str(path or ""))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            base = (
                Path(default_root).resolve(strict=False)
                if default_root
                else Path(roots[0]).resolve(strict=False) if roots else Path.cwd()
            )
            candidate = base / candidate
        return str(candidate.resolve(strict=False))

    return resolve_within_roots(path, roots, default_root=default_root)
