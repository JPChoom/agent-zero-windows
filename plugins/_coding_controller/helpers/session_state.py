"""Per-agent tracking of which project roots have unverified edits, and how
many automatic repair attempts each has used. Stored on agent.data (a plain
dict, same mechanism plugins/_text_editor/helpers/patch_state.py already
uses for stale-read tracking), so it lives for the lifetime of the Agent
object - the whole conversation, until reset.
"""

from plugins._coding_controller.helpers import project_detector

DIRTY_ROOTS_KEY = "_coding_controller_dirty_roots"  # dict[root, kind]
REPAIR_ATTEMPTS_KEY = "_coding_controller_repair_attempts"  # dict[root, count]
BASELINE_KEY = "_coding_controller_baseline"  # dict[root, dict[stage_name, frozenset]]


def mark_dirty_for_path(agent, path: str) -> None:
    info = project_detector.detect_project(path)
    if info is None:
        return
    dirty = agent.data.setdefault(DIRTY_ROOTS_KEY, {})
    dirty[info.root] = info.kind
    # Deliberately NOT resetting the repair-attempt counter here: a repair
    # attempt inherently involves editing the file again, so resetting on
    # every edit would make max_repair_attempts unenforceable (every
    # attempt would look like attempt #1). The counter only resets when the
    # gate actually passes, or the repair budget is exhausted and the
    # project is given up on - see clear_dirty().


def get_dirty_roots(agent) -> dict:
    return dict(agent.data.get(DIRTY_ROOTS_KEY, {}))


def clear_dirty(agent, root: str) -> None:
    """Stop tracking `root` as dirty and reset its repair-attempt counter.

    Called both when a gate check passes (successful fix, or nothing to
    verify) and when the repair budget is exhausted (giving up starts a
    fresh cycle if the project is edited again later)."""
    dirty = agent.data.get(DIRTY_ROOTS_KEY)
    if dirty:
        dirty.pop(root, None)
    attempts = agent.data.get(REPAIR_ATTEMPTS_KEY)
    if attempts:
        attempts.pop(root, None)


def get_repair_attempts(agent, root: str) -> int:
    return int(agent.data.get(REPAIR_ATTEMPTS_KEY, {}).get(root, 0))


def increment_repair_attempts(agent, root: str) -> int:
    attempts = agent.data.setdefault(REPAIR_ATTEMPTS_KEY, {})
    attempts[root] = attempts.get(root, 0) + 1
    return attempts[root]


def get_baseline(agent, root: str) -> dict | None:
    """Returns the stored baseline (dict[stage_name, frozenset[fingerprint]])
    for `root`, or None if no baseline has been captured yet - this
    project's failures, if any, haven't yet been distinguished as
    pre-existing vs. introduced by the agent."""
    return agent.data.get(BASELINE_KEY, {}).get(root)


def set_baseline(agent, root: str, baseline: dict) -> None:
    baselines = agent.data.setdefault(BASELINE_KEY, {})
    baselines[root] = baseline
