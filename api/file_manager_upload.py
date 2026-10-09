import asyncio

from helpers import access_control
from helpers import file_access as fa
from helpers import file_manager as fm
from helpers.api import ApiHandler, Request, Response
from api.file_manager import announce_change, caller


class FileManagerUpload(ApiHandler):
    """Multipart upload into a File Browser folder: form `path` (absolute
    folder), `overwrite` ("1" replaces same-named files, otherwise "name (2)"),
    files in `files[]`. Checked and audited like api/file_manager.py."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        remote, who = caller(request)
        policy = fa.policy_for(remote)
        folder = request.form.get("path", "")
        overwrite = request.form.get("overwrite") == "1"
        saved, failed = [], []
        for upload in request.files.getlist("files[]"):
            try:
                saved.append(await asyncio.to_thread(fm.save_upload, folder, upload.filename, upload.stream, policy, overwrite))
            except (fa.AccessDenied, fm.FileOpError, FileNotFoundError, PermissionError, OSError) as exc:
                failed.append({"name": upload.filename, "error": str(exc) or exc.__class__.__name__})
        access_control.audit("file_upload", by=who, path=folder, saved=saved, failed=[f["name"] for f in failed])
        await announce_change("upload", saved, folder)
        return {"ok": bool(saved) or not failed, "saved": saved, "failed": failed}
