from helpers.extension import Extension
from plugins._model_config.helpers import model_config, preflight


class ModelPreflightCheck(Extension):
    """Surface mismatches between Agent Zero's model settings and what the
    local inference server actually has loaded.

    See plugins/_model_config/helpers/preflight.py for why this exists and
    what it can/can't detect. Advisory only - findings are dismissible and
    a silent/unreachable server produces nothing.
    """

    SETTINGS_MODAL_PATH = "settings/settings.html"

    async def execute(self, banners: list = [], frontend_context: dict = {}, **kwargs):
        try:
            cfg = model_config.get_config() or {}
            findings = await preflight.run_preflight(cfg)
        except Exception:
            # Advisory only - never break the banner pipeline over it.
            return

        if not findings:
            return

        # A single banner rather than one per finding: these are usually
        # correlated (same server, same misconfiguration) and separate
        # banners would bury the rest of the UI.
        has_warning = any(f.get("level") == "warning" for f in findings)
        items = "".join(
            f"<li><b>{f.get('title', '')}</b><br>{f.get('detail', '')}</li>"
            for f in findings
        )

        banners.append(
            {
                "id": "model-preflight",
                "type": "warning" if has_warning else "info",
                "priority": 80,
                "title": (
                    "Model configuration issue"
                    if has_warning
                    else "Model configuration suggestion"
                ),
                "html": f"<ul style='margin:0;padding-left:1.2em'>{items}</ul>",
                "cta_text": "Open Settings",
                "cta_action": f"open-modal:{self.SETTINGS_MODAL_PATH}",
                "dismissible": True,
                "source": "backend",
            }
        )
