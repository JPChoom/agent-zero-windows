from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData
from helpers.localization import Localization
from helpers.errors import RepairableException
from helpers import errors
from helpers.print_style import PrintStyle

DATA_NAME_COUNTER = "_plugin.error_retry.critical_exception_counter"
DATA_NAME_OVERFLOW_COUNTER = "_plugin.error_retry.context_overflow_counter"

class ResetCriticalExceptionCounter(Extension):
    async def execute(self, exception_data: dict = {}, **kwargs):
        if not self.agent:
            return
        
        self.agent.set_data(DATA_NAME_COUNTER, 0)
        self.agent.set_data(DATA_NAME_OVERFLOW_COUNTER, 0)
        # A context overflow made this chat work with a smaller window
        # (helpers/prompt_budget). Give 2% back per turn, so one bad turn
        # does not squeeze a long chat for the rest of the session.
        from helpers import prompt_budget

        factor = prompt_budget.overflow_factor(self.agent)
        if factor < 1.0:
            self.agent.set_data(prompt_budget.OVERFLOW_FACTOR_KEY, min(1.0, factor + 0.02))

        