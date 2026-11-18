"""Canonical data store for Arch V3 — never lose users/subs again.

Design:
- The CANONICAL copies of users.json / subs.json live as documents in the
  Logs channel (bot is admin there) — Telegram itself is the database,
  so no runner death, git race or push failure can ever wipe data.
- A tiny index (db/db_index.json) in the repo maps kind -> file_id via
  the GitHub Contents API (no git daemon, no rebases, no lost pushes).
- On boot the bot pulls the store docs; repo working copies stay as a
  readable snapshot fallback when the store is empty.

Every save function in snoser calls push_async(kind, text) fire-and-forget.
"""
import base64
import json
import logging
import os
import time
from pathlib import Path

import aiohttp

log = logging.getLogger("store")

_API = "https://api.github.com"
_CHAT: str | None = None
_BOT = None
_TOKEN = ""
_INDEX = {}          # kind -> {"file_id": str, "ts": float}
_last_push: dict[str, float] = {}
COOLDOWN = 30.0


def init(bot, token: str) -> None:
    """Resolve store chat + remember bot context. Safe to call anywhere."""
    global _CHAT, _BOT, _TOKEN
    _BOT = bot
    _TOKEN = token
    env = (os.getenv("LOGS_CHAT_ID") or "").strip()
    if env:
        _CHAT = env
        return
    try:
        f = Path(__file__).parent / "logs_chat.json"
        if f.exists():
            v = json.loads(f.read_text(encoding="utf-8"))
            if v.get("chat_id"):
                _CHAT = str(v["chat_id"])
    except Exception:
        pass


def _gh_headers() -> dict:
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    return {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    } if tok else {}


def _index_path() -> Path:
    return Path(__file__).parent / "db" / "db_index.json"


def _load_local_index() -> None:
    global _INDEX
    try:
        _INDEX = json.loads(_index_path().read_text(encoding="utf-8"))
    except Exception:
        _INDEX = {}


def enabled() -> bool:
    return bool(_CHAT and _BOT)


async def _gh_get_text(rel: str) -> str | None:
    h = _gh_headers()
    if not h:
        return None
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not repo:
        return None
    url = f"{_API}/repos/{repo}/contents/{rel}"
    try:
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url, headers=h, params={"ref": "main"}) as r:
                if r.status != 200:
                    return None
                j = await r.json(content_type=None)
                return base64.b64decode(j["content"]).decode("utf-8")
    except Exception as e:
        log.debug("gh_get_text %s: %s", rel, e)
        return None


async def _gh_put_text(rel: str, text: str, msg: str) -> bool:
    h = _gh_headers()
    if not h:
        return False
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not repo:
        return False
    content = base64.b64encode(text.encode("utf-8")).decode("ascii")
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=20)) as s:
                # fresh sha reads past any concurrent commits
                sha = None
                async with s.get(f"{_API}/repos/{repo}/contents/{rel}",
                                 headers=h, params={"ref": "main"}) as r:
                    if r.status == 200:
                        sha = (await r.json(content_type=None)).get("sha")
                    elif r.status != 404:
                        await asyncio_compat_sleep(2)
                        continue
                body: dict = {"message": msg, "content": content, "branch": "main"}
                if sha:
                    body["sha"] = sha
                async with s.put(f"{_API}/repos/{repo}/contents/{rel}",
                                 headers=h, json=body) as r2:
                    if r2.status in (200, 201):
                        return True
                    log.debug("gh_put %s -> %s", rel, r2.status)
        except Exception as e:
            log.debug("gh_put %s: %s", rel, e)
        await asyncio_compat_sleep(2)
    return False


async def asyncio_compat_sleep(sec: float) -> None:
    import asyncio
    await asyncio.sleep(sec)


async def _tg_send(kind: str, text: str) -> str | None:
    """Upload the canonical doc to the store chat; return its file_id."""
    from aiogram.types import BufferedInputFile
    try:
        msg = await _BOT.send_document(
            _CHAT,
            BufferedInputFile(text.encode("utf-8"), f"db_{kind}.json"),
            caption=f"db {kind} @ {time.strftime('%Y-%m-%d %H:%M:%S')}")
        doc = getattr(msg, "document", None)
        return getattr(doc, "file_id", None) if doc else None
    except Exception as e:
        log.warning("store send %s failed: %s", kind, e)
        return None


async def _tg_read(kind: str, file_id: str) -> str | None:
    try:
        f = await _BOT.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{_TOKEN}/{f.file_path}"
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    return (await r.content.read()).decode("utf-8", "replace")
    except Exception as e:
        log.warning("store read %s failed: %s", kind, e)
    return None


