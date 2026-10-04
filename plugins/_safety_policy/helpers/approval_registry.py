"""In-memory registry of pending human approval decisions for approve-tier
safety_policy matches.

A plain module-level dict of asyncio.Future, not the sid-keyed,
loop.call_soon_threadsafe-based registry plugins/_a0_connector/helpers/
ws_runtime.py uses for remote-CLI coordination - that pattern solves a
different problem (cross-process/cross-socket signaling). Here, both the
tool-execution coroutine that awaits a future and the later HTTP request
that resolves it run on the same uvicorn/Starlette event loop within one
process (confirmed via api/pause.py, which mutates a plain context.paused
bool read by a busy-poll in agent.py's message loop - no cross-thread
signaling machinery exists or is needed anywhere in this app's request
handling), so a plain asyncio.Future set from another coroutine on the
same loop is sufficient.
"""

import asyncio

_pending: dict[str, "asyncio.Future[bool]"] = {}
_meta: dict[str, dict] = {}


def register(approval_id: str, meta: dict | None = None) -> "asyncio.Future[bool]":
    """Create and store a pending decision. Overwrites any existing entry
    for the same id (callers generate fresh uuids, so collisions aren't
    expected in practice, but this keeps register() itself total).

    `meta` is server-side context about the request (e.g. the download
    host an "always allow" click should remember). The resolving endpoint
    reads it with get_meta() instead of trusting a value sent back by the
    browser, so a client can only remember what was actually asked about."""
    future: "asyncio.Future[bool]" = asyncio.get_event_loop().create_future()
    _pending[approval_id] = future
    _meta[approval_id] = dict(meta or {})
    return future


def has_pending() -> bool:
    """True while any human decision is outstanding (safety policy,
    permissions, infection-check clarification all register here). Used by
    the job-loop stall watchdog: a chat waiting on the user is not stuck."""
    return any(not f.done() for f in list(_pending.values()))


def get_meta(approval_id: str) -> dict:
    """Metadata for a still-pending decision, or {} if unknown/resolved."""
    if approval_id not in _pending:
        return {}
    return dict(_meta.get(approval_id) or {})


def resolve(approval_id: str, approved: bool) -> bool:
    """Resolve a pending decision. Returns False (a no-op) if the id is
    unknown or already resolved - makes a duplicate/late POST (e.g. a
    second click, or a click after the wait already timed out and cleaned
    up) harmless rather than an error."""
    future = _pending.pop(approval_id, None)
    _meta.pop(approval_id, None)
    if future is None or future.done():
        return False
    future.set_result(approved)
    return True


def cleanup(approval_id: str) -> None:
    """Drop a pending entry without resolving it - used after a timeout so
    a stale future can't leak, and so a subsequent late resolve() call for
    the same id is a guaranteed no-op."""
    _pending.pop(approval_id, None)
    _meta.pop(approval_id, None)
