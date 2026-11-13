"""Session watchdog: dual-session self-healing pool (friend-spec system).

Every account in the pool is meant to hold TWO session files made with
DIFFERENT api_id/api_hash (Telegram sees two separate "apps"). A watchdog
pings every session through its pinned proxy every ~5 minutes:

  alive  -> ok, register account phone
  dead   -> revive: send_code_request on the account, receive the login
            code via the SECOND (still alive) session (Telegram pushes it
            into the service chat, user 777000), sign in under the dead
            session's OWN api pair, save a fresh .session file into the
            pool (sessions/), update session_status.json.

Bootstrap: an account that has ONE live slot and no second slot gets its
twin auto-created the same way (code received via the live session).

2FA: stored in sessions/<name>.json "twoFA" field; if the revive hits a
password wall and no password is stored, the slot is marked suspect and
left for a manual run.
"""
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from telethon import TelegramClient, errors, events  # noqa: E402

import snoser  # noqa: E402

SLOTS_FILE = ROOT / "session_slots.json"
TWIN_SUFFIX = "_t"
SERVICE_ID = 777000          # "Telegram" service chat, login code delivery
CODE_TIMEOUT = 90            # seconds to wait for the login code
BOOTSTRAP_COOLDOWN = 6 * 3600
REVIVE_COOLDOWN = 30 * 60    # after a failed revive, back off per account
TWIN_EXCLUDE = {"917066653092"}  # support account stays single-slot
CODE_RE = re.compile(r"(?:code|код|login|вход|пароль)[^\d]{0,25}(\d{4,6})", re.I)


# ── registry ─────────────────────────────────────────────────────────
def _slots_load() -> dict:
    try:
        return json.loads(SLOTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "accounts": {}}


def _slots_save(reg: dict) -> None:
    SLOTS_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _link_slot(reg: dict, name: str, phone: str) -> None:
    """Map a session name to its account key (phone) in the registry."""
    if not phone:
        return
    acc = reg["accounts"].setdefault(phone, [])
    if name not in acc:
        acc.append(name)
        acc.sort()
    reg["accounts"][phone] = [n for n in acc if not n.startswith(".")]


def _slots_of(reg: dict, phone: str) -> list[str]:
    return list(reg["accounts"].get(phone, []))


def _invert(reg: dict) -> dict:
    out = {}
    for phone, names in reg.get("accounts", {}).items():
        for n in names:
            out[n] = phone
    return out


def _rec(reg: dict, key: str, name: str, default):
    try:
        return reg.get(key, {}).get(name, default)
    except Exception:
        return default


def _rec_set(reg: dict, key: str, name: str, value) -> None:
    reg.setdefault(key, {})[name] = value


def _norm_phone(p: str) -> str:
    p = re.sub(r"\D", "", p or "")
    return "+" + p if p and not p.startswith("+") else ("+" + p if p else "")


def _meta_of(name: str) -> dict:
    f = snoser.SESSIONS_DIR / f"{name}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _meta_write(name: str, meta: dict) -> None:
    f = snoser.SESSIONS_DIR / f"{name}.json"
    old = _meta_of(name)
    old.update({k: v for k, v in meta.items() if v is not None})
    old["app_id"] = meta["app_id"]
    old["app_hash"] = meta["app_hash"]
    f.write_text(json.dumps(old, ensure_ascii=False, indent=1),
                 encoding="utf-8")


# ── fingerprint helpers ──────────────────────────────────────────────
def _pick_api_pair(exclude: tuple) -> tuple:
    """A different (api_id, api_hash) pair than the given one."""
    for pair in snoser._FP_API_POOL:
        if str(pair[0]) != str(exclude[0]):
            return pair
    return snoser._FP_API_POOL[0]


def _make_twin_meta(name: str, api_pair: tuple) -> dict:
    h = int(hashlib.sha1(name.encode()).hexdigest(), 16)
    dev = snoser._FP_DEVICE_POOL[h % len(snoser._FP_DEVICE_POOL)]
    return {
        "app_id": api_pair[0],
        "app_hash": api_pair[1],
        "device": dev[0],
        "sdk": dev[1],
        "app_version": dev[2],
        "lang_pack": dev[3],
        "lang_code": dev[4],
        "twoFA": None,
    }


