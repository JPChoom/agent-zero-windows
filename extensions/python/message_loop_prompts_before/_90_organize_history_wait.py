from helpers.extension import Extension
from agent import LoopData
from extensions.python.message_loop_end._10_organize_history import DATA_NAME_TASK
from helpers.defer import DeferredTask, THREAD_BACKGROUND

MAX_SYNC_COMPRESSION_PASSES = 64


class OrganizeHistoryWait(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        # sync action only required if the history is too large, otherwise leave it in background
        passes = 0
        while self.agent.history.is_over_limit():
            passes += 1
            before_tokens = self.agent.history.get_tokens()

            # get task
            task: DeferredTask | None = self.agent.get_data(DATA_NAME_TASK)

            # Check if the task is already done
            if task:
                already_done = task.is_ready()
                if not already_done:
                    self.agent.context.log.set_progress("Compressing history...")

                # Wait for the task to complete. A stalled provider call
                # inside compress() now raises TimeoutError (agent.py's
                # call_utility_model) instead of hanging this wait forever -
                # treat it the same as "compression made no progress" so the
                # turn continues with whatever history already fits, rather
                # than aborting prompt assembly for this extension point.
                try:
                    compressed = bool(await task.result())
                except Exception as e:
                    self.agent.set_data(DATA_NAME_TASK, None)
                    self._log_compression_stalled(
                        before_tokens, self.agent.history.get_tokens(), error=e
                    )
                    break

                # Clear the coroutine data after it's done
                self.agent.set_data(DATA_NAME_TASK, None)

                if already_done:
                    # The task finished before this loop even started, so its
                    # reduction is already inside before_tokens. Scoring this
                    # pass by it compares history against itself, reads as "no
                    # progress" and abandons compression on the very first
                    # pass - leaving history over budget and the prompt
                    # oversized. Consume it and re-evaluate instead; the next
                    # pass finds no task and compresses synchronously, which
                    # can be measured honestly.
                    if passes < MAX_SYNC_COMPRESSION_PASSES:
                        continue
                    self._log_compression_stalled(
                        before_tokens,
                        self.agent.history.get_tokens(),
                        max_passes=True,
                    )
                    break
            else:
                # no task was running, start and wait
                self.agent.context.log.set_progress("Compressing history...")
                try:
                    compressed = await self.agent.history.compress()
                except Exception as e:
                    self._log_compression_stalled(
                        before_tokens, self.agent.history.get_tokens(), error=e
                    )
                    break

            after_tokens = self.agent.history.get_tokens()
            if not compressed or after_tokens >= before_tokens:
                self._log_compression_stalled(before_tokens, after_tokens)
                break

            if passes >= MAX_SYNC_COMPRESSION_PASSES:
                self._log_compression_stalled(
                    before_tokens, after_tokens, max_passes=True
                )
                break

    def _log_compression_stalled(
        self,
        before_tokens: int,
        after_tokens: int,
        max_passes: bool = False,
        error: Exception | None = None,
    ) -> None:
        if not self.agent:
            return

        if error is not None:
            detail = f"History compression failed: {error}"
        elif max_passes:
            detail = f"History compression stopped after {MAX_SYNC_COMPRESSION_PASSES} passes"
        else:
            detail = "History compression could not reduce the prompt history further"
        self.agent.context.log.log(
            type="warning",
            heading="History compression stalled",
            content=f"{detail}. Tokens before: {before_tokens}; after: {after_tokens}.",
        )
