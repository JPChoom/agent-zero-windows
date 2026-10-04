"""Missed-run catch-up for ScheduledTask.check_schedule().

Before this, a ScheduledTask that missed its cron occurrence (server off,
machine asleep) silently skipped to the next future occurrence - there was
no way to have it fire once for what it missed. These tests pin the new
behavior: catch-up on by default, and a setting to turn it back off to the
old skip-only behavior.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import task_scheduler
from helpers.task_scheduler import ScheduledTask, SchedulerSettings, TaskSchedule


def _fake_localization(fixed_now: datetime):
    """_now() (and _localize_task_datetime) go through Localization.get(),
    not a module-level datetime.now() call - patching task_scheduler.datetime
    alone (as the timezone tests do for get_next_run()) does not affect
    check_schedule()."""

    def localize_naive(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    loc = SimpleNamespace(
        now=lambda: fixed_now,
        get_timezone=lambda: "UTC",
        localize_naive_datetime=localize_naive,
    )
    return SimpleNamespace(get=lambda: loc)


def _hourly_task(monkeypatch, now: datetime, last_run=None):
    # created_at defaults to _now() at construction time, which would
    # otherwise coincide with the test's frozen "now" (created via the
    # same frozen clock) and get picked up as the fallback baseline below -
    # an artifact of building the fixture under a frozen clock, not
    # something that happens in practice. Pin it safely in the past so
    # last_run=None tests exercise "never run before", not "just created".
    monkeypatch.setattr(task_scheduler, "Localization", _fake_localization(now))
    task = ScheduledTask.create(
        name="hourly check",
        system_prompt="",
        prompt="check",
        schedule=TaskSchedule(minute="0", hour="*", day="*", month="*", weekday="*", timezone="UTC"),
        timezone="UTC",
    )
    task.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    task.last_run = last_run
    return task


def test_missed_occurrence_fires_once_when_catchup_enabled(monkeypatch):
    monkeypatch.setattr(task_scheduler, "get_scheduler_settings", lambda: SchedulerSettings(catch_up_missed_runs=True))

    now = datetime(2026, 5, 9, 12, 30, tzinfo=timezone.utc)
    task = _hourly_task(monkeypatch, now, last_run=now - timedelta(hours=3, minutes=30))

    assert task.check_schedule() is True


def test_missed_occurrence_skipped_when_catchup_disabled(monkeypatch):
    monkeypatch.setattr(task_scheduler, "get_scheduler_settings", lambda: SchedulerSettings(catch_up_missed_runs=False))

    now = datetime(2026, 5, 9, 12, 30, tzinfo=timezone.utc)
    task = _hourly_task(monkeypatch, now, last_run=now - timedelta(hours=3, minutes=30))

    assert task.check_schedule() is False


def test_normal_occurrence_within_tick_window_still_fires_regardless_of_setting(monkeypatch):
    monkeypatch.setattr(task_scheduler, "get_scheduler_settings", lambda: SchedulerSettings(catch_up_missed_runs=False))

    # "now" is exactly on the hourly occurrence and the task has never run
    # before - this is the ordinary, non-catch-up case and must keep
    # working the same whether catch-up is on or off.
    now = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    task = _hourly_task(monkeypatch, now, last_run=None)

    assert task.check_schedule() is True


def test_already_ran_for_current_occurrence_does_not_fire_again(monkeypatch):
    monkeypatch.setattr(task_scheduler, "get_scheduler_settings", lambda: SchedulerSettings(catch_up_missed_runs=True))

    # last_run already equals the most recent occurrence - must not
    # re-fire for the same occurrence just because catch-up is on.
    now = datetime(2026, 5, 9, 12, 0, 30, tzinfo=timezone.utc)
    task = _hourly_task(monkeypatch, now, last_run=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc))

    assert task.check_schedule() is False
