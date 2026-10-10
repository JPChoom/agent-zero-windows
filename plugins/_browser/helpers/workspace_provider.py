"""Browser tabs for the Agent Workspace view (helpers/workspace.py).

Tabs already belong to a chat: each chat has its own browser runtime, closed
when the chat is deleted or reset (see the AgentContext remove/reset hooks in
this plugin). This only lists them; it never starts a browser. The agent that
opened a tab with the browser tool is remembered for display (tabs opened by a
page itself show no agent); agents in one chat still share its tabs.
"""

from __future__ import annotations

from urllib.parse import urlparse

from plugins._browser.helpers import runtime

_openers: dict[tuple[str, int], str] = {}


def record_opener(context_id, browser_id, agent_name: str) -> None:
    try:
        _openers[(str(context_id), int(browser_id))] = str(agent_name or "")
    except (TypeError, ValueError):
        pass


async def resources() -> list[dict]:
    items = []
    tabs = runtime.peek_pages()
    open_keys = {(t["context_id"], int(t["browser_id"])) for t in tabs}
    for key in list(_openers):
        if key not in open_keys:
            del _openers[key]  # the tab or its chat is gone
    for tab in tabs:
        url = tab["url"]
        host = urlparse(url).netloc if "://" in url else ""
        items.append({
            "id": f"browser:{tab['context_id']}:{tab['browser_id']}",
            "kind": "browser",
            "label": host or url or "Blank tab",
            "detail": url,
            "owner_context": tab["context_id"],
            "owner_agent": _openers.get((tab["context_id"], int(tab["browser_id"])), ""),
            "state": "active",
            "note": "Closes with its chat",
        })
    return items
