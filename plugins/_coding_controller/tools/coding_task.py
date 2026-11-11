import json

from helpers.errors import RepairableException
from helpers.tool import Response, Tool
from plugins._coding_controller.helpers import task_worktrees


class CodingTask(Tool):
    """A git worktree per coding task (helpers/task_worktrees.py)."""

    async def execute(self, action: str = "", name: str = "", repo: str = "", base: str = "", message: str = "",
                      keep: bool = False, child: str = "", **kwargs):
        action = str(action or self.method or "list").strip().lower()
        context = self.agent.context
        if child:  # review, commit, merge or discard the worktree of one of this chat's child agents
            from helpers import child_agents

            try:
                found = child_agents.find(context, child_agents.normalize_name(child))
            except child_agents.ChildAgentError as exc:
                raise RepairableException(str(exc)) from exc
            if found is None:
                raise RepairableException(f"No child agent called '{child}' in this chat.")
            context = found
            if action == "start":
                raise RepairableException("A child's worktree is made by child_agent (its repo argument), not here.")
            name = name or child
        try:
            if action == "start":
                outcome = await task_worktrees.start(context, repo, name, base)
            elif action == "diff":
                outcome = await task_worktrees.diff(context, name)
            elif action == "commit":
                outcome = await task_worktrees.commit(context, name, message)
            elif action == "merge":
                outcome = await task_worktrees.merge(context, name, keep=str(keep).lower() in ("true", "1", "yes"))
            elif action == "discard":
                outcome = await task_worktrees.discard(context, name)
            elif action in ("list", "status"):
                outcome = {"tasks": task_worktrees.describe(context)}
            else:
                raise task_worktrees.TaskError("action must be start, diff, commit, merge, discard or list.")
        except task_worktrees.TaskError as exc:
            raise RepairableException(str(exc)) from exc
        try:
            from helpers import persist_chat

            persist_chat.save_tmp_chat(context)
        except Exception:
            pass
        return Response(message=json.dumps(outcome, indent=2, ensure_ascii=False), break_loop=False)
