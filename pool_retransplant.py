# language: Python 3.11, file: pool_retransplant.py, target: GitHub Actions ubuntu-latest
"""One pass over the pool: every plain `sessions/*.session` gets a `_new`
child through the same QR transplant the lolz worker uses.

The source is never logged out. A child born from AcceptLoginToken dies with
the session that confirmed the token, so the plain source is archived in
lolz/_done and only then leaves the active pool. A failed source stays in the
pool exactly as it was.
"""
import asyncio
import os
import shutil
import time
from pathlib import Path

import snoser

ROOT = Path(__file__).parent
POOL = ROOT / "sessions"
KEEP = snoser.TRANSPLANT_KEEP
DONE = snoser.TRANSPLANT_DONE
HOLD_SEC = 2 * 3600


def pool_sources() -> list[str]:
    explicit = {s.strip() for s in
                (os.getenv("POOL_STEMS") or "").split(",") if s.strip()}
    out = []
    for p in sorted(POOL.glob("*.session")):
        stem = p.stem
        if stem.endswith("_new"):
            continue
        if stem in snoser.TRANSPLANT_EXCLUDE_STEMS:
            continue
        if explicit and stem not in explicit:
            continue
        out.append(stem)
    return out


async def _noop(*_a, **_k) -> None:
    return None


async def _fake_log(title: str, lines: list[str]) -> None:
    print(f"[LOG] {title}", flush=True)
    for line in lines:
        print("    " + line, flush=True)


async def hold_sources(stems: list[str]) -> bool:
    """Copy every source into lolz/_keep and push a 2h queue hold, so the
    bot worker cannot start the same account from another runner."""
    now = time.time()
    q = snoser._queue_load()
    ages = snoser._age_load()
    KEEP.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        src = POOL / f"{stem}.session"
        if not src.exists():
            continue
        shutil.copy2(src, KEEP / src.name)
        ages[stem] = int(now - snoser.TRANSPLANT_MIN_AGE_SEC - 60)
        entry = q.get(stem) or {"tries": 0}
        entry["next_try"] = now + HOLD_SEC
        q[stem] = entry
    snoser._queue_save(q)
    snoser._age_save(ages)
    return await snoser._persist_paths(
        ["lolz_queue.json", "lolz_age.json"], "pool transplant: hold")


async def swap_source(stem: str) -> bool:
    """The child is already in the pool. Move the plain source to _done and
    delete it from the active pool — never log it out."""
    child = POOL / f"{stem}_new.session"
    src = POOL / f"{stem}.session"
    if not child.exists() or not src.exists():
        print(f"[POOL] {stem}: no child/source on disk — kept as is",
              flush=True)
        return False
    DONE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(DONE / src.name))
    rels = [f"sessions/{stem}.session", f"lolz/_done/{stem}.session"]
    meta = POOL / f"{stem}.json"
    if meta.exists():
        shutil.move(str(meta), str(DONE / meta.name))
        rels += [f"sessions/{stem}.json", f"lolz/_done/{stem}.json"]
    return await snoser._persist_paths(
        rels, f"pool: {stem} replaced by {stem}_new")


async def main() -> int:
    snoser.push_send_log = _fake_log
    snoser.notify_admin_ready = _noop

    stems = pool_sources()
    print(f"[POOL] plain sources: {len(stems)}", flush=True)
    for stem in stems:
        print(f"  - {stem}", flush=True)
    if os.getenv("POOL_DRY", "0") == "1":
        print("🟢 Успешно: 0", flush=True)
        print("🔴 Ошибки: 0", flush=True)
        return 0
    if not stems:
        print("🟢 Успешно: 0", flush=True)
        print("🔴 Ошибки: 0", flush=True)
        return 0

    if not await hold_sources(stems):
        print("[POOL] queue hold push failed — abort", flush=True)
        print("🟢 Успешно: 0", flush=True)
        print(f"🔴 Ошибки: {len(stems)}", flush=True)
        return 1

    ok: list[str] = []
    fail: list[str] = []
    for i, stem in enumerate(stems, 1):
        print(f"[POOL] {i}/{len(stems)} start {stem}", flush=True)
        try:
            res = await snoser._transplant_one(KEEP / stem)
        except Exception as e:
            print(f"[POOL] {stem} crashed: {type(e).__name__}: {e}",
                  flush=True)
            res = False
        (ok if res else fail).append(stem)
        print(f"[POOL] {stem}: {'ok' if res else 'fail'}", flush=True)

    moved = await snoser.add_ready_to_pool()
    print(f"[POOL] added to pool: {moved}", flush=True)

    replaced: list[str] = []
    for stem in ok:
        try:
            if await swap_source(stem):
                replaced.append(stem)
        except Exception as e:
            print(f"[POOL] {stem} swap failed: {type(e).__name__}: {e}",
                  flush=True)

    q = snoser._queue_load()
    for stem in ok:
        q.pop(stem, None)
    for stem in fail:
        if (KEEP / f"{stem}.session").exists():
            entry = q.get(stem) or {"tries": 0}
            entry["tries"] = int(entry.get("tries") or 0) + 1
            entry["next_try"] = time.time() + snoser.TRANSPLANT_RETRY_SEC
            entry["last_try"] = int(time.time())
            q[stem] = entry
        else:
            q.pop(stem, None)
    snoser._queue_save(q)
    await snoser._persist_paths(["lolz_queue.json"],
                                "pool transplant: results")

    bad = len(stems) - len(replaced)
    esc = snoser.html_mod.escape
    lines = [f"✅ <code>{esc(s)}_new</code> → пул" for s in replaced]
    lines += [f"❌ <code>{esc(s)}</code> — источник остался в пуле"
              for s in stems if s not in replaced]
    lines += ["", f"🟢 Успешно: {len(replaced)}", f"🔴 Ошибки: {bad}"]
    try:
        await snoser._admin_send(
            snoser.bq(f"<b>{snoser.NAME}</b> · 🧬 Пересадка пула")
            + "\n\n" + "\n".join(lines))
    except Exception as e:
        print(f"[POOL] admin notify failed: {e}", flush=True)

    print(f"🟢 Успешно: {len(replaced)}", flush=True)
    print(f"🔴 Ошибки: {bad}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
