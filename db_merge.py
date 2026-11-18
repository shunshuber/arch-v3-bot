"""Union-merge the Telegram store docs into the repo copies.

Why: the store doc used to overwrite the repo file on boot, so a stale doc
silently deleted fresh users/subs. This script reads BOTH sides, merges them
without dropping anything, writes the result back to the repo and re-seeds
the store doc when the repo copy is richer.

usage: python db_merge.py            # report only
       python db_merge.py --apply    # write files + re-seed the store doc
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from aiogram import Bot

import store

REPO = Path(__file__).parent
KINDS = {"users": REPO / "users.json", "subs": REPO / "subs.json"}


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


async def main() -> int:
    apply = "--apply" in sys.argv
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        print("BOT_TOKEN missing")
        return 2
    bot = Bot(token=token)
    store.init(bot, token)
    if not store.enabled():
        print("store disabled (LOGS_CHAT_ID missing)")
        return 2
    store._load_local_index()
    remote = await store._gh_get_text("db/db_index.json")
    if remote:
        try:
            store._INDEX.update(json.loads(remote))
        except Exception:
            pass
    rc = 0
    for kind, path in KINDS.items():
        local = load(path)
        fid = (store._INDEX.get(kind) or {}).get("file_id")
        doc = None
        if fid:
            text = await store._tg_read(kind, fid)
            if text:
                try:
                    doc = json.loads(text)
                except Exception:
                    doc = None
        print(f"{kind}: repo={len(local or {})} store={len(doc or {})}")
        if doc is None:
            print(f"{kind}: store doc unreadable — repo copy kept")
            rc = 1
            continue
        merged = store.merge_records(kind, local or {}, doc) or doc
        grew = len(merged) - len(local or {})
        print(f"{kind}: merged={len(merged)} (recovered {grew})")
        if not apply:
            continue
        txt = json.dumps(merged, ensure_ascii=False, indent=1)
        if txt.strip() != (json.dumps(local, ensure_ascii=False, indent=1).strip()
                           if local is not None else ""):
            path.write_text(txt, encoding="utf-8")
            print(f"{kind}: written")
        if len(merged) > len(doc):
            await store._push_kind(kind, txt)
            print(f"{kind}: store doc re-seeded ({len(doc)} -> {len(merged)})")
    await bot.session.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
