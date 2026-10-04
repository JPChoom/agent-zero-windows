import asyncio
from datetime import datetime
import time
from helpers.task_scheduler import TaskScheduler
from helpers.print_style import PrintStyle
from helpers import errors
from helpers import runtime


SLEEP_TIME = 60

keep_running = True
pause_time = 0


async def run_loop():
    global pause_time, keep_running

    while True:
        # Signal the container's instance to pause its job loop while a
        # development instance runs, so jobs aren't run twice. Only when the
        # call actually crosses to that other instance: on native Windows
        # call_development_function runs pause_loop *locally* (there is no
        # container to delegate to), which used to pause this - the only -
        # instance on every pass, so scheduled tasks and job_loop extensions
        # never ran at all.
        if runtime.is_development() and not runtime.is_windows():
            try:
                await runtime.call_development_function(pause_loop)
            except Exception as e:
                PrintStyle().error("Failed to pause job loop by development instance: " + errors.error_text(e))
        if not keep_running and (time.time() - pause_time) > (SLEEP_TIME * 2):
            resume_loop()
        if keep_running:
            try:
                await scheduler_tick()
            except Exception as e:
                PrintStyle().error(errors.format_error(e))
        await asyncio.sleep(SLEEP_TIME)  # TODO! - if we lower it under 1min, it can run a 5min job multiple times in it's target minute


async def scheduler_tick():
    # Get the task scheduler instance and print detailed debug info
    scheduler = TaskScheduler.get()
    # Run the scheduler tick
    await scheduler.tick()

    # Run job_loop extensions (e.g. email polling)
    from helpers.extension import call_extensions_async
    await call_extensions_async("job_loop")


def pause_loop():
    global keep_running, pause_time
    keep_running = False
    pause_time = time.time()


def resume_loop():
    global keep_running, pause_time
    keep_running = True
    pause_time = 0
