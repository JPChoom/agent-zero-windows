from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData
from helpers.localization import Localization
from helpers.errors import InterventionException
from helpers import errors
from helpers.print_style import PrintStyle


class HandleInterventionException(Extension):
    # This hook exists to handle an exception - catching a failure inside
    # it would mask why the real handling didn't occur, and risks a
    # confusing double-fault instead of a clear one.
    FAIL_LOUD = True

    async def execute(self, data: dict = {}, **kwargs):
        if not self.agent:
            return

        if not data.get("exception"):
            return

        if isinstance(data["exception"], InterventionException):
            data["exception"] = None # skip the exception and continue message loop

        
