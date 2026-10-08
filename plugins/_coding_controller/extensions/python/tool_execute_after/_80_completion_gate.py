"""Blocks a false "done" response until quality gates pass, with a bounded
automatic repair loop.

Fires on tool_execute_after for the "response" tool - the one tool that
ever sets Response.break_loop=True (see tools/response.py), i.e. the single
point where the agent's turn actually ends. Raising RepairableException
here prevents that from happening: monologue()'s exception handler
(extensions/python/_functions/agent/Agent/handle_exception/end/
_50_handle_repairable_exception.py) turns it into a warning fed back into
the agent's own history and the loop continues - no core agent.py change
needed.

Only blocks on NEW failures, not pre-existing ones (baseline tracking): the
first time a project is seen failing, that failure set becomes its
baseline rather than being blocked on - the agent shouldn't be trapped
trying to fix problems it wasn't asked to fix and didn't introduce. Only
failures beyond the baseline (a real regression) block completion. This is
necessarily captured post-first-edit, not pre-task - see session_state.py.
"""

from helpers.extension import Extension
from helpers.errors import RepairableException
from plugins._coding_controller.helpers import checkpoint, diagnostician, diagnostics, gate_controller, git_state, reviewer, session_state
from plugins._coding_controller.helpers.config import get_config, get_config_for_root


class CodingCompletionGate(Extension):
    FAIL_LOUD = True  # it blocks a premature "done" by raising; isolating it would let the response through

    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if tool_name != "response" or not self.agent or response is None:
            return

        cfg = get_config(self.agent)
        if not cfg["enforce_completion_gate"]:
            return

        dirty = session_state.get_dirty_roots(self.agent)
        if not dirty:
            return  # nothing changed since the last pass - nothing to gate

        failures = []  # (root, result, new_findings, current_fingerprint)
        baseline_captured = []  # (root, result)
        passed_clean = []  # (root, result) - passed this turn, eligible for review
        reverted = []  # roots where a worse repair attempt was rolled back
        for root, kind in dirty.items():
            # A project's own coding.yaml (if present) overrides build-
            # command fields for its own gate run - see config.py's
            # get_config_for_root() docstring for exactly which fields
            # and why enforcement toggles are excluded.
            root_cfg = get_config_for_root(self.agent, root)
            result = await gate_controller.run_gate_for_root(root, kind, root_cfg)

            if result.get("skipped"):
                # Tool not installed / no adapter - can't verify, don't block
                # on it, but drop it so it isn't re-checked every turn either.
                session_state.clear_dirty(self.agent, root)
                continue

            if result["passed"]:
                # Confirmed clean: any future failure here is unambiguously
                # new, not pre-existing.
                session_state.set_baseline(self.agent, root, {})
                session_state.clear_dirty(self.agent, root)
                passed_clean.append((root, result))
                continue

            current_fp = _fingerprint_result(result)
            baseline_fp = session_state.get_baseline(self.agent, root)

            if baseline_fp is None:
                # First time this project has been seen failing - can't yet
                # tell pre-existing from introduced, so don't block; this
                # failure set becomes the reference point going forward.
                session_state.set_baseline(self.agent, root, current_fp)
                session_state.clear_dirty(self.agent, root)
                baseline_captured.append((root, result))
                continue

            new_findings = _new_findings(current_fp, baseline_fp)
            if not new_findings:
                # Still failing, but nothing beyond what was already known -
                # not something this task introduced.
                session_state.clear_dirty(self.agent, root)
                continue

            # A checkpoint exists iff a prior repair attempt was requested
            # for this root - compare against it to see whether that
            # attempt made things worse, and if so, undo it before this
            # failure becomes the basis for the next attempt.
            prior_checkpoint = session_state.get_checkpoint(self.agent, root)
            if prior_checkpoint is not None and checkpoint.is_worse(current_fp, prior_checkpoint.fingerprint):
                await checkpoint.restore_checkpoint(prior_checkpoint)
                reverted.append(root)
                result = await gate_controller.run_gate_for_root(root, kind, root_cfg)
                if result["passed"]:
                    session_state.set_baseline(self.agent, root, {})
                    session_state.clear_dirty(self.agent, root)
                    passed_clean.append((root, result))
                    continue
                current_fp = _fingerprint_result(result)
                new_findings = _new_findings(current_fp, baseline_fp)
                if not new_findings:
                    session_state.clear_dirty(self.agent, root)
                    continue

            failures.append((root, result, new_findings, current_fp))

        max_attempts = cfg["max_repair_attempts"]
        repair_instructions = []
        gave_up = []
        for root, result, new_findings, current_fp in failures:
            attempts = session_state.increment_repair_attempts(self.agent, root)
            if attempts > max_attempts:
                gave_up.append((root, attempts, result))
                session_state.clear_dirty(self.agent, root)
                # Accept the current state as the new baseline so this same
                # unresolved regression isn't flagged again forever.
                session_state.set_baseline(self.agent, root, current_fp)
            else:
                repair_instructions.append(
                    _format_failure(root, result, new_findings, attempts, max_attempts)
                )
                # Checkpoint the state we're about to ask the agent to build
                # on top of, so if the next attempt makes it worse, it can
                # be rolled back to exactly this point instead of compounding
                # the regression.
                new_checkpoint = await checkpoint.save_checkpoint(root, current_fp)
                session_state.set_checkpoint(self.agent, root, new_checkpoint)

        notes = [_format_baseline_captured(root, result) for root, result in baseline_captured]
        notes += [_format_reverted(root) for root in reverted]
        notes += [_format_gave_up(root, attempts) for root, attempts, _result in gave_up]
        if cfg["enable_diagnostician"]:
            for root, attempts, result in gave_up:
                diagnosis = await _run_diagnosis_for_root(self.agent, root, attempts, max_attempts, result)
                notes.append(_format_diagnosis(root, diagnosis))
        if notes:
            response.message = f"{response.message}\n\n" + "\n\n".join(notes)
            response.message = response.message.strip()

        if repair_instructions:
            raise RepairableException("\n\n".join(repair_instructions))

        # Independent review only runs once the gate is genuinely clean this
        # turn (no repair_instructions above) - a reviewer can't rescue a
        # failing gate, and reviewing mid-repair would waste a review call
        # on code that's about to change again anyway.
        if cfg["enable_independent_review"] and passed_clean:
            review_notes = []
            for root, result in passed_clean:
                review_result = await _run_review_for_root(self.agent, root, result)
                if review_result.parse_error:
                    review_notes.append(
                        f"[coding_controller] Independent review for {root} could not be completed "
                        f"({review_result.parse_error}) - treated as UNABLE_TO_VERIFY, not blocking."
                    )
                    continue
                if review_result.has_blocking_findings:
                    raise RepairableException(_format_review_blocking(root, review_result))
                review_notes.append(_format_review_note(root, review_result))
            if review_notes:
                response.message = f"{response.message}\n\n" + "\n\n".join(review_notes)
                response.message = response.message.strip()


