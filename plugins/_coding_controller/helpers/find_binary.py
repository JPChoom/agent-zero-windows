"""Shared executable discovery: shutil.which() first, then a Windows
Program Files fallback list. Same shape as plugins/_office/helpers/
libreoffice.py's find_soffice(), which exists because Windows installers
often don't add their own binaries to PATH.
"""

import os
import shutil


def find_executable(names: tuple[str, ...], windows_candidates: tuple[str, ...] = ()) -> str:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for candidate in windows_candidates:
            if os.path.isfile(candidate):
                return candidate
    return ""
