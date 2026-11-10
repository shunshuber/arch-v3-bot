"""Session hygiene: log out every OTHER authorized session (other phones,
desktops, web apps) on each pooled account, keeping only the current
Telethon connection. Runs on GitHub Actions — local network blocks Telegram.

The connection itself goes through the session's sticky pinned proxy, so
the kick never registers a second IP on the account.

Skip list: 917066653092 (support account — stays untouched)."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, functions, errors  # noqa: E402

import snoser  # noqa: E402

EXCLUDE = {"917066653092"}


async def kick_one(sess: Path) -> None:
    name = sess.stem
    if name in EXCLUDE:
        print(f"[KICK] SKIP   {name}  (excluded)", flush=True)
        return
    proxies = snoser.load_proxies()
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
        # terminates every OTHER session; the current connection survives
        await client(functions.account.ResetAuthorizationsRequest())
        print(f"[KICK] CLEAN  {name}  all foreign sessions logged out", flush=True)
    except errors.FloodWaitError as e:
        print(f"[KICK] FLOOD  {name}  wait {e.seconds}s", flush=True)
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
    for s in sessions:
        await kick_one(s)
        await asyncio.sleep(1.5)   # gentle pacing between accounts


if __name__ == "__main__":
    asyncio.run(main())
