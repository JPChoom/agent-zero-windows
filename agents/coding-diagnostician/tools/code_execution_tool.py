"""Diagnostician-profile override of code_execution_tool: always denied.

Shadows plugins/_code_execution/tools/code_execution_tool.py for the
coding-diagnostician profile only (see text_editor.py in this same
directory for how profile-scoped tool shadowing works). The diagnostician
investigates why repair attempts failed by reading code and evidence; it
never runs anything, same restriction as agents/coding-reviewer/tools/
code_execution_tool.py.
"""

from helpers.tool import Tool, Response


class CodeExecution(Tool):

    async def execute(self, **kwargs):
        return Response(
            message=(
                "The diagnostician role cannot execute code or run terminal commands. "
                "It may only read files, search code, and inspect the diff, failure "
                "output, and repair attempt history."
            ),
            break_loop=False,
        )