def _client(work_path: Path, api_id, api_hash, fp: dict, proxy):
    return TelegramClient(
        str(work_path), int(api_id), api_hash, proxy=proxy,
        device_model=fp.get("device", "Desktop"),
        system_version=fp.get("system_version", "Windows 10"),
        app_version=fp.get("app_version", "5.16.5 x64"),
        lang_code=fp.get("lang_code", "en"))


def _probe_client(name: str, proxy):
    fp = snoser.session_fingerprint(name)
    return _client(snoser.SESSIONS_DIR / name, fp["api_id"], fp["api_hash"],
                   fp, proxy)


# ── probe ────────────────────────────────────────────────────────────
async def probe(name: str) -> tuple[str, str]:
    """Return (verdict, info): alive + phone / dead + reason / suspect + err."""
    proxies = snoser.load_pin_proxies()
    px = snoser.pin_for_session(name, proxies) if proxies else None
    client = None
    try:
        client = _probe_client(name, px)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await client.is_user_authorized():
            return "dead", "not authorized"
        me = await client.get_me()
        phone = _norm_phone(getattr(me, "phone", "") or "")
        return "alive", phone or getattr(me, "username", "") or name
    except (errors.AuthKeyUnregisteredError,
            errors.SessionRevokedError,
            errors.UserDeactivatedError):
        return "dead", "auth key unregistered"
    except Exception as e:  # noqa: BLE001 — verdict is the contract
        return "suspect", f"{type(e).__name__}: {e}"
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


# ── login code harvest ───────────────────────────────────────────────
def _extract_code(text: str) -> str:
    if not text:
        return ""
    m = CODE_RE.search(text)
    if m:
        return m.group(1)
    toks = re.findall(r"(?<!\d)(\d{5})(?!\d)", text)
    if toks:
        return toks[0]
    toks = re.findall(r"(?<!\d)(\d{4})(?!\d)", text)
    return toks[0] if toks else ""


async def _receive_code(receiver, timeout: int = CODE_TIMEOUT) -> str:
    """Pull the login code Telegram pushes to the other authorized session
    via the 777000 service chat (live events + history fallback)."""
    q: asyncio.Queue = asyncio.Queue()

    async def _on_msg(event):
        txt = getattr(event.message, "message", "") or ""
        q.put_nowait(txt)

    receiver.add_event_handler(_on_msg, events.NewMessage(from_users=SERVICE_ID))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs = await receiver.get_messages(SERVICE_ID, limit=5)
            for m in msgs:
                c = _extract_code(getattr(m, "message", "") or "")
                if c:
                    return c
        except Exception:
            pass
        try:
            txt = await asyncio.wait_for(q.get(), timeout=2.0)
            c = _extract_code(txt)
            if c:
                return c
        except asyncio.TimeoutError:
            continue
    return ""


# ── session creation (twin bootstrap AND revive share this) ──────────
async def create_session(
    session_name: str,
    api_id,
    api_hash,
    fp: dict,
    phone: str,
    receiver_name: str,
    twofa: str | None = None,
    proxy=None,
) -> tuple[bool, str]:
    """Create a NEW authorized session file `session_name` under the given
    api pair, receiving the login code via `receiver_name` (an authorized
    session of the SAME account). Overwrites any existing <session_name>."""
    sdir = snoser.SESSIONS_DIR
    tmp_base = sdir / f".tmp_{session_name}"
    for suffix in ("", ".session"):
        p = Path(str(tmp_base) + suffix)
        if p.exists():
            p.unlink()
    target = _client(tmp_base, api_id, api_hash, fp, proxy)
    receiver = None
    try:
        rfp = snoser.session_fingerprint(receiver_name)
        rpx = proxy or snoser.pin_for_session(receiver_name,
                                              snoser.load_pin_proxies())
        receiver = _client(sdir / receiver_name, rfp["api_id"],
                           rfp["api_hash"], rfp, rpx)
        await asyncio.wait_for(receiver.connect(), timeout=20)
        if not await receiver.is_user_authorized():
            return False, f"receiver {receiver_name} is dead"
        await asyncio.wait_for(target.connect(), timeout=20)
        harvest = asyncio.create_task(_receive_code(receiver))
        try:
            sent = await target.send_code_request(phone)
            code = await asyncio.wait_for(harvest, timeout=CODE_TIMEOUT + 5)
        except asyncio.TimeoutError:
            code = ""
        if not code:
            return False, "login code not received within window"
        try:
            await target.sign_in(phone, code,
                                 phone_code_hash=sent.phone_code_hash)
        except errors.SessionPasswordNeededError:
            if not twofa:
                return False, "2FA password needed (set meta twoFA)"
            await target.sign_in(password=twofa)
        if not await target.is_user_authorized():
            return False, "sign-in did not authorize"
    except errors.FloodWaitError as e:
        return False, f"flood {e.seconds}s"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            if target:
                await target.disconnect()
        except Exception:
            pass
        try:
            if receiver:
                await receiver.disconnect()
        except Exception:
            pass
    # commit the freshly authorized session file into the pool
    try:
        os.replace(str(tmp_base) + ".session",
                   str(sdir / f"{session_name}.session"))
    except FileNotFoundError:
        return False, "session file missing after sign-in"
    for suffix in ("", ".session"):
        p = Path(str(tmp_base) + suffix)
        if p.exists():
            p.unlink()
    # store discovered phone in meta so revives never lose the account key
    meta = _meta_of(session_name)
    meta["phone"] = phone.lstrip("+")
    _meta_write(session_name, meta)
    return True, "ok"


