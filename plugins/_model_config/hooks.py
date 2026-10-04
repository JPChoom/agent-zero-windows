def save_plugin_config(result=None, settings=None, **kwargs):
    if settings and isinstance(settings, dict):
        # Remove transient UI-only fields before persisting
        for section in ("chat_model", "utility_model", "embedding_model", "vision_model"):
            if section in settings and isinstance(settings[section], dict):
                settings[section].pop("_kwargs_text", None)
                settings[section].pop("api_key", None)
    return settings


def get_plugin_config(default=None, **kwargs):
    """Backfill slots added after a saved config.json was first written.

    helpers.plugins.get_plugin_config() returns a saved config.json as-is,
    with no merge against current default_config.yaml - so an existing
    install's saved file predates vision_model and won't gain it just by
    the framework reading defaults. Every settings UI load and every
    model_config helper read goes through this hook (it's the generic
    get_plugin_config path, not just the plugin's own custom API
    endpoints), so this is the one place that reliably fixes it for all of
    them.
    """
    if not isinstance(default, dict) or "vision_model" in default:
        return default

    from helpers import plugins

    default_cfg = plugins.get_default_plugin_config("_model_config") or {}
    default["vision_model"] = default_cfg.get("vision_model", {})
    return default
