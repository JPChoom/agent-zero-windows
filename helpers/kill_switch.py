"""Global kill switch: a process the agent itself cannot control (hand-off
doc §12.16). Backed by a flag file (usr/.kill_switch) so the tripped
state survives a process restart - an agent that got itself tripped
can't just wait out a restart to clear it.

No tool exposes trip()/reset() to the model - the only callers are
api/kill_switch.py (a small header UI control, not a chat action) and
this module's own tests. Checked in two independent places for
defense-in-depth (plugins/_safety_policy's command-policy extension, and
directly inside plugins/_code_execution/tools/code_execution_tool.py's
execute()), so disabling or misconfiguring the _safety_policy plugin
doesn't silently bypass it.
"""

import json
import time

from helpers import files

_FLAG_FILENAME = ".kill_switch"


def get_flag_path() -> str:
    return files.get_abs_path(files.USER_DIR, _FLAG_FILENAME)


def is_tripped() -> bool:
    import os

    return os.path.exists(get_flag_path())


def get_reason() -> str:
    """Returns the reason recorded when the switch was tripped, or "" if
    not tripped or no reason was recorded."""
    path = get_flag_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("reason", "") or "")
    except (OSError, ValueError):
        return ""


def trip(reason: str = "") -> None:
    path = get_flag_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"reason": reason, "time": time.time()}, f)
    except OSError:
        pass


def reset() -> None:
    import os

    try:
        os.remove(get_flag_path())
    except OSError:
        pass


def denial_message() -> str:
    reason = get_reason()
    suffix = f" Reason: {reason}." if reason else ""
    return (
        "[kill_switch] Execution is halted - the kill switch is active."
        f"{suffix} A human must reset it from the UI before any code execution can resume."
    )
