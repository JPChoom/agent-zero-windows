from helpers import perf, plugins
from helpers.extension import Extension
from helpers.print_style import PrintStyle


class PerfTurnEnd(Extension):
    async def execute(self, **kwargs):
        if not self.agent or getattr(self.agent, "number", 0) != 0:
            return
        record = perf.turn_end(str(self.agent.context.id))
        if record is None:
            return
        config = plugins.get_plugin_config("_perf", self.agent) or {}
        if config.get("print_summary", True):
            PrintStyle(font_color="#7fb3d5", padding=False).print(perf.format_turn(record))
