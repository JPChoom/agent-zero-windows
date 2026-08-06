# WebSockets

Agent Zero WebSocket architecture is documented in
[DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero).

This local page is only a handoff. Keeping the full protocol guide here would
duplicate source-linked documentation and become stale.

## When You Are Working On WebSockets

Start with the source and DeepWiki:

- `helpers/ws.py`
- `helpers/ws_manager.py`
- `api/ws_*.py`
- `webui/js/websocket.js`
- WebSocket pages in [DeepWiki](https://deepwiki.com/agent0ai/agent-zero)

## Keep These Rules In Mind

- Preserve authentication and CSRF checks.
- Keep payloads JSON-serializable.
- Prefer small, named events over large catch-all events.
- Test reconnects, timeouts, and duplicate deliveries.
- Keep user-facing behavior documented in the relevant guide, not in this
  protocol handoff page.

## Related

- [Architecture](architecture.md)
- [DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero)
