"""Discord bots: one discord.py client per configured bot, each on its own
thread loop (helpers/chat_channels.BotThread).

Who may talk to the agent:
- the sender's Discord user id must be in `allowed_users` (empty = nobody;
  rejected ids are logged so the owner can find theirs)
- DMs are always considered; in servers the bot answers only when
  @mentioned (`server_mode: mention`), every message in allowed channels
  (`all`, needs the privileged Message Content intent), or never (`off`)
- optional `allowed_channels` restricts server channels by id

Each (bot, user, channel) gets its own Agent Zero chat. Replies are sent by
the process_chain_end extension through `send_reply`.
"""

from __future__ import annotations

import asyncio
import os
import re

from helpers import chat_channels, integration_commands
from helpers.errors import format_error
from helpers.print_style import PrintStyle
from plugins._discord_integration.helpers import constants as C

STATE = chat_channels.ChannelState(C.PLUGIN_NAME)

_MENTION_RE = re.compile(r"<@!?\d+>")


def has_library() -> bool:
    try:
        import discord  # noqa: F401
        return True
    except ImportError:
        return False


def strip_mentions(text: str) -> str:
    return _MENTION_RE.sub("", text or "").strip()


def should_answer(*, is_dm: bool, mentioned: bool, server_mode: str, channel_id: str, allowed_channels) -> bool:
    if is_dm:
        return True
    mode = (server_mode or "mention").lower()
    if mode == "off":
        return False
    channels = [str(c).strip() for c in (allowed_channels or []) if str(c).strip()]
    if channels and str(channel_id) not in channels:
        return False
    return mentioned or mode == "all"


