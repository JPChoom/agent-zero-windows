import os
import sys
from typing import Any

from helpers import files
from helpers.files import VariablesPlugin


class EnvironmentPaths(VariablesPlugin):
    """Fill the environment prompt with this install's real locations
    instead of a hard-coded C:\a0, so the agent is told the truth on any
    machine or folder the fork is installed to."""

    def get_variables(
        self, file: str, backup_dirs: list[str] | None = None, **kwargs
    ) -> dict[str, Any]:
        return {
            "a0_root": os.path.normpath(files.get_base_dir()),
            "python_path": os.path.normpath(sys.executable),
            "python_env": os.path.normpath(sys.prefix),
        }
