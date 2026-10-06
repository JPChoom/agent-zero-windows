# Discord Integration

Talk to Agent Zero from Discord: send your bot a DM, or @mention it in a server.

## Setup

1. Install the library once: `.\.venv\Scripts\python.exe -m pip install -r plugins/_discord_integration/requirements.txt`
2. At <https://discord.com/developers/applications> create an application, open **Bot**, and copy the token (**Reset Token**).
3. Invite the bot: **OAuth2 > URL Generator**, scope `bot`, permissions *Send Messages*, *Read Message History*, *Attach Files*.
4. In Agent Zero, **Settings > External > Discord**: add a bot, paste the token, add **your Discord user ID** to *Allowed users* (Discord: Settings > Advanced > Developer Mode, then right-click your name > Copy User ID), and **Test token**.

## Behaviour

- **Allowed users only.** An empty list means nobody; messages from others are ignored and their id is logged, which is also an easy way to find your own.
- DMs always work. In servers the bot answers @mentions by default; *Every message* needs the **Message Content** intent enabled in the Developer Portal.
- Each user gets their own chat per channel. Text commands such as `/new`, `/status`, `/queue`, `/steer` work as on Telegram.
- Files you send are saved to `usr/uploads/`; the agent can send files back (25 MB each).
- **Security:** Discord chats are capped at the Discord permission mode (default *Manual*). Steps that need approval wait for you in the Agent Zero WebUI.
