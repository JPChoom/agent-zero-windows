from pathlib import Path

from helpers.plugin_review import ChecklistPromptBuilder

_DIR = Path(__file__).parent.parent
_builder = ChecklistPromptBuilder(
    checks_path=_DIR / "webui" / "plugin-scan-checks.json",
    template_path=_DIR / "webui" / "plugin-scan-prompt.md",
    no_checks_selected_label="no checks selected",
)


def build_prompt(git_url: str, checks: list | None = None) -> str:
    subs = _builder.shared_substitutions(checks)
    subs["GIT_URL"] = git_url
    return _builder.render(subs)
