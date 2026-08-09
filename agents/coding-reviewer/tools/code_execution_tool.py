"""Reviewer-profile override of code_execution_tool: always denied.

Shadows plugins/_code_execution/tools/code_execution_tool.py for the
coding-reviewer profile only (see text_editor.py in this same directory
for how profile-scoped tool shadowing works). Matches the hand-off doc's
reviewer permission list: denied apply_patch/write_file/delete_file/
arbitrary_terminal_write/git_commit/git_push - the reviewer inspects code
and evidence, it never runs anything.
"""

from helpers.tool import Tool, Response


class CodeExecution(Tool):

    async def execute(self, **kwargs):
        return Response(
            message=(
                "The reviewer role cannot execute code or run terminal commands. "
                "It may only read files, search code, and inspect the diff, "
                "validation results, and project instructions."
            ),
            break_loop=False,
        )
