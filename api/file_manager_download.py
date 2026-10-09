import asyncio
import mimetypes
import os

from flask import Response

from helpers import access_control
from helpers import file_access as fa
from helpers import file_manager as fm
from helpers.api import ApiHandler, Request
from api.download_work_dir_file import make_disposition
from api.file_manager import caller

CHUNK = 256 * 1024


class FileManagerDownload(ApiHandler):
    """GET ?path=<file or folder>[&path=...][&inline=1]. One file streams
    as-is; folders or several items stream as one ZIP built in a temp file
    (removed afterwards). `inline=1` (single file) lets the browser show it,
    for the preview pane. Every download is audited."""

    @classmethod
    def get_methods(cls):
        return ["GET"]

    async def process(self, input: dict, request: Request) -> Response:
        raws = [p for p in request.args.getlist("path") if p]
        if not raws:
            return Response("No path given", status=400)
        return await serve_download(request, raws, inline=request.args.get("inline") == "1")


async def serve_download(request, raws: list[str], inline: bool = False) -> Response:
    """Stream one file, or a ZIP of folders / several items, after checking
    every path against the caller's File Browser policy. Shared with
    api/download_work_dir_file.py."""
    remote, who = caller(request)
    policy = fa.policy_for(remote)
    try:
        targets = [fa.resolve(raw, policy) for raw in raws]
        if len(targets) == 1 and targets[0].is_file():
            path, name, temp = str(targets[0]), targets[0].name, False
        else:
            path, name = await asyncio.to_thread(fm.zip_selection, [str(t) for t in targets], policy)
            temp = True
    except (fa.AccessDenied, fm.FileOpError, FileNotFoundError, PermissionError, OSError) as exc:
        access_control.audit("file_download_refused", by=who, path=raws, error=str(exc)[:300])
        return Response(str(exc) or "Not available", status=403 if isinstance(exc, fa.AccessDenied) else 404)

    access_control.audit("file_download", by=who, path=raws, zipped=temp)
    inline = inline and not temp
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if inline and content_type in ("text/html", "image/svg+xml", "application/xhtml+xml"):
        content_type = "text/plain"  # never render active content from disk in the app's origin

    def stream():
        try:
            with open(path, "rb") as fh:
                while chunk := fh.read(CHUNK):
                    yield chunk
        finally:
            if temp:
                try:
                    os.remove(path)
                except OSError:
                    pass

    headers = {
        "Content-Length": str(os.path.getsize(path)),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline" if inline else make_disposition(name),
    }
    return Response(stream(), content_type=content_type, direct_passthrough=True, headers=headers)
