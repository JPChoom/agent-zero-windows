from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read(*parts: str) -> str:
    return PROJECT_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_model_config_text_buttons_have_shared_primitive() -> None:
    buttons_css = read("webui", "css", "buttons.css")
    preset_modal = read("plugins", "_model_config", "webui", "main.html")
    config_modal = read("plugins", "_model_config", "webui", "config.html")

    assert ".text-button {" in buttons_css
    assert "appearance: none;" in buttons_css
    assert ".text-button:hover:not(:disabled)" in buttons_css
    assert ".text-button .material-symbols-outlined" in buttons_css
    assert 'class="text-button preset-add-btn"' in preset_modal
    assert 'class="text-button preset-delete-btn"' in preset_modal
    assert 'class="text-button"' in config_modal
