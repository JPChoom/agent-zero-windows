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
_JAVA_MARKERS = ("pom.xml", "build.gradle", "build.gradle.kts")
_GO_MARKER = "go.mod"
_RUST_MARKER = "Cargo.toml"
_CPP_MARKER = "CMakeLists.txt"
# Weakest signal of the bunch (these filenames show up in all sorts of
# repos, sometimes alongside a stronger marker for a different language)
# - checked last within a directory level so a more specific marker at
# the same level wins first.
_PYTHON_MARKERS = ("pyproject.toml", "setup.py", "requirements.txt")


class ProjectInfo(NamedTuple):
    kind: str  # "dotnet" | "npm" | "python" | "go" | "rust" | "java" | "cpp" | "powershell"
    root: str  # resolved project root directory
    marker: str  # the marker file that matched, for diagnostics


def detect_project(start_path: str) -> ProjectInfo | None:
    """Walk upward from start_path looking for the nearest project markers.

    start_path may be a file or a directory. Markers are checked in order
    at each directory level (most specific/unambiguous first): .sln or
    .csproj/.fsproj/.vbproj (dotnet), package.json (npm), pom.xml/
    build.gradle(.kts) (java), go.mod (go), Cargo.toml (rust),
    CMakeLists.txt (cpp), then pyproject.toml/setup.py/requirements.txt
    (python, checked last - these filenames are common enough to show up
    incidentally in a repo for another language). Walks up to
    _MAX_WALK_LEVELS parent directories. If none is found and start_path
    is itself a .ps1 file, its own directory is treated as a lint-only
    PowerShell "project" (PowerShell scripts don't have a meaningful
    project root the way the others do). Returns None if nothing matches.
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

        java_marker = next((m for m in _JAVA_MARKERS if m in names), "")
        if java_marker:
            return ProjectInfo("java", str(current), java_marker)

        if _GO_MARKER in names:
            return ProjectInfo("go", str(current), _GO_MARKER)

        if _RUST_MARKER in names:
            return ProjectInfo("rust", str(current), _RUST_MARKER)

        if _CPP_MARKER in names:
            return ProjectInfo("cpp", str(current), _CPP_MARKER)

        python_marker = next((m for m in _PYTHON_MARKERS if m in names), "")
        if python_marker:
            return ProjectInfo("python", str(current), python_marker)

        parent = current.parent
        if parent == current:
            break
        current = parent

    if original.is_file() and original.suffix.lower() == ".ps1":
        return ProjectInfo("powershell", str(original.parent), original.name)

    return None
