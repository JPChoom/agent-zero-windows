from helpers.defer import DeferredTask, THREAD_BACKGROUND
from helpers.extension import Extension, best_effort
from plugins._skills.helpers import auto_learn, learned, task_watch


class LearnSkillFromTask(Extension):
    """End the task: record learned-skill uses, and learn a skill on its own
    from a long successful task (helpers/auto_learn.py, in the background)."""

    @best_effort("Learn a skill from the task")
    async def execute(self, **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        current = task_watch.current(self.agent)
        task = task_watch.finish(self.agent, ok=bool(current and current.get("answered")))
        if not task:
            return
        if task["ok"]:
            for name in task.get("used_skills", []):
                learned.record_use(name, task["seconds"], task["steps"])
        cfg = auto_learn.settings(self.agent)
        if not cfg["enabled"] or auto_learn.worth_trying(task, cfg):
            return
        DeferredTask(thread_name=THREAD_BACKGROUND).start_task(auto_learn.learn_from_task, self.agent, task)
