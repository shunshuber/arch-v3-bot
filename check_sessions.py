"""Check all real sessions: connectivity + authorization + identity.

Discipline (BL-style soft probe):
- "not authorized"  -> DEAD (server-side revoke — real, remove from pool)
- timeout/error     -> SUSPECT (transient; only repeated suspects over
                       several runs may be soft-removed — never delete on
                       a single flaky proxy)
Probes run through each session's sticky pinned proxy and ITS OWN
pinned fingerprint so probers look like the bot itself.

Hygiene: every session connects through its sticky pinned proxy — a check
from a runner IP would register a second IP on the account."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import snoser  # noqa: E402

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
STATUS_FILE = ROOT / "session_status.json"


def _load_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def check(session_path: Path, status: dict) -> None:
    name = session_path.stem
    proxies = snoser.load_proxies()
    px = snoser.pin_for_session(name, proxies)
    fp = snoser.session_fingerprint(name)
    client = TelegramClient(
        str(session_path.with_suffix("")), fp["api_id"], fp["api_hash"],
        proxy=px, device_model=fp["device"],
        system_version=fp["system_version"], app_version=fp["app_version"],
        lang_code=fp["lang_code"])
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await client.is_user_authorized():
            print(f"❌ {name}  not authorized")
            status["dead"] = sorted(set(status.get("dead", []) + [name]))
            status["suspect"] = [s for s in status.get("suspect", []) if s != name]
            return
        me = await client.get_me()
        via = px[1] if px else "direct"
        print(f"✅ {name}  phone={me.phone} user={me.username} "
              f"name={me.first_name} prem={'yes' if me.premium else 'no'} "
              f"ip={via}")
        if name in status.get("suspect", []):
            status["suspect"] = [s for s in status["suspect"] if s != name]
            print(f"♻️ {name}  suspect flag cleared")
    except Exception as e:
        print(f"⚠️ {name}  {type(e).__name__}: {e}")
        if name not in status.get("suspect", []):
            status["suspect"] = status.get("suspect", []) + [name]
        print(f"⚠️ {name}  suspect count: {status['suspect'].count(name)}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> None:
    sessions = sorted(ROOT.glob("sessions/*.session"))
    if not sessions:
        print("no sessions found")
        return
    status = _load_status()
    for s in sessions:
        await check(s, status)
    status.setdefault("updated", []).append(
        time.strftime("%Y-%m-%dT%H:%M:%S"))
    status["updated"] = status["updated"][-5:]
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print("[CHECK] suspect:", status.get("suspect", []))
    print("[CHECK] dead:", status.get("dead", []))


if __name__ == "__main__":
    asyncio.run(main())
