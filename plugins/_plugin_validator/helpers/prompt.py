from pathlib import Path

from helpers.plugin_review import ChecklistPromptBuilder

_DIR = Path(__file__).parent.parent
_builder = ChecklistPromptBuilder(
    checks_path=_DIR / "webui" / "plugin-validator-checks.json",
    template_path=_DIR / "webui" / "plugin-validator-prompt.md",
    no_checks_selected_label="no validation phases selected",
)
_CHECKLIST_GUIDANCE = None


def _load_guidance() -> str:
    global _CHECKLIST_GUIDANCE
    if _CHECKLIST_GUIDANCE is not None:
        return _CHECKLIST_GUIDANCE

    path = _DIR / "webui" / "plugin-validator-guidance.md"
    try:
        _CHECKLIST_GUIDANCE = path.read_text(encoding="utf-8").strip()
        return _CHECKLIST_GUIDANCE
    except Exception as e:
        raise RuntimeError(f"Unable to load plugin validator guidance: {e}") from e


def _sanitize_target(value: str) -> str:
    return (value or "").strip().replace("{", "(").replace("}", ")")


def _target_reference(source_type: str, target: str) -> str:
    target = _sanitize_target(target)
    if source_type == "local" and target and "/" not in target and "\\" not in target:
        return f"usr/plugins/{target}/"
    return target


def _source_label(source_type: str) -> str:
    return {
        "local": "Local Plugin",
        "git": "Git Repository",
        "zip": "Uploaded ZIP",
    }.get(source_type, "Plugin Source")


def _source_instructions(source_type: str, target: str, cleanup_target: str | None = None) -> str:
    target_ref = _target_reference(source_type, target)
    cleanup_ref = _sanitize_target(cleanup_target or target_ref)

    if source_type == "git":
        return (
            f"Clone `{target_ref}` to a temporary directory outside the workspace, such as "
            "`/tmp/plugin-validate-$(date +%s)`. Validate the cloned files there. After the review, "
            "run `rm -rf /tmp/plugin-validate-*` and verify cleanup with `ls /tmp/plugin-validate-* 2>&1`."
        )

    if source_type == "zip":
        return (
            f"The ZIP has already been extracted to `{target_ref}`. Validate the plugin from that extracted "
            "directory only. Do not install or move it. After the review, delete that extracted directory "
            f"with `rm -rf \"{cleanup_ref}\"` and verify cleanup with `ls \"{cleanup_ref}\" 2>&1`."
        )

    return (
        f"Read the plugin directly from `{target_ref}`. Do not clone, move, or modify the plugin. "
        "No temporary cleanup is required for this source."
    )


def build_prompt(
    source_type: str,
    target: str,
    checks: list | None = None,
    cleanup_target: str | None = None,
) -> str:
    subs = _builder.shared_substitutions(checks)
    subs["SOURCE_LABEL"] = _source_label(source_type)
    subs["TARGET_REFERENCE"] = _target_reference(source_type, target)
    subs["SOURCE_INSTRUCTIONS"] = _source_instructions(source_type, target, cleanup_target)
    subs["CHECKLIST_GUIDANCE"] = _load_guidance()
    return _builder.render(subs)
