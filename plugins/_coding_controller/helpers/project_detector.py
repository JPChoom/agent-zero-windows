"""Detects a project's type by marker files, so the coding controller knows
which gate adapter and commands to run.

No project-type detection existed anywhere in this codebase before this -
the existing "file structure injection" feature (helpers/projects.py) is a
generic gitignore-driven directory listing with no language awareness.
"""

from pathlib import Path
from typing import NamedTuple

_MAX_WALK_LEVELS = 25
_DOTNET_PROJECT_EXTS = (".csproj", ".fsproj", ".vbproj")
_NPM_MARKER = "package.json"


class ProjectInfo(NamedTuple):
    kind: str  # "dotnet" | "npm" | "powershell"
    root: str  # resolved project root directory
    marker: str  # the marker file that matched, for diagnostics


def detect_project(start_path: str) -> ProjectInfo | None:
    """Walk upward from start_path looking for the nearest project markers.

    start_path may be a file or a directory. A .sln or .csproj/.fsproj/.vbproj
    file marks a dotnet project; package.json marks an npm project - these
    are checked first, walking up to _MAX_WALK_LEVELS parent directories.
    If none is found and start_path is itself a .ps1 file, its own
    directory is treated as a lint-only PowerShell "project" (PowerShell
    scripts don't have a meaningful project root the way dotnet/npm do).
    Returns None if nothing matches.
    """
    original = Path(start_path)
    current = original if original.is_dir() else original.parent

    for _ in range(_MAX_WALK_LEVELS):
        try:
            names = {entry.name for entry in current.iterdir()}
        except OSError:
            names = set()

        sln = next((n for n in names if n.lower().endswith(".sln")), "")
        if sln:
            return ProjectInfo("dotnet", str(current), sln)

        proj = next(
            (n for n in names if n.lower().endswith(_DOTNET_PROJECT_EXTS)), ""
        )
        if proj:
            return ProjectInfo("dotnet", str(current), proj)

        if _NPM_MARKER in names:
            return ProjectInfo("npm", str(current), _NPM_MARKER)

        parent = current.parent
        if parent == current:
            break
        current = parent

    if original.is_file() and original.suffix.lower() == ".ps1":
        return ProjectInfo("powershell", str(original.parent), original.name)

    return None
