"""Repair-attempt checkpointing + worsening-detection rollback.

Before asking the agent to try another repair attempt, the completion
gate (_80_completion_gate.py) snapshots the current state of every
changed file under the project root plus the gate's failure-fingerprint
set at that moment. The next time the gate re-checks that root (after the
attempt), it compares the new fingerprint set against the snapshot: if
the attempt made things strictly worse (more failures, or a previously
passing stage now failing), the snapshotted file contents are restored
before continuing - so a bad repair attempt can't become the foundation
the next attempt has to dig out of.

Git-based file discovery rather than a bespoke dirty-file-tracking
scheme: this repo already uses git_state.py as the source of truth for
"what changed" (the same information the reviewer/diagnostician packets
use), so reusing it here avoids a second, parallel tracking mechanism.
Checkpointing is a no-op - and worsening is never reported - for a
project that isn't a git repo, same graceful-degradation posture as
git_state.py itself: a project without git just doesn't get rollback
protection, it isn't blocked from repair attempts.
"""

from dataclasses import dataclass, field
from pathlib import Path

from plugins._coding_controller.helpers import git_state


@dataclass
class Checkpoint:
    root: str
    is_git_repo: bool
    fingerprint: dict
    # path (relative to root) -> file bytes at snapshot time, or None if
    # the file did not exist yet at snapshot time (a later attempt
    # creating it should be undone by deleting it, not by writing empty
    # content).
    file_snapshots: dict = field(default_factory=dict)


async def save_checkpoint(root: str, fingerprint: dict) -> Checkpoint:
    if not await git_state.is_git_repo(root):
        return Checkpoint(root=root, is_git_repo=False, fingerprint=fingerprint)

    changed = await git_state.get_changed_files(root)
    snapshots: dict[str, bytes | None] = {}
    for rel_path in changed:
        abs_path = _resolve(root, rel_path)
        if abs_path is None:
            continue
        if abs_path.is_file():
            try:
                snapshots[rel_path] = abs_path.read_bytes()
            except OSError:
                continue
        else:
            snapshots[rel_path] = None
    return Checkpoint(root=root, is_git_repo=True, fingerprint=fingerprint, file_snapshots=snapshots)


def is_worse(current_fingerprint: dict, checkpoint_fingerprint: dict) -> bool:
    """A stage that was passing (absent from the fingerprint - only
    failing stages are fingerprinted, see _fingerprint_result) and is now
    failing counts as worse, regardless of finding counts elsewhere.
    Otherwise, worse means strictly more total findings than before."""
    for stage_name in current_fingerprint:
        if stage_name not in checkpoint_fingerprint:
            return True
    current_total = sum(len(findings) for findings in current_fingerprint.values())
    checkpoint_total = sum(len(findings) for findings in checkpoint_fingerprint.values())
    return current_total > checkpoint_total


async def restore_checkpoint(checkpoint: Checkpoint) -> None:
    if not checkpoint.is_git_repo:
        return

    for rel_path, content in checkpoint.file_snapshots.items():
        abs_path = _resolve(checkpoint.root, rel_path)
        if abs_path is None:
            continue
        try:
            if content is None:
                abs_path.unlink(missing_ok=True)
            else:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(content)
        except OSError:
            continue

    # Anything changed right now that wasn't part of the snapshot at all
    # was created fresh during the reverted attempt - remove it too.
    current = await git_state.get_changed_files(checkpoint.root)
    for rel_path in current:
        if rel_path in checkpoint.file_snapshots:
            continue
        abs_path = _resolve(checkpoint.root, rel_path)
        if abs_path is None:
            continue
        try:
            abs_path.unlink(missing_ok=True)
        except OSError:
            continue


def _resolve(root: str, rel_path: str) -> Path | None:
    try:
        base = Path(root).resolve()
        resolved = (base / rel_path).resolve()
    except (OSError, ValueError):
        return None
    # Refuse to touch anything outside the project root - a malformed or
    # adversarial relative path (e.g. containing "..") must not let a
    # rollback write/delete files elsewhere on disk.
    if base not in resolved.parents and resolved != base:
        return None
    return resolved
