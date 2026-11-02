from helpers.extension import Extension, best_effort
from plugins._skills.helpers import task_watch


class SkillTaskStart(Extension):
    """Start tracking a task of the top agent (see helpers/task_watch.py)."""

    @best_effort("Track task for skill learning")
    async def execute(self, **kwargs):
        if self.agent:
            task_watch.start(self.agent)