class DiscordBot:

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.client = None
        self.thread = chat_channels.BotThread(f"Discord ({name})", self._main)

    # -- lifecycle ---------------------------------------------------------

    async def _main(self, thread) -> None:
        import discord

        intents = discord.Intents.default()
        intents.dm_messages = True
        intents.guild_messages = True
        # Only needed to read un-mentioned server messages; requesting it
        # without enabling it in the Developer Portal makes login fail.
        intents.message_content = str(self.cfg.get("server_mode", "mention")).lower() == "all"
        client = discord.Client(intents=intents)
        self.client = client

        @client.event
        async def on_ready():
            PrintStyle.success(f"Discord ({self.name}): connected as {client.user}")
            chat_channels.mark_healthy(_key(self.name))
            thread.ready.set()

        @client.event
        async def on_message(message):
            try:
                await self._on_message(message)
            except Exception as e:
                PrintStyle.error(f"Discord ({self.name}): message handling failed: {format_error(e)}")

        try:
            await client.start(str(self.cfg.get("token", "")))
        finally:
            # A failed login leaves discord.py's HTTP session open otherwise.
            if not client.is_closed():
                await client.close()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        client, loop = self.client, self.thread.loop
        if client is not None and loop is not None and self.thread.alive:
            try:
                asyncio.run_coroutine_threadsafe(client.close(), loop).result(15)
            except Exception:
                pass

    @property
    def alive(self) -> bool:
        return self.thread.alive

    # -- incoming ----------------------------------------------------------

    async def _on_message(self, message) -> None:
        import discord

        client = self.client
        if message.author.bot or (client.user and message.author.id == client.user.id):
            return
        cfg = current_cfg(self.name) or self.cfg
        is_dm = isinstance(message.channel, discord.DMChannel)
        mentioned = bool(client.user and client.user in message.mentions)
        if not should_answer(is_dm=is_dm, mentioned=mentioned, server_mode=cfg.get("server_mode", "mention"),
                             channel_id=str(message.channel.id), allowed_channels=cfg.get("allowed_channels")):
            return

        author = message.author
        names = [author.name, getattr(author, "global_name", "") or ""]
        if not chat_channels.is_allowed(cfg.get("allowed_users"), str(author.id), names):
            PrintStyle.warning(
                f"Discord ({self.name}): ignored a message from {author.name} (id {author.id}) - "
                "not in allowed_users."
            )
            return

        text = strip_mentions(message.content) or "[No text content]"
        key = f"{self.name}:{author.id}:{message.channel.id}"
        context = chat_channels.get_or_create_context(
            STATE, key, f"Discord: {author.name}",
            {C.CTX_BOT: self.name, C.CTX_BOT_CFG: cfg, C.CTX_CHANNEL: str(message.channel.id),
             C.CTX_USER: str(author.id)},
            project=str((cfg.get("user_projects") or {}).get(str(author.id)) or cfg.get("default_project") or ""),
        )
        context.data[C.CTX_REPLY_TO] = message.id

        reply = integration_commands.try_handle_command(context, text, integration="discord")
        if reply is None and integration_commands.extract_command_line(text).startswith("/"):
            reply = integration_commands.unknown_command_text(
                integration_commands.extract_command_line(text).split(" ", 1)[0], integration="discord")
        if reply is not None:
            await self._send_text(message.channel, reply, reference=message)
            return

        attachments = await self._download(message)
        prompt = context.agent0.read_prompt("fw.discord.user_message.md", sender=author.name, body=text)
        queued = chat_channels.deliver(context, prompt, attachments, C.SOURCE)
        if queued:
            await self._send_text(message.channel, queued, reference=message)
            return
        self._start_typing(context, message.channel)

        if cfg.get("notify_messages"):
            from helpers.notification import NotificationManager, NotificationPriority, NotificationType
            NotificationManager.send_notification(
                type=NotificationType.INFO, priority=NotificationPriority.HIGH,
                title="Discord: new message", message=f"From {author.name}: {text[:80]}",
                display_time=10, group="discord",
            )

    async def _download(self, message) -> list[str]:
        paths = []
        for att in message.attachments or []:
            if att.size and att.size > C.ATTACHMENT_MAX_BYTES:
                continue
            path, ref = chat_channels.download_path(f"dc_{self.name}", att.filename)
            try:
                await att.save(path)
                paths.append(ref)
            except Exception as e:
                PrintStyle.error(f"Discord ({self.name}): attachment download failed: {e}")
        return paths

    def _start_typing(self, context, channel) -> None:
        stop = asyncio.Event()
        context.data[C.CTX_TYPING] = stop

        async def typing():
            try:
                async with channel.typing():
                    await asyncio.wait_for(stop.wait(), timeout=600)
            except Exception:
                pass

        asyncio.ensure_future(typing())

    # -- outgoing ----------------------------------------------------------

    async def _send_text(self, channel, text: str, reference=None, files=None) -> None:
        import discord

        chunks = chat_channels.split_text(text, C.MESSAGE_LIMIT - 10) or ([""] if files else [])
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            await channel.send(
                content=chunk or None,
                reference=reference if i == 0 else None,
                mention_author=False,
                files=[discord.File(f) for f in files] if (files and last) else None,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _reply(self, channel_id: str, reply_to, text: str, attachments: list[str]) -> None:
        channel = self.client.get_channel(int(channel_id)) or await self.client.fetch_channel(int(channel_id))
        reference = None
        if reply_to:
            try:
                reference = await channel.fetch_message(int(reply_to))
            except Exception:
                reference = None
        files = [p for p in attachments if os.path.isfile(p) and os.path.getsize(p) <= C.ATTACHMENT_MAX_BYTES]
        await self._send_text(channel, text, reference=reference, files=files or None)


def current_cfg(name: str) -> dict:
    from helpers import plugins

    for b in (plugins.get_plugin_config(C.PLUGIN_NAME) or {}).get("bots", []) or []:
        if b.get("name") == name:
            return b
    return {}


def _key(name: str) -> str:
    return f"discord:{name}"


def get_bot(name: str) -> "DiscordBot | None":
    return chat_channels.RUNNING.get(_key(name))


def sync(bots_cfg: list[dict]) -> None:
    """Start, restart or stop bots to match the config."""
    wanted = {b["name"]: b for b in bots_cfg if b.get("enabled") and b.get("name") and b.get("token")}
    chat_channels.sync_clients("discord", wanted, lambda c: (c.get("token"), c.get("server_mode")), DiscordBot)


async def send_reply(context, text: str, attachments: list[str]) -> str:
    """Send the agent's reply for a Discord chat. Returns an error message or ""."""
    bot = get_bot(context.data.get(C.CTX_BOT, ""))
    if not bot or not bot.alive or bot.client is None:
        return "the Discord bot is not running"
    stop = context.data.pop(C.CTX_TYPING, None)
    if stop is not None and bot.thread.loop is not None:
        bot.thread.loop.call_soon_threadsafe(stop.set)
    try:
        await bot.thread.run(bot._reply(context.data.get(C.CTX_CHANNEL, ""),
                                        context.data.get(C.CTX_REPLY_TO), text, attachments or []))
        return ""
    except Exception as e:
        return format_error(e)


async def test_token(token: str) -> tuple[bool, str]:
    import aiohttp

    async with aiohttp.ClientSession() as s:
        async with s.get("https://discord.com/api/v10/users/@me",
                         headers={"Authorization": f"Bot {token}"}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                return True, f"Discord accepted the token: bot {data.get('username')} (id {data.get('id')})."
            return False, f"Discord rejected the token (HTTP {r.status})."
