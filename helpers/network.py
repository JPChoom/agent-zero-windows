from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import socket
import struct
from urllib.parse import urljoin, urlparse

import requests


SAFE_HTTP_SCHEMES = frozenset({"http", "https"})
DEFAULT_FETCH_TIMEOUT = (3.05, 10.0)
DEFAULT_HTTP_USER_AGENT = "@mixedbread-ai/unstructured"


@dataclass(frozen=True)
class HttpFetchResult:
    url: str
    content: bytes
    content_type: str | None
    encoding: str | None


class UnsafeUrlError(ValueError):
    """Raised when a remote URL resolves to a non-public destination."""


def _build_request_headers() -> dict[str, str]:
    user_agent = (
        os.getenv("USER_AGENT")
        or os.getenv("user_agent")
        or DEFAULT_HTTP_USER_AGENT
    ).strip()
    return {"User-Agent": user_agent or DEFAULT_HTTP_USER_AGENT}


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def resolve_host_ips(hostname: str) -> tuple[ipaddress._BaseAddress, ...]:
    try:
        results = socket.getaddrinfo(
            hostname,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Unable to resolve hostname '{hostname}'") from exc

    ips: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for _family, _type, _proto, _canonname, sockaddr in results:
        address = sockaddr[0]
        if "%" in address:
            address = address.split("%", 1)[0]
        ip = ipaddress.ip_address(address)
        key = ip.compressed
        if key in seen:
            continue
        seen.add(key)
        ips.append(ip)

    if not ips:
        raise UnsafeUrlError(f"Hostname '{hostname}' did not resolve to an IP address")

    return tuple(ips)


def validate_public_http_url(url: str) -> tuple[ipaddress._BaseAddress, ...]:
    parsed = urlparse(url)

    if parsed.scheme not in SAFE_HTTP_SCHEMES:
        raise UnsafeUrlError("Only http:// and https:// URLs are supported")
    if not parsed.hostname:
        raise UnsafeUrlError("URL hostname is required")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeUrlError(f"Blocked local hostname '{hostname}'")

    ips = resolve_host_ips(hostname)
    blocked = [str(ip) for ip in ips if not ip.is_global]
    if blocked:
        raise UnsafeUrlError(
            f"Blocked non-public address resolution for '{hostname}': {', '.join(blocked)}"
        )

    return ips


def fetch_public_http_resource(
    url: str,
    *,
    max_bytes: int,
    max_redirects: int = 5,
    timeout: tuple[float, float] = DEFAULT_FETCH_TIMEOUT,
) -> HttpFetchResult:
    current_url = url
    session = requests.Session()
    session.trust_env = False

    for redirect_count in range(max_redirects + 1):
        validate_public_http_url(current_url)

        try:
            with session.get(
                current_url,
                stream=True,
                allow_redirects=False,
                headers=_build_request_headers(),
                timeout=timeout,
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError(
                            f"Remote URL redirect is missing a Location header: {current_url}"
                        )
                    if redirect_count >= max_redirects:
                        raise ValueError(
                            f"Remote URL exceeded redirect limit ({max_redirects}): {url}"
                        )
                    current_url = urljoin(current_url, location)
                    continue

                if response.status_code >= 400:
                    raise ValueError(
                        f"Remote URL returned HTTP {response.status_code}: {current_url}"
                    )

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = None
                    if declared_length is not None and declared_length > max_bytes:
                        raise ValueError(
                            f"Remote document exceeds max size {max_bytes} bytes: {current_url}"
                        )

                body = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError(
                            f"Remote document exceeds max size {max_bytes} bytes: {current_url}"
                        )

                return HttpFetchResult(
                    url=current_url,
                    content=bytes(body),
                    content_type=_normalize_content_type(
                        response.headers.get("Content-Type")
                    ),
                    encoding=response.encoding,
                )
        except requests.RequestException as exc:
            raise ValueError(
                f"Remote document fetch failed for {current_url}: {exc}"
            ) from exc

    raise ValueError(f"Remote URL exceeded redirect limit ({max_redirects}): {url}")


def is_loopback_address(address: str) -> bool:
    """Check whether *address* resolves to a loopback interface."""
    _checkers = {
        socket.AF_INET: lambda x: (
            struct.unpack("!I", socket.inet_aton(x))[0] >> (32 - 8)
        ) == 127,
        socket.AF_INET6: lambda x: x == "::1",
    }
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return _checkers[socket.AF_INET6](address)
    except socket.error:
        pass
    try:
        socket.inet_pton(socket.AF_INET, address)
        return _checkers[socket.AF_INET](address)
    except socket.error:
        pass
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            r = socket.getaddrinfo(address, None, family, socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        for fam, _, _, _, sockaddr in r:
            if not _checkers[fam](sockaddr[0]):
                return False
    return True
