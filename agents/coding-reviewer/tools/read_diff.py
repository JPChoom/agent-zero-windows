"""Reviewer-only tool: read the current git diff/status for the active
project. One of the hand-off doc's explicitly allowed reviewer tools
(read_diff), backed by plugins/_coding_controller/helpers/git_state.py -
the same helper the review-packet builder uses to assemble the initial
packet, exposed here so the reviewer can re-check or narrow to one file
during its own investigation.
"""

from helpers.tool import Tool, Response
from plugins._coding_controller.helpers import git_state


class ReadDiff(Tool):

    async def execute(self, project_root: str = "", path: str = "", **kwargs):
        if not project_root:
            return Response(message="project_root is required", break_loop=False)

        if not await git_state.is_git_repo(project_root):
            return Response(
                message=f"'{project_root}' is not a git repository (or git is unavailable) - no diff to show.",
                break_loop=False,
            )

        diff = await git_state.get_git_diff(project_root, path=path or None)
        status = await git_state.get_git_status(project_root)

        if not diff and not status:
            return Response(message="No working-tree changes.", break_loop=False)

        parts = []
        if status:
            parts.append(f"git status --short:\n{status}")
        if diff:
            parts.append(f"git diff{' -- ' + path if path else ''}:\n{diff}")
        return Response(message="\n\n".join(parts), break_loop=False)
