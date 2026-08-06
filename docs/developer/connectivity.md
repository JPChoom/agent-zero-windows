# Connectivity

This page helps you choose the right connection path.

For source-linked architecture and endpoint internals, use
[DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero). The local
docs should not duplicate the full connectivity architecture.

## Choose The Right Path

| Need | Start here |
| --- | --- |
| Let Agent Zero work on your host files, shell, or browser | [A0 CLI Connector](../guides/a0-cli-connector.md) |
| Add a third-party tool through MCP | [MCP Setup](../guides/mcp-setup.md) |
| Let another agent talk to Agent Zero | [A2A Setup](../guides/a2a-setup.md) |
| Add an external API for one workflow | [API Integration](../guides/api-integration.md) |
| Study API, MCP, or A2A internals | [DeepWiki](https://deepwiki.com/agent0ai/agent-zero) |

## External API Basics

You can find your API token in Agent Zero under **Settings > External Services**.

Common external endpoints include:

| Endpoint | Use it for |
| --- | --- |
| `POST /api_message` | Send a message to Agent Zero. |
| `GET/POST /api_log_get` | Read chat logs. |
| `POST /api_terminate_chat` | Stop a running chat. |
| `POST /api_reset_chat` | Reset a chat. |
| `POST /api_files_get` | Retrieve files. |

External API calls use the `X-API-KEY` header.

> [!TIP]
> For exact request and response details, check the current source or the
> matching DeepWiki page. That keeps the API reference tied to the code that is
> actually running.

## MCP And A2A

Use MCP when you want Agent Zero to call tools from another app or service.

Use A2A when you want another agent to talk to Agent Zero as a collaborator.

Both use the same Agent Zero instance and can be project-aware when configured
that way.

## Related

- [A0 CLI Connector](../guides/a0-cli-connector.md)
- [MCP Setup](../guides/mcp-setup.md)
- [A2A Setup](../guides/a2a-setup.md)
- [API Integration](../guides/api-integration.md)
- [DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero)
