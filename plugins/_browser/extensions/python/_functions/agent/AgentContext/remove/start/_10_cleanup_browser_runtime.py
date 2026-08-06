from helpers.extension import Extension
from plugins._browser.helpers.runtime import close_runtime_sync


class CleanupBrowserRuntimeOnRemove(Extension):
    def execute(self, data: dict = {}, **kwargs):
        args = data.get("args", ())
        context_id = args[0] if isinstance(args, tuple) and args else ""
        if context_id:
            close_runtime_sync(str(context_id), delete_profile=True)
