from datetime import datetime, timezone
from types import SimpleNamespace

import pytz

from plugins._calendar.api.calendar_events import CalendarEvents


def _daily_6am(tz_name):
    schedule = SimpleNamespace(to_crontab=lambda: "0 6 * * *", timezone=tz_name)
    return SimpleNamespace(
        schedule=schedule, uuid="t", name="Daily", state="idle",
        project_name=None, project_color=None,
    )


def test_daily_6am_stays_6am_across_both_clock_changes():
    handler = CalendarEvents.__new__(CalendarEvents)
    events = handler._expand_scheduled(
        _daily_6am("America/New_York"),
        datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2027, 5, 1, tzinfo=timezone.utc),
    )
    zone = pytz.timezone("America/New_York")
    local = [datetime.fromisoformat(e["start"]).astimezone(zone) for e in events]
    assert len(local) == 212
    assert {(d.hour, d.minute) for d in local} == {(6, 0)}
