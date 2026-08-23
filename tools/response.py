from helpers.tool import Tool, Response


class ResponseTool(Tool):

    async def execute(self, **kwargs):
        # A local/weaker model can occasionally emit a response tool call
        # missing both "text" and "message" (malformed tool-call JSON) -
        # fall back to "" instead of a raw KeyError crashing the turn.
        message = self.args.get("text")
        if message is None:
            message = self.args.get("message", "")
        return Response(message=message, break_loop=True)

    async def before_execution(self, **kwargs):
        # self.log = self.agent.context.log.log(type="response", heading=f"{self.agent.agent_name}: Responding", content=self.args.get("text", ""))
        # don't log here anymore, we have the live_response extension now
        pass

    async def after_execution(self, response, **kwargs):
        # do not add anything to the history or output

        if self.loop_data and "log_item_response" in self.loop_data.params_temporary:
            log = self.loop_data.params_temporary["log_item_response"]
            log.update(finished=True) # mark the message as finished
