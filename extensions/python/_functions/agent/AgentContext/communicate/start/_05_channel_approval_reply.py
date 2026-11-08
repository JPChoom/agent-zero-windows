"""A phone reply such as `yes 7KQ2` answers a pending approval question
(helpers/channel_approvals.py) instead of reaching the agent."""

import asyncio

from helpers.extension import Extension


class ChannelApprovalReply(Extension):
    def execute(self, data: dict = {}, **kwargs):
        try:
            from helpers import channel_approvals

            args = data.get("args", ())
            if not isinstance(args, tuple) or len(args) < 2:
                return
            context, message = args[0], args[1]
            confirmation = channel_approvals.try_answer(context, message)
            if confirmation is None:
                return
            data["result"] = context.task  # handled: the agent never sees it
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(channel_approvals.send(context, confirmation))
                channel_approvals._tasks.add(task)
                task.add_done_callback(channel_approvals._tasks.discard)
            except RuntimeError:
                pass  # no loop here: the answer still counts
        except Exception:
            return  # a normal message then
