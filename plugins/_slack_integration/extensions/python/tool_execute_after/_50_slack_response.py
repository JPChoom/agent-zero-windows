from helpers.extension import Extension
from helpers.tool import Response
from plugins._slack_integration.helpers import constants as C


class SlackResponseIntercept(Extension):
    """Capture `response` attachments, and send mid-task updates (break_loop false) right away."""

    async def execute(self, tool_name: str = "", response: Response | None = None, **kwargs):
        if not self.agent or tool_name != "response":
            return
        context = self.agent.context
        if not context.data.get(C.CTX_BOT):
            return
        tool = self.agent.loop_data.current_tool
        if not tool:
            return

        attachments = tool.args.get("attachments") or []
        if attachments:
            context.data[C.CTX_ATTACHMENTS] = list(attachments)

        if tool.args.get("break_loop", True) is False and response:
            from plugins._slack_integration.helpers import bot

            text = tool.args.get("text", tool.args.get("message", ""))
            error = await bot.send_reply(context, text, context.data.pop(C.CTX_ATTACHMENTS, []) or [])
            result = f"slack update failed: {error}" if error else "slack update sent, continue working"
            response.break_loop = False
            response.message = result
            self.agent.hist_add_tool_result("response", result)
