# Plugins

Most people should start with the practical guide:
[Create a Small Plugin](../guides/create-plugin.md).

Plugin architecture and source-linked internals live in
[DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero). This page
stays intentionally small so the repository does not maintain a second plugin
manual.

## What To Use

| Goal | Start here |
| --- | --- |
| Build your first plugin | [Create a Small Plugin](../guides/create-plugin.md) |
| Understand how plugins are loaded | [DeepWiki](https://deepwiki.com/agent0ai/agent-zero) |
| Decide what is safe to publish | [Sharing and Safety](sharing-and-safety.md) |
| Contribute a plugin upstream | [Contributing Guide](../guides/contribution.md) |

## Minimum Local Plugin

A local plugin usually lives here:

```text
/a0/usr/plugins/<plugin_name>/
├── plugin.yaml
├── README.md
└── webui/
```

The smallest useful `plugin.yaml` looks like this:

```yaml
name: my_plugin
title: My Plugin
description: A short sentence that explains what it does.
version: 1.0.0
```

Ask Agent Zero to keep the first version small. A tiny plugin that does one
visible thing is easier to test, review, and share.

## Sharing A Plugin

Before publishing a plugin:

- keep it in its own public repository;
- include a clear `README.md`;
- include a `LICENSE`;
- avoid secrets, local paths, and machine-specific files;
- explain what the plugin changes and how to remove it.

For Plugin Index submission, use the current instructions in the
[`agent0ai/a0-plugins`](https://github.com/agent0ai/a0-plugins) repository.

## Related

- [Create a Small Plugin](../guides/create-plugin.md)
- [Sharing and Safety](sharing-and-safety.md)
- [DeepWiki for Agent Zero](https://deepwiki.com/agent0ai/agent-zero)
