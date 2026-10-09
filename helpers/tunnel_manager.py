import json
import os
import threading
import time
from collections import deque

from flaredantic import NotifyData, NotifyEvent, notifier

from helpers import files
from helpers.cloudflare_tunnel import CloudflareTunnel
from helpers.microsoft_tunnel import MicrosoftDevTunnel
from helpers.print_style import PrintStyle
from helpers.serveo_tunnel import ServeoTunnelHelper
from helpers.tailscale_tunnel import TailscaleTunnel
from helpers.tunnel_common import event_value


SUPPORTED_TUNNEL_PROVIDERS = {
    "cloudflared",
    "microsoft",
    "serveo",
    "tailscale",
}
TUNNEL_PROVIDER_ALIASES = {
    "cloudflare": "cloudflared",
    "cloudflare_tunnel": "cloudflared",
    "cloudflare-tunnel": "cloudflared",
    "tailscale_funnel": "tailscale",
    "tailscale-funnel": "tailscale",
}


HANDOVER_FILE = "usr/tunnel_handover.json"
# Only cloudflared is known to keep serving after the process that started it
# exits (a restart replaces the server process; the tunnel is its child).
HANDOVER_PROVIDERS = {"cloudflared"}


class AdoptedTunnel:
    """A tunnel process started by the previous server process and taken over
    after a restart, so the remote address stays the same."""

    def __init__(self, pid: int, create_time: float, url: str):
        self.pid = pid
        self.create_time = create_time
        self.tunnel_url = url

    def stop(self):
        import psutil

        try:
            proc = psutil.Process(self.pid)
            if abs(proc.create_time() - self.create_time) < 1:
                proc.terminate()
        except psutil.Error:
            pass
        self.tunnel_url = None
        return True


def _tunnel_process(tunnel):
    """The subprocess.Popen behind a running tunnel helper, if there is one."""
    inner = getattr(tunnel, "tunnel", None)
    return getattr(inner, "tunnel_process", None)


def normalize_provider(provider):
    normalized = (provider or "serveo").strip().lower()
    normalized = TUNNEL_PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_TUNNEL_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_TUNNEL_PROVIDERS))
        raise ValueError(
            f"Unsupported remote control provider '{provider}'. Choose one of: {supported}."
        )
    return normalized


