"""Root-cause diagnosis: spawns a fresh, read-only "coding-diagnostician"
sub-agent (see agents/coding-diagnostician/) once the automatic repair
loop has given up on a project (exhausted max_repair_attempts without
clearing a new failure - see _80_completion_gate.py's `gave_up` handling).

Unlike reviewer.py's output, a diagnosis is purely advisory narrative, not
a gating decision - nothing downstream needs to parse it into a structured
verdict, so this deliberately has no tag contract or parser to keep
fragile against. The diagnostician's job is to explain *why* the repair
attempts kept failing (wrong fix target, a misleading error message, a
fix that addressed a symptom instead of the cause, etc.), for whoever
picks this up next - the user or a later session - not to fix it itself
(it has no write/execute tools, same restriction as the reviewer role).
"""

DIAGNOSTICIAN_PROFILE = "coding-diagnostician"


def build_diagnosis_packet(
    *,
    project_root: str,
    original_request: str,
    repair_attempts: int,
    max_repair_attempts: int,
    final_failure_summary: str,
    diff: str,
    repair_history: str,
) -> str:
    lines = [
        "A coding task's automatic repair loop has given up on this project "
        f"after {repair_attempts}/{max_repair_attempts} attempts without clearing a new "
        "quality-gate failure. You did not attempt any of the repairs yourself - you are "
        "investigating why they kept failing, not fixing it.",
        "",
        f"## Project root\n{project_root}",
        f"## Original request\n{original_request or '(not provided)'}",
        f"## Current (still-failing) diff\n```diff\n{diff or '(no diff available)'}\n```",
        f"## Final failure, after all repair attempts\n{final_failure_summary or '(not provided)'}",
    ]
    if repair_history:
        lines.append(f"## Repair attempt history\n{repair_history}")
    lines.append(
        "\nInvestigate and explain the likely root cause: was a symptom being fixed "
        "instead of the underlying issue, was the wrong file/function targeted, is the "
        "error message misleading about where the real problem is, or is this a "
        "pre-existing/environmental issue unrelated to the task? End with a concise "
        "recommendation for what to try next - you cannot make the change yourself."
    )
    return "\n\n".join(lines)


async def run_diagnosis(parent_agent, packet: str) -> str:
    """Spawn the diagnostician sub-agent and return its raw response text.

    Never raises - a spawn failure becomes a short explanatory string
    rather than blowing up the (already-given-up) repair loop further."""
    from plugins._coding_controller.helpers import coding_agent_manager as cam

    try:
        role = await cam.create_role(parent_agent, DIAGNOSTICIAN_PROFILE)
        raw_response = await cam.send_task(role, packet)
        cam.terminate_role(role)
        return raw_response
    except Exception as exc:
        return f"(diagnostician sub-agent failed to run: {exc})"
