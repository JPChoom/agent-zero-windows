"""Fail-closed startup self-test: asserts _safety_policy's own documented
invariant (get_config() defaults to enforce_policy=True and denies by
default when a project has no config at all, AND stays True even if the
stored value is present but garbled - a corrupted config file or a
typo'd setting must not silently disable enforcement) still holds, so a
future refactor that accidentally flips that default is caught
immediately rather than silently shipping a fork that no longer enforces
anything by default.

Logged, not gating: a failure here means the fork's advertised safety
posture doesn't match its actual behavior, which is worth a loud warning
at every startup - but this repo's own principle throughout the safety
work this phase belongs to is "fail closed on missing/broken config, not
fail loud and refuse to start," so this doesn't block startup either.
"""

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class SafetyPolicyFailClosedSelfTest(Extension):
    def execute(self, **kwargs):
        ok, problems = _check_fail_closed_invariants()
        if ok:
            return
        PrintStyle.error(
            "[startup self-test] _safety_policy's fail-closed defaults do not hold: "
            + "; ".join(problems)
        )


def _check_fail_closed_invariants() -> tuple[bool, list[str]]:
    problems: list[str] = []
    try:
        from plugins._safety_policy.helpers.config import get_config

        cfg = get_config(None)
    except Exception as exc:
        return False, [f"could not even call get_config(None): {exc}"]

    if cfg.get("enforce_policy") is not True:
        problems.append(
            f"enforce_policy defaulted to {cfg.get('enforce_policy')!r} with no plugin config present, expected True"
        )

    try:
        from plugins._safety_policy.helpers.config import _as_bool_fail_closed

        garbled = _as_bool_fail_closed("not a real boolean value")
        if garbled is not True:
            problems.append(
                f"_as_bool_fail_closed('not a real boolean value') returned {garbled!r}, expected True - "
                "a garbled (present but unrecognized) enforce_policy value must fail closed, not disable enforcement"
            )
    except Exception as exc:
        problems.append(f"could not call _as_bool_fail_closed: {exc}")

    if not isinstance(cfg.get("approval_timeout_seconds"), int) or cfg.get("approval_timeout_seconds") <= 0:
        problems.append(
            f"approval_timeout_seconds defaulted to {cfg.get('approval_timeout_seconds')!r}, expected a positive int"
        )

    try:
        from plugins._safety_policy.helpers import policy

        decision = policy.classify_command("shutdown /r /t 0", [], set())
        if decision.allowed:
            problems.append(
                "classify_command('shutdown /r /t 0', no custom patterns, no approval categories) "
                "was allowed - a known-destructive command must be denied by default"
            )
    except Exception as exc:
        problems.append(f"could not call policy.classify_command: {exc}")

    return not problems, problems