async def _run_review_for_root(agent, root: str, result: dict):
    diff = await git_state.get_git_diff(root)
    changed_files = await git_state.get_changed_files(root)
    gate_evidence = "\n".join(
        f"- {s['name']}: {'passed' if s['passed'] else 'FAILED'} (exit_code={s['exit_code']})"
        for s in result.get("stages", [])
    )
    conversation_tail = ""
    try:
        conversation_tail = agent.history.output_text()[-3000:]
    except Exception:
        pass
    packet = reviewer.build_review_packet(
        original_request=conversation_tail,
        acceptance_criteria=[],
        changed_files=changed_files,
        diff=diff,
        baseline_summary="",
        gate_evidence=gate_evidence,
        project_instructions="",
        project_root=root,
    )
    return await reviewer.run_review(agent, packet)


async def _run_diagnosis_for_root(agent, root: str, attempts: int, max_attempts: int, result: dict) -> str:
    diff = await git_state.get_git_diff(root)
    failure_summary = "\n".join(
        f"- {s['name']}: {'passed' if s['passed'] else 'FAILED'} (exit_code={s['exit_code']})"
        for s in result.get("stages", [])
    )
    conversation_tail = ""
    try:
        conversation_tail = agent.history.output_text()[-3000:]
    except Exception:
        pass
    packet = diagnostician.build_diagnosis_packet(
        project_root=root,
        original_request=conversation_tail,
        repair_attempts=attempts,
        max_repair_attempts=max_attempts,
        final_failure_summary=failure_summary,
        diff=diff,
        repair_history="",
    )
    return await diagnostician.run_diagnosis(agent, packet)


