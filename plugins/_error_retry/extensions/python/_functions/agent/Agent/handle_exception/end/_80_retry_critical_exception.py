import asyncio
from datetime import datetime, timezone
import litellm
from helpers.extension import Extension
from agent import LoopData
from helpers.localization import Localization
from helpers.errors import RepairableException, HandledException
from helpers import errors, plugins
from helpers.print_style import PrintStyle

from plugins._error_retry.extensions.python._functions.agent.Agent.monologue.start._10_reset_critical_exception_counter import (
    DATA_NAME_COUNTER,
    DATA_NAME_OVERFLOW_COUNTER,
)

# Context-window overflows are retried separately from other errors, after
# the prompt has been made smaller; a plain retry would only fail again.
MAX_OVERFLOW_RETRIES = 2

DEFAULT_MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 3


def normalize_max_retries(value, default: int = DEFAULT_MAX_RETRIES) -> int:
    if value is None or isinstance(value, bool):
        return default

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class RetryCriticalException(Extension):
    # This hook exists to handle an exception - catching a failure inside
    # it would mask why the real handling didn't occur, and risks a
    # confusing double-fault instead of a clear one.
    FAIL_LOUD = True

    async def execute(self, data: dict = {}, **kwargs):
        if not self.agent:
            return

        exception = data.get("exception")
        if not exception:
            self.agent.set_data(DATA_NAME_COUNTER, 0) # reset counter if exception has been handled
            return

        if isinstance(exception, (HandledException, RepairableException)):
            self.agent.set_data(DATA_NAME_COUNTER, 0) # reset counter if exception has been handled
            return

        if await self._recover_from_overflow(data, exception):
            return

        cfg = plugins.get_plugin_config("_error_retry", agent=self.agent) or {}
        max_retries = normalize_max_retries(cfg.get("retries"))

        counter = self.agent.get_data(DATA_NAME_COUNTER) or 0
        if counter >= max_retries:
            self.when_critical(data)
            return

        self.agent.set_data(DATA_NAME_COUNTER, counter + 1)

        error_message = errors.format_error(exception)
        import uuid as _uuid
        msg_id = str(_uuid.uuid4())
        self.agent.context.log.log(
            type="warning",
            heading="Critical error occurred, retrying...",
            content=error_message,
            id=msg_id,
        )
        PrintStyle(font_color="orange", padding=True).print(
            "Critical error occurred, retrying..."
        )
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        await self.agent.handle_intervention()
        agent_facing_error = self.agent.read_prompt(
            "fw.msg_critical_error.md", error_message=error_message
        )
        self.agent.hist_add_warning(message=agent_facing_error, id=msg_id)
        PrintStyle(font_color="orange", padding=True).print(agent_facing_error)

        data["exception"] = None


    async def _recover_from_overflow(self, data: dict, exception) -> bool:
        """The provider refused the prompt as too long (or ran out of room
        mid-reply). Make the prompt smaller and retry, instead of failing
        and putting the long error text into history, which made the next
        prompt even bigger."""
        from helpers import prompt_budget

        if not prompt_budget.is_context_overflow(exception):
            return False
        count = int(self.agent.get_data(DATA_NAME_OVERFLOW_COUNTER) or 0)
        if count >= MAX_OVERFLOW_RETRIES:
            return False
        self.agent.set_data(DATA_NAME_OVERFLOW_COUNTER, count + 1)

        factor = prompt_budget.shrink_after_overflow(self.agent)
        try:
            await self.agent.history.compress()
        except Exception as exc:
            PrintStyle.error(f"History compression after a context overflow failed: {exc}")
        self.agent.context.log.log(
            type="warning",
            heading="Prompt did not fit the context window - retrying with less context",
            content=(f"This chat now uses {int(factor * 100)}% of the configured window. "
                     "Older history is summarised more and extras are trimmed when needed."),
        )
        self.agent.hist_add_warning(
            message="The previous reply was cut off: the prompt did not fit the model's context window. "
                    "Context has been reduced. Continue where you left off; keep tool output short."
        )
        data["exception"] = None
        return True

    def when_critical(self, data: dict = {}):
        if not self.agent:
            return

        self.try_clear_embeds(data)

    def try_clear_embeds(self, data: dict = {}):
        """Try to clear embeds before failing on LiteLLM errors"""
        
        if not self.agent:
            return

        exc = data.get("exception")
        if not isinstance(exc, litellm.exceptions.BadRequestError):
            return

        cfg = plugins.get_plugin_config("_error_retry", agent=self.agent) or {}
        if not cfg.get("try_clear_embeds", False):
            return

        removed = self.agent.history.remove_all_embeds()
        if removed <= 0:
            return

        data["exception"] = None
        self.agent.context.log.log(
            type="warning",
            heading="Cleared embedded media from history",
            content=f"Persistent LiteLLM bad request detected. Removed {removed} embedded media messages from history to help recover.",
        )
        PrintStyle(font_color="orange", padding=True).print(
            f"Cleared {removed} embedded media messages from history after persistent LiteLLM bad request."
        )
