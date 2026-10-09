from urllib.parse import quote

from helpers.api import ApiHandler, Input, Output, Request


def make_disposition(download_name: str) -> str:
    # RFC 5987: ASCII fallback plus filename* with UTF-8
    ascii_fallback = download_name.encode("ascii", "ignore").decode("ascii") or "download"
    ascii_fallback = ascii_fallback.replace('"', "")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(download_name)}'


class DownloadFile(ApiHandler):
    """GET ?path=... for links built by chat attachments, message file links
    and Office documents. Accepts the old path forms (Docker-style "/a0/...",
    "file://" URLs, workdir-relative, Windows paths), translates them with
    helpers/file_manager.translate and serves them through the File
    Browser's checked, audited download (api/file_manager_download.py), so
    the File Browser access mode applies here too."""

    @classmethod
    def get_methods(cls):
        return ["GET"]

    async def process(self, input: Input, request: Request) -> Output:
        from api.file_manager_download import serve_download
        from helpers import file_manager as fm

        raw = request.args.get("path", input.get("path", ""))
        if not raw:
            from flask import Response

            return Response("No file path provided", status=400)
        return await serve_download(request, [fm.translate(raw)])
