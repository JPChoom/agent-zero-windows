from helpers.extension import Extension


class PerfAgentName(Extension):
    """Tell the perf record which agent makes this main-model call.

    A0 and its subordinates share one chat id; helpers/perf.prompt_reuse
    compares each agent's prompt with that same agent's previous one. Each
    call builds a fresh model object, so the name applies to this call only.
    """

    async def execute(self, call_data: dict | None = None, **kwargs):
        model = (call_data or {}).get("model")
        if self.agent and model is not None:
            try:
                model.a0_perf_agent = self.agent.agent_name
            except Exception:
                pass
