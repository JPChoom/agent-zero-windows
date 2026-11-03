import dataclasses

from helpers import files
from helpers.extension import Extension


class NativeAttachmentPaths(Extension):
    """Show the agent attachments at their real path on a native install.

    Uploads are recorded as "/a0/usr/uploads/<file>" (the chat UI previews
    them by that path, so the stored message keeps it). A terminal on a
    native install would read that path on the current drive, not in this
    install (helpers/files.native_path), so the copy of the message the agent
    gets lists the real paths.
    """

    def execute(self, data: dict | None = None, **kwargs):
        args = list((data or {}).get("args") or ())
        if len(args) < 2 or not dataclasses.is_dataclass(args[1]):
            return
        message = args[1]
        attachments = list(getattr(message, "attachments", None) or [])
        native = [files.native_path(a) for a in attachments]
        if native != attachments:
            args[1] = dataclasses.replace(message, attachments=native)
            data["args"] = tuple(args)
