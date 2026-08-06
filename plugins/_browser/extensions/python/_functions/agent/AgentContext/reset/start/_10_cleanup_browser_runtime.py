from helpers.extension import Extension
from plugins._browser.helpers.runtime import close_runtime_sync


class CleanupBrowserRuntimeOnReset(Extension):
    def execute(self, data: dict = {}, **kwargs):
        args = data.get("args", ())
        context = args[0] if isinstance(args, tuple) and args else None
        context_id = getattr(context, "id", "")
        if context_id:
            close_runtime_sync(context_id, delete_profile=True)
