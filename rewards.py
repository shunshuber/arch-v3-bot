"""Arch V3 — wheel of reports (🎡 сутки разwaitFor) + 📦 case + 🎁 promocode.

States are stored in users.json inside the existing record structure.
Prizes are randomly drawn a set of tiered options (не платим).
"""

import random
import json
from datetime import datetime, timedelta
from pathlib import Path
import asyncio

USERS_FILE = Path(__file__).parent / "users.json"
SUBS_FILE = Path(__file__).parent / "subs.json"

WHEEL_COOLDOWN = 24 * 60 * 60

# Prizes — proportional to probability
WHEEL_TABLE = [
    ("+1 день подписки",       12,   {"plan": "d1"}),
    ("+7 дней подписки",        3,   {"plan": "d7"}),
    ("+30 дней подписки",       1,   {"plan": "d30"}),
    ("Запуск бесплатно (уже)",  20,  {"free_launch": 1}),
    ("Ничего 😔",               60,  {}),
    ("+1 рефер (виртуально)",   4,   {}),
]
CASE_PRIZES = [
    ("+1 день подписки",       40,   {"plan": "d1"}),
    ("+7 дней подписки",       20,   {"plan": "d7"}),
    ("+30 дней подписки",       8,   {"plan": "d30"}),
    ("Ничего 😔",              25,   {}),
    ("Вечная подписка",         1,   {"plan": "fo"}),
    ("+2 запуска бесплатно",    6,   {"free_launch": 2}),
]


def _users() -> dict:
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")


def _subs() -> dict:
    try:
        return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_subs(subs: dict) -> None:
    SUBS_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=1), encoding="utf-8")


def can_spin(user_id: int) -> tuple[bool, int]:
    """Returns (can_spin, seconds_left)."""
    users = _users()
    rec = users.get(str(user_id), {})
    last = rec.get("wheel_last_spin") or ""
    if not last:
        return True, 0
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True, 0
    elapsed = (datetime.now() - last_dt).total_seconds()
    if elapsed >= WHEEL_COOLDOWN:
        return True, 0
    return False, int(WHEEL_COOLDOWN - elapsed)


def spin_wheel(user_id: int) -> str:
    """Rolls the wheel; grants prize to subs.json / user profile. Returns prize label."""
    ok, left = can_spin(user_id)
    if not ok:
        return ""
    users = _users()
    key = str(user_id)
    rec = users.setdefault(key, {
        "id": user_id, "username": "", "name": "",
        "first_seen": datetime.now().isoformat(timespec="seconds"),
        "last_seen": datetime.now().isoformat(timespec="seconds"),
        "ref_by": None, "refs": [], "ref_grants": 0, "deep_refs": 0,
        "free_launches": 0, "wheel_last_spin": "",
    })
    rec["wheel_last_spin"] = datetime.now().isoformat(timespec="seconds")

    total = sum(p[1] for p in WHEEL_TABLE)
    roll = random.randint(1, total)
    cumm = 0
    chosen = WHEEL_TABLE[-1][0]
    for label, weight, plan_hint in WHEEL_TABLE:
        cumm += weight
        if roll <= cumm:
            chosen = label
            break

    for label, _, extra in WHEEL_TABLE:
        if label == chosen:
            _apply_prize(user_id, extra)
            break

    rec["last_wheel_prize"] = chosen
    _save(users)
    return chosen


def open_case(user_id: int, cost: dict | None = None) -> tuple[str, dict]:
    """Opens the case; cost must be paid externally (e.g. via xRocket)."""
    users = _users()
    key = str(user_id)
    rec = users.setdefault(key, {"id": user_id, "free_launches": 0})

    total = sum(p[1] for p in CASE_PRIZES)
    roll = random.randint(1, total)
    cumm = 0
    chosen = CASE_PRIZES[-1][0]
    for label, weight, extra in CASE_PRIZES:
        cumm += weight
        if roll <= cumm:
            chosen = label
            break

    _apply_prize(user_id, extra)

    rec["last_case_prize"] = chosen
    _save(users)
    return chosen, extra


def _apply_prize(user_id: int, extra: dict) -> None:
    """Grants the prize into subs.json / users.json."""
    if extra.get("plan"):
        plan = extra["plan"]
        subs = _subs()
        rec = subs.setdefault(str(user_id), {})
        if plan == "fo":
            rec["forever"] = True
        else:
            days_map = {"d1": 1, "d7": 7, "d30": 30}
            days = days_map.get(plan, 1)
            base = rec.get("until", 0)
            import time
            start = max(base, time.time())
            rec["until"] = start + days * 86400
        _save_subs(subs)
    if extra.get("free_launch"):
        n = extra["free_launch"]
        users = _users()
        key = str(user_id)
        rec = users.setdefault(key, {"id": user_id, "free_launches": 0})
        rec["free_launches"] = (rec.get("free_launches") or 0) + n
        _save(users)


def set_promo(code: str, days: int, activations: int = 3) -> None:
    users = _users()
    promos = users.setdefault("__promos", {})
    promos[code] = {"days": days, "activations": activations,
                    "issued": datetime.now().isoformat(timespec="seconds")}
    _save(users)


def apply_promo(user_id: int, code: str) -> tuple[bool, str]:
    users = _users()
    promos = users.get("__promos", {})
    pr = promos.get(code)
    if not pr:
        return False, "promo не найден"
    activations = pr.get("activations", 0)
    used = users.get(f"__promo_use_{code}", [])
    if user_id in used:
        return False, "ты уже usesS этот промокод"
    if activations <= 0:
        return False, "промокод исчерпан"
    used.append(user_id)
    users[f"__promo_use_{code}"] = used
    pr["activations"] = max(0, activations - 1)
    save_subs_zip = _subs()
    rec = save_subs_zip.setdefault(str(user_id), {})
    if pr.get("forever"):
        rec["forever"] = True
    else:
        days = pr.get("days", 1)
        import time
        base = rec.get("until", 0)
        start = max(base, time.time())
        rec["until"] = start + days * 86400
    _save_subs(save_subs_zip)
    _save(users)
    return True, f"активирован: +{pr['days']} дн."
