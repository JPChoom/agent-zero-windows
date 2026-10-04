"""Refuse to send a host-bound secret anywhere but its own service.

Runs before _10_unmask_secrets substitutes real values for §§secret(KEY)
placeholders. A secret bound with a `# hosts: example.com` comment in the
secrets file (see helpers/secrets.py get_host_bindings) may only be used in
a tool call whose destinations are those hosts (or their subdomains):

- URL literals in the tool's string arguments (curl/requests/navigate...)
- for the browser tool without a URL argument (typing into the open page):
  the page the browser is currently on

If a bound secret is used and no destination can be determined at all, the
call is refused too - an unknown destination is exactly the case this guard
exists for. Unbound secrets are not restricted here.
"""

import re
from urllib.parse import urlparse

from helpers.errors import RepairableException
from helpers.extension import Extension
from helpers.secrets import ALIAS_PATTERN, get_secrets_manager

_URL_RE = re.compile(r"https?://[^\s\"'<>|&;)]+", re.IGNORECASE)


def _hosts_in(values) -> list[str]:
    hosts: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        for match in _URL_RE.finditer(value):
            try:
                host = (urlparse(match.group(0)).hostname or "").lower()
            except ValueError:
                continue
            if host and host not in hosts:
                hosts.append(host)
    return hosts


def _host_allowed(host: str, allowed: list[str]) -> bool:
    return any(host == a or host.endswith("." + a) for a in allowed)


class SecretDestinationGuard(Extension):
    FAIL_LOUD = True  # a crash here must not let the call through unchecked

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if not self.agent or not tool_args:
            return
        strings = [v for v in tool_args.values() if isinstance(v, str)]
        used = {m.group(1).upper() for s in strings for m in re.finditer(ALIAS_PATTERN, s)}
        if not used:
            return

        bindings = get_secrets_manager(self.agent.context).get_host_bindings()
        bound = {key: bindings[key] for key in used if key in bindings}
        if not bound:
            return

        hosts = _hosts_in(strings)
        if not hosts and tool_name == "browser":
            page_host = await self._browser_page_host(tool_args)
            if page_host:
                hosts = [page_host]

        for key, allowed in bound.items():
            if not hosts:
                raise RepairableException(
                    f"Secret {key} may only be sent to {', '.join(allowed)}, and the destination of this "
                    f"{tool_name} call could not be determined, so it was not run. Include the target URL "
                    "explicitly, or (browser) navigate to the right site first."
                )
            stray = [h for h in hosts if not _host_allowed(h, allowed)]
            if stray:
                raise RepairableException(
                    f"Secret {key} may only be sent to {', '.join(allowed)}; this {tool_name} call also "
                    f"targets {', '.join(stray)}, so it was not run."
                )

    async def _browser_page_host(self, tool_args: dict) -> str:
        try:
            from plugins._browser.helpers.runtime import get_runtime

            runtime = await get_runtime(self.agent.context.id, create=False)
            if runtime is None:
                return ""
            state = await runtime.call("state", tool_args.get("browser_id"))
            url = (state or {}).get("currentUrl") or (state or {}).get("url") or ""
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""
