"""Where a memory came from, how far to trust it, and when it was last used.

Stamped onto every new memory's metadata (after any caller-supplied fields,
so the agent can't label its own memory "high" trust):

    source     user-file | conversation | agent
    trust      high | medium | low
    project    active project name ("" for none)
    chat       context id the memory was formed in
    last_used  timestamp of the last recall ("" until recalled)

Trust:
- high   - imported knowledge files the user put in place
- medium - formed in a chat that never read content from outside this PC
- low    - formed in a chat that did (web pages, search results, documents
           fetched by URL, MCP or other agents, other apps' windows): the
           memorizers already strip that content, but what the agent
           concluded from it can be skewed. Local command output and file
           reads don't lower trust - that would mark nearly every memory
           "low" and make the label noise.

A merge keeps the lowest trust of the memories it combines.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

TRUST_ORDER = ("low", "medium", "high")

# Tools whose results come from outside this PC. MCP tools ("server.tool")
# count too. Matched against the source attribute of <untrusted_content>
# blocks in the chat history (helpers/untrusted_content.py).
EXTERNAL_SOURCES = frozenset({
    "browser", "search_engine", "webpage_content_tool", "document_query",
    "a2a_chat", "ytdlp", "computer_use",
})
_SOURCE_RE = re.compile(r'<untrusted_content (?:id="[0-9a-f]+" )?source="([^"]+)"')


def read_external_content(agent) -> bool:
    try:
        text = agent.concat_messages(agent.history)
    except Exception:
        return False
    for source in _SOURCE_RE.findall(str(text or "")):
        if source in EXTERNAL_SOURCES or "." in source:
            return True
    return False
PROVENANCE_KEYS = ("source", "trust", "project", "chat")

_SAVE_INTERVAL_SECONDS = 600
_last_saved: dict[str, float] = {}


def lowest_trust(*levels) -> str:
    known = [lvl for lvl in levels if lvl in TRUST_ORDER]
    if not known:
        return ""
    return min(known, key=TRUST_ORDER.index)


def stamp(metadata: dict, agent, source: str) -> dict:
    """Return metadata with provenance fields set (overwriting any supplied ones)."""
    context = getattr(agent, "context", None)
    project = ""
    try:
        from helpers import projects

        project = projects.get_context_project_name(context) or "" if context is not None else ""
    except Exception:
        project = ""

    if source == "user-file":
        trust = "high"
    else:
        trust = "low" if read_external_content(agent) else "medium"

    out = {k: v for k, v in (metadata or {}).items() if k not in PROVENANCE_KEYS and k != "last_used"}
    out.update({
        "source": source,
        "trust": trust,
        "project": project,
        "chat": str(getattr(context, "id", "") or ""),
        "last_used": "",
    })
    return out


def touch(memory, docs) -> None:
    """Record that these memories were just recalled.

    Edits the stored documents' metadata in place (no re-embedding) and
    persists at most every few minutes per memory folder.
    """
    if not docs:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    changed = False
    store = getattr(getattr(memory, "db", None), "docstore", None)
    for doc in docs:
        doc_id = (getattr(doc, "metadata", None) or {}).get("id")
        if not doc_id:
            continue
        stored = None
        try:
            stored = store.search(doc_id) if store is not None else None
        except Exception:
            stored = None
        for target in (doc, stored):
            meta = getattr(target, "metadata", None)
            if isinstance(meta, dict):
                meta["last_used"] = now
                changed = True
    if not changed:
        return
    key = str(getattr(memory, "memory_subdir", ""))
    if time.monotonic() - _last_saved.get(key, 0.0) >= _SAVE_INTERVAL_SECONDS:
        _last_saved[key] = time.monotonic()
        try:
            memory._save_db()
        except Exception:
            pass
