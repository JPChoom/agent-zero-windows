"""Independent diff review: spawns a fresh, read-only "coding-reviewer"
sub-agent (see agents/coding-reviewer/ - bundled, not usr/, since this is
a shipped feature of the fork rather than user-local customization) after
a coding task's full quality gate passes, and parses its structured
findings.

Deliberately does NOT use tools/call_subordinate.py's Delegation tool or
its single-subordinate-slot mechanism (Agent.DATA_NAME_SUBORDINATE) - that
slot may already be in use for an unrelated, ongoing delegation the agent
or user initiated, and clobbering it here would silently lose that state.
Instead this spawns its own throwaway Agent instance the same way
Delegation does internally (initialize_agent + Agent(...) + monologue()),
scoped entirely to this one review call.
"""

import json
import re
from dataclasses import dataclass, field

_RE_DECISION = re.compile(r"<review_decision>\s*(.*?)\s*</review_decision>", re.DOTALL)
_RE_FINDINGS = re.compile(r"<review_findings>\s*(.*?)\s*</review_findings>", re.DOTALL)

_VALID_DECISIONS = {"APPROVE", "APPROVE_WITH_NOTES", "CHANGES_REQUIRED", "UNABLE_TO_VERIFY"}
# Ordered least to most severe. NOT YET WIRED to a configurable blocking
# threshold - has_blocking_findings() below currently trusts the model's
# own self-reported "blocking" field per finding, which is a known,
# temporary deviation from this codebase's usual "model proposes,
# deterministic code decides" principle (see _safety_policy, _coding_
# controller's own gate). Follow-up: make blocking = severity meets/exceeds
# a configured review_blocking_severity threshold, ignoring the model's
# self-assessment for the gating decision (keep it as a displayed/logged
# field only). Left as-is for now rather than risk an inconsistent
# half-refactor.
_SEVERITY_RANK = ("informational", "low", "medium", "high", "critical")
_VALID_SEVERITIES = set(_SEVERITY_RANK)

REVIEWER_PROFILE = "coding-reviewer"


@dataclass
class Finding:
    severity: str
    category: str
    file: str
    line: int | None
    finding: str
    impact: str
    evidence: str
    recommended_action: str
    blocking: bool


@dataclass
class ReviewResult:
    decision: str  # one of _VALID_DECISIONS, or "UNABLE_TO_VERIFY" if unparsable
    findings: list[Finding] = field(default_factory=list)
    raw_response: str = ""
    parse_error: str = ""

    @property
    def has_blocking_findings(self) -> bool:
        return any(f.blocking for f in self.findings)


def build_review_packet(
    *,
    original_request: str,
    acceptance_criteria: list[str],
    changed_files: list[str],
    diff: str,
    baseline_summary: str,
    gate_evidence: str,
    project_instructions: str,
    project_root: str,
) -> str:
    lines = [
        "Review this completed coding task. You did not write this code.",
        "",
        f"## Project root\n{project_root}",
        f"## Original request\n{original_request or '(not provided)'}",
    ]
    if acceptance_criteria:
        lines.append("## Acceptance criteria\n" + "\n".join(f"- {c}" for c in acceptance_criteria))
    lines.append("## Changed files\n" + ("\n".join(f"- {f}" for f in changed_files) or "(none listed)"))
    lines.append(f"## Diff\n```diff\n{diff or '(no diff available)'}\n```")
    if baseline_summary:
        lines.append(f"## Baseline (pre-existing) failures\n{baseline_summary}")
    lines.append(f"## Final gate evidence\n{gate_evidence or '(not provided)'}")
    if project_instructions:
        lines.append(f"## Project instructions\n{project_instructions}")
    lines.append(
        "\nProduce your review now. End with the required "
        "<review_decision>/<review_findings> tags."
    )
    return "\n\n".join(lines)


_RETRY_NUDGE = (
    "Your response is missing the required tags. Resend your review, "
    "keeping your findings, but end the message with exactly one "
    "<review_decision>...</review_decision> tag and one "
    "<review_findings>...</review_findings> tag as described in your "
    "instructions - the literal tags, not a description of them."
)


async def run_review(parent_agent, packet: str) -> ReviewResult:
    """Spawn the reviewer sub-agent, run it to completion, and parse its
    structured findings. Never raises - a spawn/parse failure becomes an
    UNABLE_TO_VERIFY result with parse_error set, so a broken reviewer
    can't itself become a silent hard-blocker or a silent bypass.

    Smaller/local models don't always follow the tag-format instruction on
    the first try (observed live against an LM Studio-hosted model - it
    correctly found real issues but replied in free prose with no tags).
    One corrective retry is attempted before giving up as UNABLE_TO_VERIFY."""
    try:
        from agent import Agent, UserMessage
        from initialize import initialize_agent

        config = initialize_agent(override_settings={"agent_profile": REVIEWER_PROFILE})
        reviewer = Agent(parent_agent.number + 1, config, parent_agent.context)
        reviewer.set_data(Agent.DATA_NAME_SUPERIOR, parent_agent)
        reviewer.hist_add_user_message(UserMessage(message=packet, attachments=[]))
        raw_response = await reviewer.monologue()

        result = parse_review_response(raw_response)
        if result.decision == "UNABLE_TO_VERIFY" and "tag" in result.parse_error:
            reviewer.hist_add_user_message(UserMessage(message=_RETRY_NUDGE, attachments=[]))
            raw_response = await reviewer.monologue()
            result = parse_review_response(raw_response)
        return result
    except Exception as exc:
        return ReviewResult(
            decision="UNABLE_TO_VERIFY",
            parse_error=f"reviewer sub-agent failed to run: {exc}",
        )


def parse_review_response(text: str) -> ReviewResult:
    text = str(text or "")

    decision_match = _RE_DECISION.search(text)
    decision = decision_match.group(1).strip().upper() if decision_match else ""
    if decision not in _VALID_DECISIONS:
        return ReviewResult(
            decision="UNABLE_TO_VERIFY",
            raw_response=text,
            parse_error=f"no valid <review_decision> tag found (got: {decision!r})",
        )

    findings_match = _RE_FINDINGS.search(text)
    if not findings_match:
        return ReviewResult(
            decision="UNABLE_TO_VERIFY",
            raw_response=text,
            parse_error="no <review_findings> tag found",
        )

    try:
        raw_findings = json.loads(findings_match.group(1))
        if not isinstance(raw_findings, list):
            raise ValueError("review_findings must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        return ReviewResult(
            decision="UNABLE_TO_VERIFY",
            raw_response=text,
            parse_error=f"review_findings is not valid JSON: {exc}",
        )

    findings: list[Finding] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "")).strip().lower()
        if severity not in _VALID_SEVERITIES:
            severity = "informational"
        line_raw = item.get("line")
        try:
            line = int(line_raw) if line_raw is not None else None
        except (TypeError, ValueError):
            line = None
        findings.append(
            Finding(
                severity=severity,
                category=str(item.get("category", "")).strip(),
                file=str(item.get("file", "")).strip(),
                line=line,
                finding=str(item.get("finding", "")).strip(),
                impact=str(item.get("impact", "")).strip(),
                evidence=str(item.get("evidence", "")).strip(),
                recommended_action=str(item.get("recommended_action", "")).strip(),
                blocking=bool(item.get("blocking", False)),
            )
        )

    return ReviewResult(decision=decision, findings=findings, raw_response=text)
