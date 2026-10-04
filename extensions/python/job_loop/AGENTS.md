# Job Loop Extensions DOX

## Purpose

- Own periodic backend maintenance jobs.

## Ownership

- Ordered Python files own cleanup of expired API chats (`_20_`), the stall watchdog (`_30_`), cache trimming (`_50_`), and future job-loop tasks.

## Local Contracts

- Jobs must be idempotent and safe to run repeatedly.
- Keep cleanup scoped to owned caches, temporary contexts, or documented runtime state.
- The job loop fires every 60s (`helpers/job_loop.py`); jobs needing a longer interval track their own timestamps.
- `_30_stall_watchdog.py` auto-nudges a running, unpaused chat whose log update counter (`len(context.log.updates)`) has not moved for `STALL_SECONDS` (600s), capped at `MAX_NUDGES_PER_WINDOW` (4) per `NUDGE_WINDOW_SECONDS` (2h) per chat, then raises one persistent "Agent stuck" notification. It never nudges while `approval_registry.has_pending()` (an Allow/Deny decision is outstanding anywhere), restarting the stall window instead. `STALL_SECONDS` must stay above the longest other legitimate silent wait (model stream-idle timeout, code-execution no-output return); raise it if either is raised. State is in-memory and resets on restart.

## Work Guidance

- Avoid expensive work on every loop; use timestamps or thresholds when practical.

## Verification

- Run targeted cleanup/cache tests or smoke-test job-loop startup after changes.

## Child DOX Index

No child DOX files.
