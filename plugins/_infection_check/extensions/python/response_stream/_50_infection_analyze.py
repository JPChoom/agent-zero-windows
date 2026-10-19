from helpers import extract_tools
from helpers.extension import Extension
from agent import LoopData
from plugins._infection_check.helpers.checker import get_checker


class InfectionAnalyzeThoughts(Extension):
    async def execute(self, loop_data=LoopData(), text="", parsed={}, **kwargs):
        if not self.agent or not parsed:
            return
        checker = get_checker(self.agent)
        if checker.mode != "thoughts":
            return
        # Start the background check as soon as the tool call is complete,
        # so it judges the arguments too and the gate can use its verdict.
        # Starting earlier (on the heading) meant the gate had to cancel it
        # and start over - double the model time on every tool call.
        if parsed.get("tool_name") and extract_tools.extract_tool_request(text or "") is not None:
            checker.start_analysis(self.agent)
