from agent import LoopData
from helpers import chat_channels
from helpers.extension import Extension
from helpers.print_style import PrintStyle
from plugins._slack_integration.helpers import constants as C


class SlackReply(Extension):
    """Send agent 0's final response back to the Slack conversation."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        context = self.agent.context
        if not context.data.get(C.CTX_BOT):
            return

        from plugins._slack_integration.helpers import bot

        text = chat_channels.last_response(context)
        attachments = context.data.pop(C.CTX_ATTACHMENTS, []) or []
        if not text and not attachments:
            return
        from helpers import channel_delivery

        delivery = await channel_delivery.deliver(context, text, attachments, send=bot.send_reply)
        error = "" if delivery.queued else delivery.error  # a queued reply is retried automatically
        if error:
            PrintStyle.error(f"Slack reply failed: {error}")
            context.log.log(type="error", heading="Slack reply was not delivered", content=error)