# ── twin bootstrap ───────────────────────────────────────────────────
async def ensure_twin(live_name: str, phone: str, proxies) -> tuple[bool, str]:
    """Create the second session file (different api pair) for an account
    that currently has only one live slot."""
    twin = live_name + TWIN_SUFFIX
    base_fp = snoser.session_fingerprint(live_name)
    pair = _pick_api_pair((base_fp["api_id"], base_fp["api_hash"]))
    meta = _make_twin_meta(twin, pair)
    _meta_write(twin, meta)
    fp = {
        "device": meta["device"],
        "system_version": meta["sdk"],
        "app_version": meta["app_version"],
        "lang_code": meta["lang_code"],
    }
    px = snoser.pin_for_session(live_name, proxies) if proxies else None
    twofa = _meta_of(live_name).get("twoFA")
    ok, err = await create_session(twin, pair[0], pair[1], fp, phone,
                                   receiver_name=live_name, twofa=twofa,
                                   proxy=px)
    return ok, err


# ── revive ───────────────────────────────────────────────────────────
async def revive(dead_name: str, alive_name: str, phone: str,
                 proxies) -> tuple[bool, str]:
    """Re-create `dead_name` under its OWN api pair, code harvested via the
    alive sibling session."""
    fp = snoser.session_fingerprint(dead_name)
    # keep the same sticky IP the dead session was pinned to
    px = snoser.pin_for_session(dead_name, proxies) if proxies else None
    twofa = _meta_of(dead_name).get("twoFA")
    return await create_session(dead_name, fp["api_id"], fp["api_hash"], fp,
                                phone, receiver_name=alive_name, twofa=twofa,
                                proxy=px)


