# _calendar Plugin DOX

## Purpose

- Calendar right-canvas surface for viewing and creating scheduled, planned, and ad-hoc tasks.

## Ownership

- `api/calendar_events.py` owns the event/occurrence listing over the task scheduler.
- `webui/` owns the calendar panel, store, and modal entry; `extensions/webui/` registers the right-canvas surface and panel.

## Local Contracts

- Colors follow the user's accent through `--calendar-primary` (falls back to `--color-primary` outside the theme).
- Occurrence expansion must stay bounded so a pathological cron expression or huge range cannot spin the server.

- Cron occurrences are expanded in the task's schedule timezone and re-pinned with `cron_wall_time` on every step, so a daily 6 am task stays 6 am across daylight-saving changes.

## Work Guidance

## Verification

- Smoke-test month/week/day views, Today, and creating a task from the panel.

## Child DOX Index

No child DOX files.
