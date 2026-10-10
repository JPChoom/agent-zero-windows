from __future__ import annotations

from helpers import access_control, file_access
from helpers.api import ApiHandler, Request
from plugins._editor.helpers import markdown_sessions
from plugins._office.helpers import document_store


class EditorSession(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "open").lower().strip()
        context_id = str(input.get("ctxid") or input.get("context_id") or "").strip()

        if action == "status":
            return {
                "ok": True,
                "open_files": markdown_sessions.get_manager().list_open(context_id=context_id),
            }
        if action == "home":
            return {"ok": True, "path": document_store.default_open_path(context_id)}
        if action == "list":
            return {
                "ok": True,
                "open_files": markdown_sessions.get_manager().list_open(
                    context_id=context_id,
                    limit=int(input.get("limit") or 20),
                ),
            }
        if action == "activate":
            return markdown_sessions.get_manager().activate(str(input.get("session_id") or ""))
        if action == "close":
            closed = markdown_sessions.get_manager().close(str(input.get("session_id") or ""))
            store_session_id = str(input.get("store_session_id") or "").strip()
            file_id = str(input.get("file_id") or "").strip()
            closed["store_closed"] = document_store.close_session(
                session_id=store_session_id,
                file_id="" if store_session_id else file_id,
            )
            return closed
        if action == "create":
            fmt = str(input.get("format") or "md").lower().lstrip(".")
            if fmt not in document_store.EDITOR_TEXT_EXTENSIONS:
                return {"ok": False, "error": "Editor can only create supported text and source-code files."}
            try:
                doc = document_store.create_document(
                    kind="document",
                    title=str(input.get("title") or "Untitled"),
                    fmt=fmt,
                    content=str(input.get("content") or ""),
                    path=str(input.get("path") or ""),
                    context_id=context_id,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return await self._open_document(doc, input, request, context_id=context_id)
        if action == "open":
            file_id = str(input.get("file_id") or "").strip()
            path = str(input.get("path") or "").strip()
            # Files the user opens from the File Browser follow the File
            # Browser's access policy (Settings > Security, stricter when
            # remote), not just the workdir/project document roots.
            policy_checked = bool(not file_id and path and str(input.get("source") or "") == "file-browser")
            try:
                if file_id:
                    doc = document_store.get_document(file_id)
                elif policy_checked:
                    real = file_access.resolve(path, self._policy(request))
                    doc = document_store.register_document(
                        real, context_id=context_id, policy_checked=True
                    )
                else:
                    doc = document_store.register_document(path, context_id=context_id)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return await self._open_document(
                doc, input, request, context_id=context_id, policy_checked=policy_checked
            )
        if action == "save":
            session_id = str(input.get("session_id") or "").strip()
            if not session_id:
                return {"ok": False, "error": "session_id is required."}
            denied = self._recheck_policy(session_id, request)
            if denied:
                return denied
            return markdown_sessions.get_manager().save(session_id, text=input.get("text"))
        if action == "save_as":
            session_id = str(input.get("session_id") or "").strip()
            path = str(input.get("path") or "").strip()
            if not session_id:
                return {"ok": False, "error": "session_id is required."}
            if not path:
                return {"ok": False, "error": "path is required."}
            try:
                policy_checked = False
                try:
                    document_store.normalize_path(path, context_id=context_id)
                except PermissionError:
                    # Outside the document roots: allowed only where the
                    # File Browser may write.
                    path = str(file_access.resolve(path, self._policy(request), must_exist=False))
                    policy_checked = True
                result = markdown_sessions.get_manager().save_as(
                    session_id, path, text=input.get("text"), policy_checked=policy_checked
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            document_store.close_session(session_id=str(input.get("store_session_id") or "").strip())
            store_session = document_store.create_session(
                result["document"]["file_id"],
                user_id=str(input.get("user_id") or "agent-zero-user"),
                permission="write",
                origin=self._origin(request),
            )
            return {
                **result,
                "store_session_id": store_session["session_id"],
            }
        if action == "renamed":
            return self._renamed(input, context_id)
        if action == "refresh":
            return markdown_sessions.get_manager().refresh_document(str(input.get("file_id") or ""))
        return {"ok": False, "error": f"Unsupported editor session action: {action}"}

    async def _open_document(
        self,
        doc: dict,
        input: dict,
        request: Request,
        context_id: str = "",
        policy_checked: bool = False,
    ) -> dict:
        if str(doc.get("extension") or "").lower() not in document_store.EDITOR_TEXT_EXTENSIONS:
            return {
                "ok": False,
                "error": f".{doc.get('extension', '')} is not supported by the native Windows text editor.",
                "requires_desktop": False,
                "document": _public_doc(doc),
            }

        mode = "edit" if str(input.get("mode") or "edit").lower() == "edit" else "view"
        store_session = document_store.create_session(
            doc["file_id"],
            user_id=str(input.get("user_id") or "agent-zero-user"),
            permission="write" if mode == "edit" else "read",
            origin=self._origin(request),
        )
        try:
            editor = markdown_sessions.get_manager().open(
                doc,
                sid="",
                context_id=context_id,
                refresh=input.get("refresh") is True,
                policy_checked=policy_checked,
            )
        except ValueError as exc:
            document_store.close_session(session_id=store_session["session_id"])
            return {"ok": False, "error": str(exc)}
        return {
            **editor,
            "store_session_id": store_session["session_id"],
            "session_id": editor["session_id"],
            "mode": mode,
        }

    def _renamed(self, input: dict, context_id: str = "") -> dict:
        file_id = str(input.get("file_id") or "").strip()
        path = str(input.get("path") or "").strip()
        if not file_id:
            return {"ok": False, "error": "file_id is required."}
        if not path:
            return {"ok": False, "error": "path is required."}
        try:
            updated = document_store.rename_document(
                file_id,
                path,
                content=input.get("text") if "text" in input else None,
                context_id=context_id,
            )
            markdown_sessions.get_manager().renamed(
                file_id,
                updated,
                text=input.get("text") if "text" in input else None,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "document": _public_doc(updated),
            "version": document_store.item_version(updated),
            "refreshFiles": False,
        }

    def _origin(self, request: Request) -> str:
        origin = request.headers.get("Origin") or request.host_url.rstrip("/")
        return origin.rstrip("/")

    def _policy(self, request: Request) -> file_access.Policy:
        remote = not access_control.is_local_request(
            getattr(request, "remote_addr", None), getattr(request, "headers", {}) or {}
        )
        return file_access.policy_for(remote)

    def _recheck_policy(self, session_id: str, request: Request) -> dict | None:
        """A file opened through the File Browser policy is saved only while that
        policy (for this request: local or remote) still allows it."""
        session = markdown_sessions.get_manager().get_session(session_id)
        if not session or not session.policy_checked:
            return None
        try:
            file_access.resolve(session.path, self._policy(request))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return None


def _public_doc(doc: dict) -> dict:
    return {
        "file_id": doc["file_id"],
        "path": document_store.display_path(doc["path"]),
        "basename": doc["basename"],
        "title": doc["basename"],
        "extension": doc["extension"],
        "size": doc["size"],
        "version": document_store.item_version(doc),
        "last_modified": doc["last_modified"],
    }


