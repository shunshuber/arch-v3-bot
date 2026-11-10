"""Arch V3 — resolve proxy tuples from strings loaded from proxies.txt.

Many proxies in file are `socks5://host:port` (free) or `host:port:user:pass`
(user-dumped). We convert either format to (type, host, port, rdns, user, pwd).
"""

import os
from urllib.parse import urlparse
import python_socks as _ps

PROXY_TYPE_MAP = {
    "socks5": _ps.ProxyType.SOCKS5,
    "socks4": _ps.ProxyType.SOCKS4,
    "http":   _ps.ProxyType.HTTP,
}


def parse_proxy_string(raw: str) -> tuple | None:
    """Returns python_socks-compatible tuple or None."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" in raw:
        # full url — parse scheme
        try:
            p = urlparse(raw)
            scheme = p.scheme.lower()
            if scheme not in PROXY_TYPE_MAP:
                return None
            host = p.hostname
            port = p.port or 1080
            user = p.username
            pwd = p.password
            if not host:
                return None
            return (PROXY_TYPE_MAP[scheme], host, port, True, user, pwd)
        except Exception:
            return None
    # format host:port:user:pass or host:port
    parts = raw.replace("\"", "").strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        try:
            return (_ps.ProxyType.SOCKS5, host.strip(), int(port.strip()),
                    True, user.strip() or None, pwd.strip() or None)
        except ValueError:
            return None
    if len(parts) == 2:
        try:
            return (_ps.ProxyType.SOCKS5, parts[0].strip(), int(parts[1].strip()), True, None, None)
        except ValueError:
            return None
    return None
