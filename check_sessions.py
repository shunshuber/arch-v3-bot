"""Check all real sessions: connectivity + authorization + identity."""
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")


async def check(session_path: Path) -> None:
    client = TelegramClient(
        str(session_path.with_suffix("")), API_ID, API_HASH
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(f"❌ {session_path.stem}  not authorized")
            return
        me = await client.get_me()
        print(f"✅ {session_path.stem}  phone={me.phone} user={me.username} "
              f"name={me.first_name} prem={'yes' if me.premium else 'no'}")
    except Exception as e:
        print(f"💀 {session_path.stem}  {type(e).__name__}: {e}")
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
    # sequential to avoid DC rate limits on check
    for s in sessions:
        await check(s)


if __name__ == "__main__":
    asyncio.run(main())