# ── one watchdog pass ────────────────────────────────────────────────
async def watch_once(revive_dead: bool = True) -> dict:
    # clean leftover temp session files from crashed runs
    for p in snoser.SESSIONS_DIR.glob(".tmp_*"):
        try:
            p.unlink()
        except Exception:
            pass
    reg = _slots_load()
    st = snoser._status_load()
    proxies = snoser.load_pin_proxies()
    report = {"alive": [], "dead": [], "suspect": [],
              "revived": [], "twin_created": [], "errors": []}

    # 1) probe everything (parallel, throttled)
    verdicts: dict[str, str] = {}
    info: dict[str, str] = {}
    sess_names = [s.stem for s in snoser.load_sessions()
                  if not s.stem.startswith(".")]
    sem = asyncio.Semaphore(6)

    async def _probe_one(name: str):
        async with sem:
            return name, await probe(name)

    for name, (v, i) in await asyncio.gather(*[_probe_one(n)
                                              for n in sess_names]):
        verdicts[name], info[name] = v, i
        if v == "alive":
            report["alive"].append(name)
            phone = _norm_phone(i if i.startswith("+") else "")
            _link_slot(reg, name, phone)
        elif v == "dead":
            report["dead"].append(name)
            if name not in (st.get("dead") or []):
                st["dead"] = sorted(set((st.get("dead") or []) + [name]))
                st["suspect"] = [s for s in (st.get("suspect") or []) if s != name]
        else:
            report["suspect"].append(name)
            if name not in (st.get("suspect") or []):
                st["suspect"] = st.get("suspect", []) + [name]
    _slots_save(reg)

    if not revive_dead:
        snoser._status_save(st)
        return report

    # 2) revive dead slots whose account still has a live sibling
    inv = _invert(reg)
    by_phone: dict[str, list[str]] = {}
    for name, v in verdicts.items():
        ph = inv.get(name) or (info.get(name) if v == "alive" else "")
        ph = _norm_phone(ph)
        if ph:
            by_phone.setdefault(ph, []).append(name)
    now = time.time()
    for phone, names in by_phone.items():
        alive = [n for n in names if verdicts.get(n) == "alive"]
        dead = [n for n in names if verdicts.get(n) == "dead"]
        if not alive:
            continue
        if dead:
            for dn in dead:
                last = _rec(reg, "last_revive", dn, 0) or 0
                if now - float(last) < REVIVE_COOLDOWN:
                    continue
                print(f"[WATCH] revive {dn} via {alive[0]} ({phone})", flush=True)
                ok, err = await revive(dn, alive[0], phone, proxies)
                _rec_set(reg, "last_revive", dn, now)
                if ok:
                    report["revived"].append(dn)
                    if dn in (st.get("dead") or []):
                        st["dead"] = [d for d in st["dead"] if d != dn]
                    if dn in (st.get("suspect") or []):
                        st["suspect"] = [s for s in st["suspect"] if s != dn]
                else:
                    report["errors"].append(f"{dn}: {err}")
                await asyncio.sleep(2)
    # 3) bootstrap twins for accounts with ONE live slot and no twin
    for phone, names in by_phone.items():
        alive = [n for n in names if verdicts.get(n) == "alive"]
        if len(alive) != 1:
            continue
        live_name = alive[0]
        if live_name in TWIN_EXCLUDE:
            continue
        twin = live_name + TWIN_SUFFIX
        if twin in (sdir.stem for sdir in snoser.load_sessions()):
            continue
        last = _rec(reg, "last_bootstrap", phone, 0) or 0
        if now - float(last) < BOOTSTRAP_COOLDOWN:
            continue
        print(f"[WATCH] bootstrap twin {twin} via {live_name}", flush=True)
        ok, err = await ensure_twin(live_name, phone, proxies)
        _rec_set(reg, "last_bootstrap", phone, now)
        if ok:
            report["twin_created"].append(twin)
            verdicts[twin] = "alive"
            info[twin] = phone
            _link_slot(reg, twin, phone)
        else:
            report["errors"].append(f"twin {twin}: {err}")
        await asyncio.sleep(2)

    _slots_save(reg)
    st.setdefault("updated", []).append(time.strftime("%Y-%m-%dT%H:%M:%S"))
    st["updated"] = st["updated"][-8:]
    snoser._status_save(st)
    return report


async def watch_loop(interval: int = 300) -> None:
    """Forever loop used by the GH Actions job; the cron tick restarts it."""
    while True:
        try:
            r = await watch_once()
            print("[WATCH] alive:", r["alive"], flush=True)
            print("[WATCH] dead:", r["dead"], flush=True)
            print("[WATCH] revived:", r["revived"], flush=True)
            print("[WATCH] twins:", r["twin_created"], flush=True)
            if r["errors"]:
                print("[WATCH] errors:", r["errors"], flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[WATCH] pass failed: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(interval)


async def main() -> None:
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    argv = sys.argv[1:]
    if argv and argv[0] == "once":
        r = await watch_once()
        print("[WATCH] alive:", r["alive"], flush=True)
        print("[WATCH] dead:", r["dead"], flush=True)
        print("[WATCH] revived:", r["revived"], flush=True)
        print("[WATCH] twins:", r["twin_created"], flush=True)
        print("[WATCH] errors:", r["errors"], flush=True)
    elif argv and argv[0] == "twin":
        name = argv[1]
        px = snoser.load_pin_proxies()
        v, phone = await probe(name)
        if v != "alive":
            print(f"[TWIN] {name} not alive ({v}: {phone})", flush=True)
            return
        ok, err = await ensure_twin(name, phone, px)
        print(f"[TWIN] {name} -> {name}{TWIN_SUFFIX}: {'OK' if ok else err}",
              flush=True)
    else:
        interval = 300
        if argv and argv[0].isdigit():
            interval = int(argv[0])
        await watch_loop(interval)


if __name__ == "__main__":
    asyncio.run(main())