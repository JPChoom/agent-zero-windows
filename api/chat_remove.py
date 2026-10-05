from helpers.api import ApiHandler, Input, Output, Request, Response
from agent import AgentContext
from helpers import chat_trash, files, persist_chat
from helpers.task_scheduler import TaskScheduler


class RemoveChat(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        ctxid = input.get("context", "")

        scheduler = TaskScheduler.get()
        scheduler.cancel_tasks_by_context(ctxid, terminate_thread=True)

        context = AgentContext.use(ctxid)

        # Move the saved chat to the trash first (restorable for
        # chat_trash.RETENTION_DAYS), before reset() clears its state.
        trash_id = chat_trash.trash_chat(ctxid, context)

        if context:
            # stop processing any tasks
            context.reset()

        AgentContext.remove(ctxid)
        if trash_id:
            # The trash holds the copy (and its provider-stored responses
            # until purge); just clear anything re-saved during the reset.
            files.delete_dir(persist_chat.get_chat_folder_path(ctxid))
        else:
            persist_chat.remove_chat(ctxid)

        await scheduler.reload()

        tasks = scheduler.get_tasks_by_context_id(ctxid)
        for task in tasks:
            await scheduler.remove_task_by_uuid(task.uuid)

        # Context removal affects global chat/task lists in all tabs.
        from helpers.state_monitor_integration import mark_dirty_all
        mark_dirty_all(reason="api.chat_remove.RemoveChat")

        return {
            "message": "Context removed.",
            "trash_id": trash_id,
        }