# Singleton to manage the tunnel instance
class TunnelManager:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.tunnel = None
        self.tunnel_url = None
        self.is_running = False
        self.provider = None
        self.notifications = deque(maxlen=50)
        self._subscribed = False

    def _on_notify(self, data: NotifyData):
        """Handle notifications from flaredantic."""
        self.notifications.append({
            "event": data.event.value,
            "message": data.message,
            "data": data.data,
        })

    def _ensure_subscribed(self):
        """Subscribe to flaredantic notifications if not already."""
        if not self._subscribed:
            notifier.subscribe(self._on_notify)
            self._subscribed = True

    def get_notifications(self):
        """Get and clear pending notifications."""
        notifications = list(self.notifications)
        self.notifications.clear()
        return notifications

    def get_last_error(self):
        """Check for recent error in notifications without clearing."""
        for notification in reversed(list(self.notifications)):
            if notification["event"] == NotifyEvent.ERROR.value:
                return notification["message"]
        return None

    def _append_notification(self, event, message, data=None):
        self.notifications.append({
            "event": event_value(event),
            "message": message,
            "data": data,
        })

    def _create_tunnel(self, port, provider):
        if provider == "cloudflared":
            return CloudflareTunnel(port, notify=self._append_notification)
        if provider == "microsoft":
            return MicrosoftDevTunnel(port, notify=self._append_notification)
        if provider == "tailscale":
            return TailscaleTunnel(port, notify=self._append_notification)
        return ServeoTunnelHelper(port, notify=self._append_notification)

    def start_tunnel(self, port=80, provider="serveo"):
        """Start a new tunnel or return the existing one's URL."""
        if self.is_running and self.tunnel_url:
            return self.tunnel_url

        self._ensure_subscribed()
        self.notifications.clear()
        try:
            self.provider = normalize_provider(provider)
        except Exception as e:
            error_msg = str(e)
            PrintStyle.error(f"Error starting tunnel: {error_msg}")
            self._append_notification(NotifyEvent.ERROR, error_msg)
            return None

        try:
            # Start tunnel in a separate thread to avoid blocking.
            def run_tunnel():
                try:
                    self.tunnel = self._create_tunnel(port, self.provider)
                    self.tunnel.start()
                    self.tunnel_url = self.tunnel.tunnel_url
                    self.is_running = True
                except Exception as e:
                    error_msg = str(e)
                    PrintStyle.error(f"Error in tunnel thread: {error_msg}")
                    self._append_notification(NotifyEvent.ERROR, error_msg)

            tunnel_thread = threading.Thread(target=run_tunnel)
            tunnel_thread.daemon = True
            tunnel_thread.start()

            # No timeout: Microsoft login can legitimately require user interaction.
            while True:
                if self.tunnel_url:
                    break
                if any(n["event"] == NotifyEvent.ERROR.value for n in self.notifications):
                    break
                if not tunnel_thread.is_alive():
                    break
                time.sleep(0.1)

            return self.tunnel_url
        except Exception as e:
            PrintStyle.error(f"Error starting tunnel: {str(e)}")
            return None

    def stop_tunnel(self):
        """Stop the running tunnel."""
        if self.tunnel and self.is_running:
            try:
                self.tunnel.stop()
                self.is_running = False
                self.tunnel_url = None
                self.provider = None
                return True
            except Exception:
                return False
        return False

    def get_tunnel_url(self):
        """Get the current tunnel URL if available."""
        return self.tunnel_url if self.is_running else None

    # ------------------------------------------------------------ restart hand-over

    def write_handover(self, port) -> bool:
        """Record the running tunnel just before this process restarts, so the
        next process can take it over instead of leaving it untracked."""
        if not (self.is_running and self.tunnel_url and self.provider in HANDOVER_PROVIDERS):
            return False
        if isinstance(self.tunnel, AdoptedTunnel):
            pid, create_time = self.tunnel.pid, self.tunnel.create_time
        else:
            process = _tunnel_process(self.tunnel)
            if process is None or process.poll() is not None:
                return False
            import psutil

            pid = process.pid
            create_time = psutil.Process(pid).create_time()
        payload = {
            "provider": self.provider, "url": self.tunnel_url, "pid": pid,
            "create_time": create_time, "port": int(port),
        }
        path = files.get_abs_path(HANDOVER_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return True

    def adopt_handover(self, port) -> str | None:
        """Take over the tunnel the previous process recorded, if it is still
        the same cloudflared process forwarding to this port. One-shot: the
        record is deleted whether or not it is adopted."""
        path = files.get_abs_path(HANDOVER_FILE)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if self.is_running or data.get("provider") not in HANDOVER_PROVIDERS:
            return None
        import psutil

        try:
            proc = psutil.Process(int(data["pid"]))
            same_process = abs(proc.create_time() - float(data["create_time"])) < 1
            is_cloudflared = proc.name().lower().startswith("cloudflared")
            forwards_here = f"localhost:{int(port)}" in " ".join(proc.cmdline())
        except (psutil.Error, KeyError, TypeError, ValueError):
            return None
        if not (same_process and is_cloudflared and forwards_here and int(data.get("port", -1)) == int(port)):
            return None
        self.tunnel = AdoptedTunnel(proc.pid, float(data["create_time"]), str(data["url"]))
        self.tunnel_url = str(data["url"])
        self.provider = data["provider"]
        self.is_running = True
        self._append_notification(NotifyEvent.TUNNEL_URL, "Remote Control kept running across the restart", {"url": self.tunnel_url})
        PrintStyle.standard(f"Remote Control tunnel kept across restart: {self.tunnel_url}")
        return self.tunnel_url
