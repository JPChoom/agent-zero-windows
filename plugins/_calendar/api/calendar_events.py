import traceback
from datetime import timezone, timedelta

import pytz
from crontab import CronTab

from helpers.api import ApiHandler, Input, Output, Request
from helpers.print_style import PrintStyle
from helpers.localization import Localization
from helpers.task_scheduler import (
    TaskScheduler,
    ScheduledTask,
    PlannedTask,
    normalize_schedule_timezone,
    parse_datetime,
    serialize_datetime,
)

# Hard cap on cron occurrences expanded per task per request, so a
# pathological cron expression (or a huge requested range) can't spin the
# server - callers only ever request one visible calendar grid at a time.
MAX_OCCURRENCES_PER_TASK = 500


class CalendarEvents(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        try:
            if timezone := input.get("timezone", None):
                Localization.get().set_timezone(timezone)

            range_start = parse_datetime(input.get("start"))
            range_end = parse_datetime(input.get("end"))
            if range_start is None or range_end is None:
                return {"ok": False, "error": "start and end are required ISO datetimes", "events": []}
            if range_end <= range_start:
                return {"ok": False, "error": "end must be after start", "events": []}

            scheduler = TaskScheduler.get()
            await scheduler.reload()
            tasks = scheduler.get_tasks()

            events = []
            for task in tasks:
                if isinstance(task, ScheduledTask):
                    events.extend(self._expand_scheduled(task, range_start, range_end))
                elif isinstance(task, PlannedTask):
                    events.extend(self._expand_planned(task, range_start, range_end))

            return {"ok": True, "events": events}

        except Exception as e:
            PrintStyle.error(f"Failed to build calendar events: {str(e)} {traceback.format_exc()}")
            return {"ok": False, "error": f"Failed to build calendar events: {str(e)}", "events": []}

    def _expand_scheduled(self, task: ScheduledTask, range_start, range_end) -> list[dict]:
        try:
            crontab = CronTab(crontab=task.schedule.to_crontab())
        except Exception:
            return []

        # Cron occurrences must be evaluated in the task's own schedule
        # timezone (same as ScheduledTask.get_next_run/check_schedule) -
        # not the viewer's timezone, since the two can differ.
        task.schedule.timezone = normalize_schedule_timezone(task.schedule.timezone)
        task_timezone = pytz.timezone(task.schedule.timezone)
        cursor = (range_start - timedelta(seconds=1)).astimezone(task_timezone)
        range_end_in_task_timezone = range_end.astimezone(task_timezone)

        events = []
        for _ in range(MAX_OCCURRENCES_PER_TASK):
            occurrence = crontab.next(now=cursor, return_datetime=True)
            if occurrence is None:
                break
            if occurrence.tzinfo is None:
                occurrence = task_timezone.localize(occurrence)
            if occurrence >= range_end_in_task_timezone:
                break
            events.append({
                "id": f"{task.uuid}:{occurrence.isoformat()}",
                "task_uuid": task.uuid,
                "task_type": "scheduled",
                "name": task.name,
                "start": serialize_datetime(occurrence.astimezone(timezone.utc)),
                "state": task.state.value if hasattr(task.state, "value") else str(task.state),
                "status": "occurrence",
                "project_name": task.project_name,
                "project_color": task.project_color,
            })
            cursor = occurrence
        return events

    def _expand_planned(self, task: PlannedTask, range_start, range_end) -> list[dict]:
        events = []
        for launch_time, status in self._planned_launch_times(task):
            if launch_time is None:
                continue
            if launch_time < range_start or launch_time >= range_end:
                continue
            events.append({
                "id": f"{task.uuid}:{launch_time.isoformat()}:{status}",
                "task_uuid": task.uuid,
                "task_type": "planned",
                "name": task.name,
                "start": serialize_datetime(launch_time),
                "state": task.state.value if hasattr(task.state, "value") else str(task.state),
                "status": status,
                "project_name": task.project_name,
                "project_color": task.project_color,
            })
        return events

    def _planned_launch_times(self, task: PlannedTask):
        for launch_time in task.plan.todo:
            yield launch_time, "todo"
        if task.plan.in_progress is not None:
            yield task.plan.in_progress, "in_progress"
        for launch_time in task.plan.done:
            yield launch_time, "done"