def merge_records(kind: str, local, doc):
    """Union of the local copy and the store doc. Never drops an entry.
    Returns None for shapes we do not know (plain overwrite stays)."""
    if not isinstance(local, dict) or not isinstance(doc, dict):
        return None
    if kind == "fsm":
        le = local.get("entries") or {}
        de = doc.get("entries") or {}
        if len(de) <= len(le):
            return local
        out = dict(doc)
        out["entries"] = {**de, **le}
        return out
    if kind == "subs":
        out = {}
        for src in (doc, local):
            for k, v in src.items():
                if not isinstance(v, dict):
                    continue
                cur = out.get(k)
                until = float(v.get("until") or 0)
                if cur is None:
                    out[k] = {**v, "until": until}
                else:
                    cur["until"] = max(float(cur.get("until") or 0), until)
                    for kk, vv in v.items():
                        if kk != "until":
                            cur.setdefault(kk, vv)
        return out
    out = {}
    for src in (doc, local):
        for k, v in src.items():
            if not isinstance(v, dict):
                continue
            cur = out.get(k)
            if cur is None:
                out[k] = dict(v)
                continue
            if (v.get("last_seen") or "") > (cur.get("last_seen") or ""):
                cur["last_seen"] = v.get("last_seen")
            if v.get("first_seen") and (
                    not cur.get("first_seen")
                    or v["first_seen"] < cur["first_seen"]):
                cur["first_seen"] = v["first_seen"]
            for kk in ("username", "name", "ref_by"):
                if not cur.get(kk) and v.get(kk):
                    cur[kk] = v[kk]
            refs = list(dict.fromkeys(
                (cur.get("refs") or []) + (v.get("refs") or [])))
            if refs:
                cur["refs"] = refs
            for kk in ("ref_grants", "deep_refs"):
                cur[kk] = max(int(cur.get(kk) or 0), int(v.get(kk) or 0))
            for kk, vv in v.items():
                cur.setdefault(kk, vv)
    return out


async def bootstrap(files: dict[str, Path]) -> None:
    """Restore canonical docs over the repo working copies on boot."""
    _load_local_index()
    if not enabled():
        log.info("store: no chat binding — repo files are canonical")
        return
    # remote index first (chat may outlive repo snapshots)
    remote = await _gh_get_text("db/db_index.json")
    if remote:
        try:
            remote_idx = json.loads(remote)
            if isinstance(remote_idx, dict):
                _INDEX.update(remote_idx)
        except Exception:
            pass
    for kind, path in files.items():
        fid = (_INDEX.get(kind) or {}).get("file_id")
        if not fid:
            log.info("store: %s not in index — seeding from repo copy", kind)
            try:
                push_async(kind, path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("store seed %s failed: %s", kind, e)
            continue
        text = await _tg_read(kind, fid)
        if text is None:
            # stale/foreign file_id (e.g. bot token switched) — the repo
            # copy is the best we have; re-seed the store from it
            log.warning("store: %s unreadable — re-seeding from repo copy",
                        kind)
            try:
                push_async(kind, path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("store reseed %s failed: %s", kind, e)
            continue
        try:
            doc = json.loads(text)
        except Exception:
            log.warning("store: %s corrupt — keeping repo copy", kind)
            continue
        try:
            local_txt = path.read_text(encoding="utf-8")
            local = json.loads(local_txt)
        except Exception:
            local_txt, local = "", None
        merged = merge_records(kind, local, doc)
        if merged is None:
            try:
                if local_txt.strip() != text.strip():
                    path.write_text(text, encoding="utf-8")
                    log.info("store: %s restored from Telegram store", kind)
            except Exception:
                path.write_text(text, encoding="utf-8")
                log.info("store: %s restored from Telegram store", kind)
            continue
        new_txt = json.dumps(merged, ensure_ascii=False, indent=1)
        if new_txt.strip() != local_txt.strip():
            path.write_text(new_txt, encoding="utf-8")
            log.info("store: %s merged %s local + %s store -> %s",
                     kind, len(local or {}), len(doc), len(merged))
        if len(merged) > len(doc):
            push_async(kind, new_txt, force=True)
            log.info("store: %s doc re-seeded from the merged copy", kind)


def push_async(kind: str, text: str, force: bool = False) -> None:
    """Fire-and-forget canonical write. Throttled per kind (force bypasses)."""
    if not enabled():
        return
    now = time.time()
    if not force and now - _last_push.get(kind, 0) < COOLDOWN:
        return
    _last_push[kind] = now
    try:
        loop = __import__("asyncio").get_running_loop()
        loop.create_task(_push_kind(kind, text))
    except Exception as e:
        log.debug("push_async %s: %s", kind, e)


async def _push_kind(kind: str, text: str) -> None:
    fid = await _tg_send(kind, text)
    if not fid:
        return
    _INDEX[kind] = {"file_id": fid, "ts": int(time.time())}
    idx_p = _index_path()
    try:
        idx_p.parent.mkdir(exist_ok=True)
        idx_p.write_text(json.dumps(_INDEX, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    except Exception:
        pass
    await _gh_put_text("db/db_index.json",
                       json.dumps(_INDEX, ensure_ascii=False, indent=1),
                       f"db index: {kind}")
