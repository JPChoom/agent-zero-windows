"""Unrestricted folder listing for the Settings folder picker. The File
Browser itself lives in helpers/file_manager.py behind helpers/file_access.py."""

import os
from pathlib import Path
from typing import Any, Dict, List

from helpers.print_style import PrintStyle


def list_directory_absolute(path: str = "") -> Dict:
    """List a directory's subfolders by absolute path, with no workdir
    containment check.

    For user-initiated (Settings-page) folder browsing outside the
    workdir - e.g. picking an external project root for the tiered
    filesystem-access setting. Folder-only and deliberately unrestricted: it backs
    api/get_folder_browser_files.py, which only an authenticated user on
    the Settings page reaches. Not wired into any agent-facing endpoint.

    An empty path lists available drive roots on Windows (there is no
    single filesystem root to start from), or "/" on POSIX.
    """
    path = str(path or "").strip()
    if not path:
        if os.name == "nt":
            import string

            drives = [
                f"{letter}:\\"
                for letter in string.ascii_uppercase
                if os.path.exists(f"{letter}:\\")
            ]
            entries = [
                {"name": drive, "path": drive, "type": "folder", "size": 0, "is_dir": True}
                for drive in drives
            ]
            return {"entries": entries, "current_path": "", "parent_path": ""}
        path = "/"

    try:
        full_path = Path(path).resolve(strict=False)
        if not full_path.exists():
            raise FileNotFoundError("Directory not found")
        if not full_path.is_dir():
            raise NotADirectoryError("Path is not a directory")

        folders: List[Dict[str, Any]] = []
        with os.scandir(full_path) as iterator:
            for entry in iterator:
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue  # folder picker only needs directories
                except OSError:
                    continue
                folders.append(
                    {
                        "name": entry.name,
                        "path": str(Path(entry.path).resolve(strict=False)),
                        "type": "folder",
                        "size": 0,
                        "is_dir": True,
                    }
                )
        folders.sort(key=lambda item: item["name"].lower())

        parent = str(full_path.parent)
        # Going up from a drive root ("C:\") would otherwise return itself
        # as its own parent - route back to the drive list instead.
        if parent.rstrip("\\/") == str(full_path).rstrip("\\/"):
            parent = ""

        return {"entries": folders, "current_path": str(full_path), "parent_path": parent}
    except Exception as e:
        PrintStyle.error(f"Error reading directory: {e}")
        return {"entries": [], "current_path": path, "parent_path": "", "error": str(e)}
