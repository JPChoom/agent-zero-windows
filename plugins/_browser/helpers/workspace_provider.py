"""Browser tabs for the Agent Workspace view (helpers/workspace.py).

Tabs already belong to a chat: each chat has its own browser runtime, closed
when the chat is deleted or reset (see the AgentContext remove/reset hooks in
this plugin). This only lists them; it never starts a browser.
"""

from __future__ import annotations

from urllib.parse import urlparse

from plugins._browser.helpers import runtime


async def resources() -> list[dict]:
    items = []
    for tab in runtime.peek_pages():
        url = tab["url"]
        host = urlparse(url).netloc if "://" in url else ""
        items.append({
            "id": f"browser:{tab['context_id']}:{tab['browser_id']}",
            "kind": "browser",
            "label": host or url or "Blank tab",
            "detail": url,
            "owner_context": tab["context_id"],
            "owner_agent": "",
            "state": "active",
            "note": "Closes with its chat",
        })
    return items
