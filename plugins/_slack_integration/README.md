# Slack Integration

Talk to Agent Zero from Slack over **Socket Mode** - no public URL, tunnel or webhook needed.

## Setup

1. Install the library once: `.\.venv\Scripts\python.exe -m pip install -r plugins/_slack_integration/requirements.txt`
2. At <https://api.slack.com/apps> create an app (from scratch) in your workspace.
3. **Socket Mode**: turn it on and create an app-level token with `connections:write` (`xapp-...`).
4. **OAuth & Permissions > Bot Token Scopes**: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `files:read`, `files:write`, `reactions:write` (add `channels:history` for *Every message*).
5. **Event Subscriptions**: enable, subscribe to bot events `app_mention` and `message.im` (add `message.channels` for *Every message*).
6. **App Home**: allow users to send messages in the Messages tab. Install the app and copy the bot token (`xoxb-...`).
7. In Agent Zero, **Settings > External > Slack**: add an app, paste both tokens, add **your Slack member ID** (profile > ... > Copy member ID) to *Allowed users*, and **Test tokens**.

## Behaviour

- **Allowed users only.** An empty list means nobody; others are ignored and their member id is logged.
- DMs always work. In channels the app answers @mentions in a thread; each thread is its own chat.
- While the agent works, your message gets an :eyes: reaction. Text commands such as `/new`, `/status`, `/queue` work in messages.
- Files you send are saved to `usr/uploads/`; the agent can send files back (25 MB each).
- **Security:** Slack chats are capped at the Slack permission mode (default *Manual*). Steps that need approval wait for you in the Agent Zero WebUI.
