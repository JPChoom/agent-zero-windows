"""Slack apps over Socket Mode (no public URL needed): one slack_sdk client
per configured app, each on its own thread loop
(helpers/chat_channels.BotThread).

Needs a bot token (xoxb-) and an app-level token with connections:write
(xapp-). Events: `message.im` for DMs and `app_mention` for channels (plus
`message.channels` only for channel_mode "all").

Who may talk to the agent:
- the sender's Slack member id (U...) must be in `allowed_users`
  (empty = nobody; rejected ids are logged)
- DMs are always considered; in channels the app answers @mentions
  (`channel_mode: mention`), every message (`all`), or nothing (`off`);
  optional `allowed_channels` restricts channels by id

Channel conversations are answered in a thread. While the agent works, the
user's message gets an :eyes: reaction (needs reactions:write; best effort).
"""

from __future__ import annotations

import os
import re

from helpers import chat_channels, integration_commands
from helpers.errors import format_error
from helpers.print_style import PrintStyle
from plugins._slack_integration.helpers import constants as C

STATE = chat_channels.ChannelState(C.PLUGIN_NAME)
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def has_library() -> bool:
    try:
        import slack_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def strip_mentions(text: str) -> str:
    return _MENTION_RE.sub("", text or "").strip()


def to_mrkdwn(text: str) -> str:
    """Common Markdown -> Slack mrkdwn (outside code blocks)."""
    parts = re.split(r"(```.*?```|`[^`\n]+`)", str(text or ""), flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        p = parts[i]
        p = _LINK_RE.sub(r"<\2|\1>", p)
        p = _HEADING_RE.sub(r"*\1*", p)
        p = _BOLD_RE.sub(r"*\1*", p)
        p = _STRIKE_RE.sub(r"~\1~", p)
        parts[i] = p
    return "".join(parts)


def classify_event(event: dict, bot_user_id: str, channel_mode: str, allowed_channels) -> str:
    """"" to ignore, else "dm" / "mention" / "channel"."""
    etype = event.get("type")
    if event.get("bot_id") or event.get("user") in (None, "", bot_user_id):
        return ""
    if etype == "message" and event.get("subtype") not in (None, "file_share"):
        return ""
    if etype == "message" and event.get("channel_type") == "im":
        return "dm"
    mode = (channel_mode or "mention").lower()
    if mode == "off":
        return ""
    channels = [str(c).strip() for c in (allowed_channels or []) if str(c).strip()]
    if channels and str(event.get("channel")) not in channels:
        return ""
    if etype == "app_mention":
        return "mention"
    if etype == "message" and mode == "all" and f"<@{bot_user_id}>" not in (event.get("text") or ""):
        # Mentions arrive twice (message + app_mention); answer the app_mention one.
        return "channel"
    return ""


class SlackBot:

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.web = None
        self.socket = None
        self.bot_user_id = ""
        self.thread = chat_channels.BotThread(f"Slack ({name})", self._main)

    async def _main(self, thread) -> None:
        import asyncio

        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web.async_client import AsyncWebClient

        self.web = AsyncWebClient(token=str(self.cfg.get("bot_token", "")))
        auth = await self.web.auth_test()
        self.bot_user_id = auth.get("user_id", "")
        self.socket = SocketModeClient(app_token=str(self.cfg.get("app_token", "")), web_client=self.web)

        async def on_request(client, req):
            if req.type != "events_api":
                return
            await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            try:
                await self._on_event((req.payload or {}).get("event") or {})
            except Exception as e:
                PrintStyle.error(f"Slack ({self.name}): event handling failed: {format_error(e)}")

        self.socket.socket_mode_request_listeners.append(on_request)
        await self.socket.connect()
        PrintStyle.success(f"Slack ({self.name}): connected as {auth.get('user')} in {auth.get('team')}")
        chat_channels.mark_healthy(_key(self.name))
        thread.ready.set()
        self._stop = asyncio.Event()
        await self._stop.wait()
        await self.socket.close()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        loop = self.thread.loop
        stop = getattr(self, "_stop", None)
        if loop is not None and stop is not None and self.thread.alive:
            loop.call_soon_threadsafe(stop.set)

    @property
    def alive(self) -> bool:
        return self.thread.alive

    # -- incoming ----------------------------------------------------------

    async def _on_event(self, event: dict) -> None:
        cfg = current_cfg(self.name) or self.cfg
        kind = classify_event(event, self.bot_user_id, cfg.get("channel_mode", "mention"), cfg.get("allowed_channels"))
        if not kind:
            return
        user_id, channel = str(event.get("user")), str(event.get("channel"))
        if not chat_channels.is_allowed(cfg.get("allowed_users"), user_id):
            PrintStyle.warning(f"Slack ({self.name}): ignored a message from member id {user_id} - not in allowed_users.")
            return

        thread_ts = "" if kind == "dm" else str(event.get("thread_ts") or event.get("ts") or "")
        text = strip_mentions(event.get("text", "")) or "[No text content]"
        key = f"{self.name}:{user_id}:{channel}:{thread_ts}"
        context = chat_channels.get_or_create_context(
            STATE, key, f"Slack: {user_id}",
            {C.CTX_BOT: self.name, C.CTX_BOT_CFG: cfg, C.CTX_CHANNEL: channel, C.CTX_USER: user_id},
            project=str((cfg.get("user_projects") or {}).get(user_id) or cfg.get("default_project") or ""),
        )
        context.data[C.CTX_THREAD] = thread_ts
        context.data[C.CTX_MESSAGE_TS] = str(event.get("ts") or "")

        reply = integration_commands.try_handle_command(context, text, integration="slack")
        if reply is None and integration_commands.extract_command_line(text).startswith("/"):
            reply = integration_commands.unknown_command_text(
                integration_commands.extract_command_line(text).split(" ", 1)[0], integration="slack")
        if reply is not None:
            await self._post(channel, thread_ts, reply)
            return

        attachments = await self._download(event.get("files") or [])
        prompt = context.agent0.read_prompt("fw.slack.user_message.md", sender=user_id, body=text)
        queued = chat_channels.deliver(context, prompt, attachments, C.SOURCE)
        if queued:
            await self._post(channel, thread_ts, queued)
            return
        await self._react(channel, str(event.get("ts") or ""), add=True)

        if cfg.get("notify_messages"):
            from helpers.notification import NotificationManager, NotificationPriority, NotificationType
            NotificationManager.send_notification(
                type=NotificationType.INFO, priority=NotificationPriority.HIGH,
                title="Slack: new message", message=f"From {user_id}: {text[:80]}",
                display_time=10, group="slack",
            )

    async def _download(self, slack_files: list[dict]) -> list[str]:
        import aiohttp

        paths = []
        headers = {"Authorization": f"Bearer {self.cfg.get('bot_token', '')}"}
        async with aiohttp.ClientSession() as session:
            for f in slack_files:
                url = f.get("url_private_download") or f.get("url_private")
                if not url or (f.get("size") or 0) > C.ATTACHMENT_MAX_BYTES:
                    continue
                path, ref = chat_channels.download_path(f"sl_{self.name}", f.get("name") or "file")
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as r:
                        if r.status != 200:
                            continue
                        with open(path, "wb") as out:
                            out.write(await r.read())
                    paths.append(ref)
                except Exception as e:
                    PrintStyle.error(f"Slack ({self.name}): file download failed: {e}")
        return paths

    # -- outgoing ----------------------------------------------------------

    async def _react(self, channel: str, ts: str, add: bool) -> None:
        if not ts:
            return
        try:
            if add:
                await self.web.reactions_add(channel=channel, timestamp=ts, name=C.WORKING_REACTION)
            else:
                await self.web.reactions_remove(channel=channel, timestamp=ts, name=C.WORKING_REACTION)
        except Exception:
            pass  # missing reactions:write scope or already removed

    async def _post(self, channel: str, thread_ts: str, text: str) -> None:
        for chunk in chat_channels.split_text(to_mrkdwn(text), C.MESSAGE_LIMIT):
            await self.web.chat_postMessage(channel=channel, text=chunk, thread_ts=thread_ts or None,
                                            unfurl_links=False, unfurl_media=False)

    async def _reply(self, channel: str, thread_ts: str, message_ts: str, text: str, attachments: list[str]) -> None:
        if text:
            await self._post(channel, thread_ts, text)
        for path in attachments:
            if os.path.isfile(path) and os.path.getsize(path) <= C.ATTACHMENT_MAX_BYTES:
                await self.web.files_upload_v2(channel=channel, file=path, filename=os.path.basename(path),
                                               thread_ts=thread_ts or None)
        await self._react(channel, message_ts, add=False)


def _key(name: str) -> str:
    return f"slack:{name}"


def current_cfg(name: str) -> dict:
    from helpers import plugins

    for b in (plugins.get_plugin_config(C.PLUGIN_NAME) or {}).get("bots", []) or []:
        if b.get("name") == name:
            return b
    return {}


def get_bot(name: str) -> "SlackBot | None":
    return chat_channels.RUNNING.get(_key(name))


def sync(bots_cfg: list[dict]) -> None:
    """Start, restart or stop apps to match the config."""
    wanted = {b["name"]: b for b in bots_cfg
              if b.get("enabled") and b.get("name") and b.get("bot_token") and b.get("app_token")}
    chat_channels.sync_clients("slack", wanted, lambda c: (c.get("bot_token"), c.get("app_token")), SlackBot)


async def send_reply(context, text: str, attachments: list[str]) -> str:
    bot = get_bot(context.data.get(C.CTX_BOT, ""))
    if not bot or not bot.alive or bot.web is None:
        return "the Slack app is not running"
    try:
        await bot.thread.run(bot._reply(context.data.get(C.CTX_CHANNEL, ""), context.data.get(C.CTX_THREAD, ""),
                                        context.data.get(C.CTX_MESSAGE_TS, ""), text, attachments or []))
        return ""
    except Exception as e:
        return format_error(e)


def _slack_error(e: Exception) -> str:
    response = getattr(e, "response", None)
    try:
        return str(response.get("error")) if response is not None else str(e)
    except Exception:
        return str(e).splitlines()[0]


async def test_tokens(bot_token: str, app_token: str) -> tuple[bool, str]:
    from slack_sdk.web.async_client import AsyncWebClient

    msgs, ok = [], True
    try:
        auth = await AsyncWebClient(token=bot_token).auth_test()
        msgs.append(f"Bot token OK: {auth.get('user')} in workspace {auth.get('team')}.")
    except Exception as e:
        ok = False
        msgs.append(f"Bot token rejected ({_slack_error(e)}).")
    try:
        await AsyncWebClient().apps_connections_open(app_token=app_token)
        msgs.append("App-level token OK (Socket Mode).")
    except Exception as e:
        ok = False
        msgs.append(f"App-level token rejected ({_slack_error(e)}); it needs connections:write and Socket Mode turned on.")
    return ok, " ".join(msgs)
