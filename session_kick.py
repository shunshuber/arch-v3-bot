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
import time
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
    raw = snoser.load_pin_proxies()
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
    # warm-up: freshly pinned/re-pinned sessions rest for a day before
    # hygiene ops — GetAuthorizations from a new IP on a young pin looks
    # like a hijack probe and Telegram sweeps the account for it
    entry = snoser._load_pins().get(name, {})
    since = entry.get("since") or 0
    age_h = (time.time() - since) / 3600
    if since and age_h < 24 and os.getenv("KICK_FORCE", "") != "1":
        print(f"[KICK] WARMUP {name}  pin age {age_h:.1f}h < 24h — skip "
              f"(KICK_FORCE=1 to override)", flush=True)
        return
    try:
        fp = snoser.session_fingerprint(name)
        client = TelegramClient(str(sess.with_suffix("")),
                                fp["api_id"], fp["api_hash"],
                                proxy=px, device_model=fp["device"],
                                system_version=fp["system_version"],
                                app_version=fp["app_version"],
                                lang_code=fp["lang_code"])
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
        # never kick our own pool sessions/twins (same account, other
        # api_id/device) — the twin is the watchdog's revive channel
        keep_devs = set()
        for s in snoser.load_sessions():
            sfp = snoser.session_fingerprint(s.stem)
            keep_devs.add(sfp["device"])
        foreign = []
        for a in auths.authorizations:
            if getattr(a, "current", False):
                continue
            if getattr(a, "device_model", "") in keep_devs:
                print(f"[KICK] KEEP   {getattr(a, 'device_model', '?')} "
                      f"(pool session/twin)", flush=True)
                continue
            foreign.append(a)
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
    print(f"[KICK] live proxies: {len(proxies)}/{len(snoser.load_pin_proxies())}",
          flush=True)
    for s in sessions:
        await kick_one(s, proxies)
        await asyncio.sleep(1.5)   # gentle pacing between accounts


if __name__ == "__main__":
    asyncio.run(main())
