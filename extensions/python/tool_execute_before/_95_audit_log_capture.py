"""Stashes the tool_name/tool_args a write-capable tool is about to run
with, so the paired tool_execute_after/_95_audit_log.py hook can build a
full audit record - tool_execute_after only receives the response, not
the original arguments (see agent.py's monologue loop), so the two hooks
correlate via a small LIFO stack on agent.data.

Safe as a plain stack (not a token/ID-matched structure) because a single
Agent's own tool-call sequence is always strictly serial - before is
always immediately followed by after for that same call before the next
tool call starts (agent.py awaits each in turn). Parallel tool calls
(helpers/parallel_tools.py) run on their own freshly-created worker Agent
instances with independent .data dicts, not concurrently on this same
agent - see that module's _run_direct_tool_job.
"""

from helpers.extension import Extension

_STACK_KEY = "_audit_log_pending"


class AuditLogCapture(Extension):
    # Preserving pre-isolation behavior deliberately: whether a broken
    # audit trail should ever be allowed to silently continue (vs. abort
    # the tool call) is a policy call, not an engineering one - left as
    # fail-loud, matching how it already behaved before isolation became
    # the dispatcher's default, rather than deciding this unilaterally.
    FAIL_LOUD = True

    async def execute(self, tool_args: dict | None = None, tool_name: str = "", **kwargs):
        if not self.agent:
            return
        stack = self.agent.data.setdefault(_STACK_KEY, [])
        stack.append({"tool_name": tool_name, "tool_args": dict(tool_args or {})})
