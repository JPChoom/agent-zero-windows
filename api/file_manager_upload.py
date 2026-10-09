import asyncio
import posixpath

from helpers import access_control
from helpers import file_access as fa
from helpers import file_manager as fm
from helpers.api import ApiHandler, Request, Response
from api.file_manager import announce_change, caller

MAX_ANNOUNCED_PATHS = 500


class FileManagerUpload(ApiHandler):
    """Multipart upload into a File Browser folder.

    form: `path` (absolute folder), `overwrite` ("1" replaces same-named
    files, otherwise "name (2)"), files in `files[]`. Folder uploads add
    `relpaths[]` (one per file, "Folder/sub/name.ext") and `dirs[]` (folders
    to create, so empty ones survive); every level is created through
    file_manager.ensure_dir under the caller's policy. Audited like
    api/file_manager.py."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        remote, who = caller(request)
        policy = fa.policy_for(remote)
        folder = request.form.get("path", "")
        overwrite = request.form.get("overwrite") == "1"
        relpaths = request.form.getlist("relpaths[]")
        uploads = request.files.getlist("files[]")
        saved, failed, created_dirs = [], [], []

        for rel in request.form.getlist("dirs[]"):
            try:
                created_dirs.append(await asyncio.to_thread(fm.ensure_dir, folder, rel, policy))
            except (fa.AccessDenied, fm.FileOpError, FileNotFoundError, PermissionError, OSError) as exc:
                failed.append({"name": rel, "error": str(exc) or exc.__class__.__name__})

        for index, upload in enumerate(uploads):
            rel = relpaths[index] if index < len(relpaths) else ""
            subdir = posixpath.dirname(rel.replace("\\", "/")) if rel else ""
            name = posixpath.basename(rel.replace("\\", "/")) if rel else upload.filename
            try:
                target = await asyncio.to_thread(fm.ensure_dir, folder, subdir, policy) if subdir else folder
                saved.append(await asyncio.to_thread(fm.save_upload, target, name, upload.stream, policy, overwrite))
            except (fa.AccessDenied, fm.FileOpError, FileNotFoundError, PermissionError, OSError) as exc:
                failed.append({"name": rel or upload.filename, "error": str(exc) or exc.__class__.__name__})

        access_control.audit(
            "file_upload", by=who, path=folder, saved=saved[:MAX_ANNOUNCED_PATHS], saved_count=len(saved),
            folders=len(created_dirs), failed=[f["name"] for f in failed][:100],
        )
        await announce_change("upload", (saved + created_dirs)[:MAX_ANNOUNCED_PATHS], folder)
        return {"ok": bool(saved or created_dirs) or not failed, "saved": saved, "failed": failed, "folders": created_dirs}