def _fingerprint_result(result: dict) -> dict:
    fingerprints = {}
    for stage in result.get("stages", []):
        if stage.get("passed"):
            continue
        fingerprints[stage["name"]] = diagnostics.fingerprint_stage(stage)
    return fingerprints


def _new_findings(current: dict, baseline: dict) -> dict:
    new = {}
    for stage_name, fingerprints in current.items():
        prior = baseline.get(stage_name, frozenset())
        diff = fingerprints - prior
        if diff:
            new[stage_name] = diff
    return new


def _format_failure(root: str, result: dict, new_findings: dict, attempt: int, max_attempts: int) -> str:
    lines = [f"Quality gate found NEW failures for project at {root} (repair attempt {attempt}/{max_attempts})."]
    for stage in result.get("stages", []):
        stage_new = new_findings.get(stage["name"])
        if not stage_new:
            continue
        lines.append(f"- stage '{stage['name']}' exit_code={stage['exit_code']} timed_out={stage['timed_out']}")
        stage_diagnostics = stage.get("diagnostics") or []
        shown = [
            d for d in stage_diagnostics
            if (d["file"], d["code"], d["message"]) in stage_new
        ]
        for diag in shown[:20]:
            lines.append(
                f"  {diag['severity']} {diag['code']} {diag['file']}({diag['line']},{diag['column']}): {diag['message']}"
            )
        if not shown:
            tail = (stage.get("stderr_tail") or stage.get("stdout_tail") or "").strip()
            if tail:
                lines.append(f"  output tail:\n{tail[-1500:]}")
    lines.append(
        "This project already had other pre-existing failures that are not listed above and do not need "
        "fixing here. Fix the smallest possible cause of the NEW failure(s) listed. Do not weaken tests, "
        "disable warnings, or claim the task is done until this gate passes."
    )
    return "\n".join(lines)


def _format_baseline_captured(root: str, result: dict) -> str:
    failing_stages = ", ".join(s["name"] for s in result.get("stages", []) if not s.get("passed"))
    return (
        f"[coding_controller] Note: the quality gate for {root} already had failing stage(s) "
        f"({failing_stages}) before this task's changes. That pre-existing state is now the baseline - "
        "it will not block completion, but a NEW failure introduced beyond it will."
    )


def _format_gave_up(root: str, attempts: int) -> str:
    return (
        f"[coding_controller] The quality gate for {root} still has a new, unresolved failure after "
        f"{attempts} automatic repair attempts. Reporting this as an unresolved failure rather than a "
        "false success claim; manual review is likely needed."
    )


def _format_reverted(root: str) -> str:
    return (
        f"[coding_controller] The previous repair attempt for {root} made the quality gate "
        "worse (more failures, or a stage that was passing is now failing), so it has been "
        "automatically rolled back to the state before that attempt. This still counts toward "
        "the repair attempt budget."
    )


def _format_diagnosis(root: str, diagnosis: str) -> str:
    return f"[coding_controller] Diagnostician's root-cause analysis for {root}:\n{diagnosis.strip()}"


def _format_review_blocking(root: str, review_result) -> str:
    lines = [
        f"Independent review of {root} found blocking issue(s) - decision: {review_result.decision}."
    ]
    for f in review_result.findings:
        if not f.blocking:
            continue
        loc = f"{f.file}:{f.line}" if f.line else f.file
        lines.append(f"- [{f.severity}/{f.category}] {loc}: {f.finding}")
        if f.impact:
            lines.append(f"  impact: {f.impact}")
        if f.recommended_action:
            lines.append(f"  recommended action: {f.recommended_action}")
    lines.append(
        "Address the blocking finding(s) above with the smallest valid fix. "
        "Do not weaken tests or suppress the underlying issue to make the finding go away."
    )
    return "\n".join(lines)


def _format_review_note(root: str, review_result) -> str:
    nonblocking = [f for f in review_result.findings if not f.blocking]
    summary = f"[coding_controller] Independent review of {root}: {review_result.decision}."
    if nonblocking:
        summary += f" {len(nonblocking)} nonblocking finding(s) noted (not required to fix)."
    return summary
