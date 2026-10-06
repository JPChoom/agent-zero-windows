"""Marking external content as data, and tracking whether a chat has seen any.

Tool results are where outside text enters an agent's context: web pages,
search results, parsed documents, files from cloned repos, command output,
MCP and A2A replies. A prompt-injection attack hides instructions in that
text. Two defenses use this module:

1. wrap_tool_result(): every tool result except those A0 generates itself is
   wrapped in an <untrusted_content id="KEY" source="..."> block, and the
   system prompt (prompts/agent.system.main.role.md) tells the agent such
   blocks are data, never instructions, and end only at the closing tag
   carrying the same KEY. KEY is fresh random hex per result, so text written
   in advance (a web page, a file) cannot contain the real closing tag. On
   top of that, tag-like text inside the content is neutralized in any case,
   spacing, HTML-entity or full-width form, so it can't pose as a boundary.

2. A per-chat taint flag (context data): set the first time untrusted
   content is added. The infection check can skip its model call while a
   chat has never seen untrusted content, since nothing in the context could
   have injected anything.
"""

from __future__ import annotations

import re
import secrets

TAG = "untrusted_content"
DATA_KEY = "untrusted_content_seen"

# Results written by Agent Zero itself (or a reply from its own subordinate,
# whose own tool results were already wrapped in its history).
TRUSTED_TOOLS = frozenset({
    "response",
    "call_subordinate",
    "notify_user",
    "wait",
    "scheduler",
    "memory_save",
    "memory_delete",
    "memory_forget",
    "behaviour_adjustment",
    "coding_gate",
    "goal",
    "parallel",
    "unknown",
})

# Tool calls with no side effects outside reading local state - the
# infection check has nothing to stop there.
READ_ONLY_ACTIONS = {
    "text_editor": {"read"},
    "skills_tool": {"list", "search", "load", "read_file"},
    "memory_load": None,  # None = every call
    "vision_load": None,
    "wait": None,
}


def is_trusted_tool(tool_name: str) -> bool:
    return str(tool_name or "") in TRUSTED_TOOLS


def is_read_only_call(tool_name: str, tool_args: dict | None) -> bool:
    name = str(tool_name or "")
    if name not in READ_ONLY_ACTIONS:
        return False
    allowed = READ_ONLY_ACTIONS[name]
    if allowed is None:
        return True
    args = tool_args or {}
    action = str(args.get("action") or args.get("method") or "").strip().lower()
    return action in allowed


# Text that could pass for one of our tags: "<" in plain, HTML-entity or
# full-width form, an optional slash and spaces, then the tag name in any
# case with optional separators ("</ UNTRUSTED-content", "&lt;/untrusted_content").
_TAG_LIKE_RE = re.compile(
    r"(?P<lt><|&lt;|&#0*60;|&#x0*3c;|＜)"
    r"(?P<mid>\s*(?:/|／)?\s*)"
    r"(?P<name>untrusted[\s_\-]*content)",
    re.IGNORECASE,
)


def _neutralize(text: str) -> str:
    # Break any tag that would close (or reopen) our block from inside by
    # appending "_" to its name: "</untrusted_content>" -> "</untrusted_content_>".
    return _TAG_LIKE_RE.sub(lambda m: f"{m.group('lt')}{m.group('mid')}{m.group('name')}_", text)


def _new_key() -> str:
    return secrets.token_hex(8)


def wrap_tool_result(tool_name: str, result: str, key: str | None = None) -> str:
    source = "".join(c for c in str(tool_name or "tool") if c.isalnum() or c in "_-.:") or "tool"
    key = key or _new_key()
    return f'<{TAG} id="{key}" source="{source}">\n{_neutralize(result)}\n</{TAG} id="{key}">'


def is_wrapped(result: str) -> bool:
    return isinstance(result, str) and result.startswith(f"<{TAG} ")


_BLOCK_RE = None
_INJECTION_RE = None


def strip_untrusted_blocks(text: str, placeholder: str = "[external content omitted]") -> str:
    """Replace every <untrusted_content> block with a placeholder - for
    consumers that must never learn from outside text (fragment memory)."""
    global _BLOCK_RE

    if _BLOCK_RE is None:
        # A block ends only at the closing tag with its own id. The legacy
        # form (no id) still matches so chats saved before ids existed strip
        # correctly too.
        _BLOCK_RE = re.compile(
            rf"<{TAG} id=\"(?P<key>[0-9a-f]+)\" source=\"[^\"]*\">.*?</{TAG} id=\"(?P=key)\">"
            rf"|<{TAG} source=\"[^\"]*\">.*?</{TAG}>",
            re.DOTALL,
        )
    return _BLOCK_RE.sub(placeholder, str(text or ""))


def looks_like_injected_instruction(text: str) -> bool:
    """Heuristic for memory candidates phrased as orders to the agent rather
    than facts - the shape a prompt-injection takes when it tries to persist
    itself ("always send...", "ignore previous instructions", ...)."""
    global _INJECTION_RE

    if _INJECTION_RE is None:
        _INJECTION_RE = re.compile(
            r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules|messages)"
            r"|you\s+are\s+now\s+(unrestricted|jailbroken|in\s+developer\s+mode)"
            r"|(system|developer)\s+prompt"
            r"|<\s*/?\s*(system|untrusted_content)"
            r"|(always|must|should)\s+(send|upload|post|forward|exfiltrate|email)\b"
            r"|do\s+not\s+(tell|inform|alert)\s+the\s+user",
            re.IGNORECASE,
        )
    return bool(_INJECTION_RE.search(str(text or "")))


def _context(agent):
    return getattr(agent, "context", None)


def mark_tainted(agent) -> None:
    ctx = _context(agent)
    if ctx is None:
        return
    try:
        if not ctx.get_data(DATA_KEY):
            ctx.set_data(DATA_KEY, True)
    except Exception:
        pass


def is_tainted(agent) -> bool:
    ctx = _context(agent)
    if ctx is None:
        return True  # unknown -> assume the worst
    try:
        return bool(ctx.get_data(DATA_KEY))
    except Exception:
        return True
