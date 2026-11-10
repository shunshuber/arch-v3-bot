"""Arch V3 — auto proxy harvester + validator.

Sources: multiple free GitHub proxy lists, scraped fresh every time we spawn.
Successful combined after validation against Telegram (api.telegram.org:443
through socks5 connection).

Output: proxies.txt (one `socks5://host:port` per line).
The bot picks from this file on start and rotates sendcode calls per session.
"""

import asyncio
import os
import random
import re
import ssl
import sys
import io
import time
from pathlib import Path

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType

BASE = Path(__file__).parent
PROXIES_FILE = BASE / "proxies.txt"

# ── free proxy sources (updated actively on github) ─────
SOURCES = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/BLACK-SCORP10/ProxyList/main/socks5.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
    "https://raw.githubusercontent.com/npmrun/proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/casjay/hosts/main/proxies/socks5",
    "https://raw.githubusercontent.com/Oxigine/proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/Vannik/proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
]

REQUIRED_WORKING = 20   # minimum usable proxies we want


def parse_host_port(line: str) -> tuple[str, int] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "//" in line:
        line = line.split("//", 1)[1]
    if "@" in line:
        line = line.rsplit("@", 1)[1]
    parts = line.replace("\"", "").strip().split(":")
    if len(parts) != 2:
        return None
    host = parts[0].strip()
    try:
        port = int(parts[1].strip())
    except ValueError:
        return None
    if not host or not (1 < port < 65536):
        return None
    return host, port


def scheme_of(line: str) -> str:
    low = line.lower()
    if low.startswith("socks4://"):
        return "socks4"
    if low.startswith("http://"):
        return "http"
    return "socks5"


async def fetch_source(sess, url: str) -> list[str]:
    try:
        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=25), ssl=False) as r:
            if r.status != 200:
                return []
            body = await r.text()
            return [l.strip() for l in body.splitlines() if l.strip()]
    except Exception:
        return []


async def harvest() -> list[tuple[str, str]]:
    """Returns list of (proxy_url, scheme). Deduplicates."""
    async with aiohttp.ClientSession() as sess:
        chunks = await asyncio.gather(*[fetch_source(sess, u) for u in SOURCES])
    flat = []
    for c in chunks:
        flat.extend(c)
    seen = set()
    parsed = []
    for line in flat:
        hp = parse_host_port(line)
        if hp is None:
            continue
        key = f"{hp[0]}:{hp[1]}"
        if key in seen:
            continue
        seen.add(key)
        scheme = scheme_of(line)
        parsed.append((f"{scheme}://{key}", scheme))
    print(f"harvested {len(parsed)} unique proxies from {len(SOURCES)} sources")
    return parsed


async def validate_proxy(proxy_url: str, scheme: str) -> bool:
    """Test each proxy the way sessions actually use it: a real MTProto
    handshake with a Telegram DC over Telethon (throwaway unauthenticated
    session). A plain HTTPS GET to api.telegram.org is NOT enough — free
    proxies often pass that but die on the MTProto tunnel, killing every
    session that gets pinned to them."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    api_id = int(os.getenv("API_ID", "0") or 0)
    api_hash = os.getenv("API_HASH", "")
    try:
        from snoser import parse_proxy
        px = parse_proxy(proxy_url)
    except Exception:
        px = None
        m = re.match(r"(?:socks5|socks4|http)://(?:[^@/]+@)?([\w.\-]+):(\d+)",
                     proxy_url)
        if m:
            ptype = ProxyType.SOCKS5 if scheme.startswith("socks5") else (
                ProxyType.SOCKS4 if scheme.startswith("socks4") else ProxyType.HTTP)
            px = (ptype, m.group(1), int(m.group(2)), True, None, None)
    if px is None:
        return False
    if not api_id or not api_hash:
        return await _http_probe(proxy_url, scheme)
    client = TelegramClient(StringSession(), api_id, api_hash, proxy=px)
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        return client.is_connected()
    except Exception:
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _http_probe(proxy_url: str, scheme: str) -> bool:
    """Cheap fallback probe when API creds are absent (HTTP GET only)."""
    conn = ProxyConnector.from_url(proxy_url) if scheme in ("socks5", "socks4") else None
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        if conn:
            async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
                async with s.get("https://api.telegram.org", ssl=False) as r:
                    return r.status in (200, 301, 302, 307, 308)
        hostport = proxy_url.rsplit("://", 1)[1]
        p = f"http://{hostport}"
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get("https://api.telegram.org", proxy=p, ssl=False) as r:
                return r.status in (200, 301, 302, 307, 308)
    except Exception:
        return False


async def harvest_and_validate(need: int = REQUIRED_WORKING) -> list[str]:
    all_proxies = await harvest()
    # try all of them concurrently, chunked
    working = []
    chunk_size = 50
    for i in range(0, len(all_proxies), chunk_size):
        chunk = all_proxies[i:i + chunk_size]
        results = await asyncio.gather(*[validate_proxy(u, s) for u, s in chunk])
        for (u, s), ok in zip(chunk, results):
            if ok:
                working.append(u)
            if len(working) >= need:
                break
        if len(working) >= need:
            break
    print(f"working: {len(working)} proxies (need {need})")
    return working


async def write_proxy_file(working: list[str]) -> None:
    if not working:
        return
    with io.open(PROXIES_FILE, "w", encoding="utf-8") as f:
        for p in working:
            f.write(p + "\n")
    print(f"wrote {len(working)} proxies to {PROXIES_FILE.name}")


# allow standalone run
async def run():
    proxies = await harvest_and_validate()
    await write_proxy_file(proxies)


if __name__ == "__main__":
    asyncio.run(run())
