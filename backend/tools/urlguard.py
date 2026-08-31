"""Shared URL validation and SSRF-safe fetching for scraper tools.

Substring checks like `"espn.com" in url` pass for
`http://169.254.169.254/?x=espn.com`, and auto-followed redirects can land
anywhere. Every scraper fetch goes through safe_get, which:

- parses with urlparse and requires an http(s) scheme,
- matches the hostname against an explicit domain allowlist
  (exact match or dot-suffix, never substring),
- rejects literal IP hostnames, which also blocks private and
  link-local ranges such as 169.254.0.0/16 and 10.0.0.0/8,
- follows redirects manually, re-validating every hop.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import httpx

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    pass


def is_allowed_url(url: str, allowed_domains: set[str] | list[str]) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return False  # literal IPs are never in the domain allowlist
    except ValueError:
        pass
    return any(hostname == d or hostname.endswith("." + d) for d in allowed_domains)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    allowed_domains: set[str] | list[str],
    headers: dict | None = None,
) -> httpx.Response:
    """GET with manual redirect following; every hop must pass the allowlist."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_allowed_url(current, allowed_domains):
            raise UnsafeURLError(f"URL failed allowlist check: {current}")
        response = await client.get(current, headers=headers, follow_redirects=False)
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            if not location:
                return response
            current = str(httpx.URL(current).join(location))
            continue
        return response
    raise UnsafeURLError(f"Too many redirects starting from: {url}")
