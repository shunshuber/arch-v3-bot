"""Session hygiene: log out every OTHER authorized session (other phones,
desktops, web apps) on each pooled account, keeping only the current
Telethon connection. Runs on GitHub Actions — local network blocks Telegram.

The connection itself goes through the session's sticky pinned proxy, so
the kick never registers a second IP on the account. The proxy pool is
re-validated here first: dead pinned proxies would silently kill the kick.

Skip list: 917066653092 (support account — stays untouched)."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, functions, errors  # noqa: E402

import snoser  # noqa: E402
from proxy_farmer import validate_proxy  # noqa: E402

EXCLUDE = {"917066653092"}


async def _live_proxies() -> list[tuple]:
    """Validate the pooled proxies against Telegram right now; keep only
    the ones that can actually carry a connection."""
    raw = snoser.load_proxies()
    if not raw:
        return []
    sem = asyncio.Semaphore(15)

    async def one(px: tuple) -> tuple | None:
        url = snoser.proxy_to_url(px)
        scheme = url.rsplit("://", 1)[0]
        async with sem:
            return px if await validate_proxy(url, scheme) else None

    live = [p for p in await asyncio.gather(*[one(p) for p in raw])
            if p is not None]
    return live


async def kick_one(sess: Path, proxies: list[tuple]) -> None:
    name = sess.stem
    if name in EXCLUDE:
        print(f"[KICK] SKIP   {name}  (excluded)", flush=True)
        return
    px = snoser.pin_for_session(name, proxies)
    try:
        client = TelegramClient(str(sess.with_suffix("")),
                                int(os.getenv("API_ID", "0")),
                                os.getenv("API_HASH", ""),
                                proxy=px)
        await asyncio.wait_for(client.connect(), timeout=20)
    except Exception as e:
        print(f"[KICK] ERROR  {name}  connect ({px[1] if px else 'direct'}): "
              f"{type(e).__name__}: {e}", flush=True)
        return
    try:
        if not await client.is_user_authorized():
            print(f"[KICK] DEAD   {name}  not authorized", flush=True)
            return
        auths = await client(functions.account.GetAuthorizationsRequest())
        foreign = [a for a in auths.authorizations
                   if not getattr(a, "current", False)]
        print(f"[KICK] {name}: {len(auths.authorizations)} auth(s) total, "
              f"{len(foreign)} foreign", flush=True)
        for a in foreign:
            try:
                await client(functions.account.ResetAuthorizationRequest(a.hash))
                dev = getattr(a, "device_model", "?")
                plat = getattr(a, "platform", "?")
                ip = getattr(a, "ip", "?")
                print(f"[KICK]   - kicked {dev} / {plat} / {ip}", flush=True)
            except errors.FloodWaitError as e:
                print(f"[KICK]   - flood {e.seconds}s on {a.hash}", flush=True)
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"[KICK]   - fail {type(e).__name__}: {e}", flush=True)
        if foreign:
            print(f"[KICK] CLEAN  {name}  foreign sessions logged out", flush=True)
        else:
            print(f"[KICK] CLEAN  {name}  was already the only session", flush=True)
    except Exception as e:
        print(f"[KICK] ERROR  {name}  {type(e).__name__}: {e}", flush=True)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> None:
    sessions = snoser.load_sessions()
    print(f"[KICK] pool: {len(sessions)} sessions", flush=True)
    proxies = await _live_proxies()
    print(f"[KICK] live proxies: {len(proxies)}/{len(snoser.load_proxies())}",
          flush=True)
    for s in sessions:
        await kick_one(s, proxies)
        await asyncio.sleep(1.5)   # gentle pacing between accounts


if __name__ == "__main__":
    asyncio.run(main())
