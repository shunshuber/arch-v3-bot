"""Arch V3 mirror hosting — run the same bot on your own bot token.

Usage:
- the owner opens /mirror in main bot;
- they paste a BotFather token;
- we validate via Bot API, register, spawn a Dispatcher-like poller;
- mirrors share the same 内存 (users.json / subs.json) and the same handlers.
On FREE tier (GH Actions) — mirror runs within the same job lifetime.

Mirror's inline reply_markup uses kb_main-like button set.
"""
import asyncio
import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Job-scoped: active mirrors map (token -> asyncio.Task)
_running_mirrors: dict[str, asyncio.Task] = {}
# cached Bot instances (token -> Bot)
_mirror_bots: dict[str, Bot] = {}

MIRROR_MAX = 5  # mirrors per user; mirror token → owner user_id

_mirrors_file = None
def _mirror_store():
    global _mirrors_file
    if _mirrors_file is None:
        from pathlib import Path as _P
        _mirrors_file = _P(__file__).parent / "mirrors.json"
    if not _mirrors_file.exists():
        _mirrors_file.write_text("{}", encoding="utf-8")
    import json as _json
    return _json.loads(_mirrors_file.read_text(encoding="utf-8"))


def save_mirrors(data: dict):
    import json as _json
    _mirrors_file.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def register_mirror(owner_id: int, token: str, bot_username: str) -> bool:
    data = _mirror_store()
    existing = data.get(token)
    if existing:
        return False
    user_entries = [v for v in data.values() if v.get("owner") == owner_id]
    if len(user_entries) >= MIRROR_MAX:
        return False
    data[token] = {"owner": owner_id, "username": bot_username}
    save_mirrors(data)
    return True


def count_mirrors(owner_id: int) -> int:
    data = _mirror_store()
    return len([v for v in data.values() if v.get("owner") == owner_id])


async def validate_token(token: str) -> str | None:
    """Returns bot_username if token valid, else None."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.telegram.org/bot{token}/getMe") as r:
                j = await r.json(content_type=None)
                if j.get("ok"):
                    return (j.get("result") or {}).get("username")
                return None
    except Exception:
        return None


# ── Mirror polling: a stripped down bioline dispatcher that emulates the same flow
async def mirror_poller(token: str) -> None:
    """Long-polling loop for one mirror. Same as bot, but with limited handlers."""
    try:
        bot = Bot(token=token)
        dp = Dispatcher(storage=MemoryStorage())
        _mirror_bots[token] = bot

        # /start в зеркале — просто hero-экран
        @dp.message()
        async def any_handler(msg: types.Message):
            text = msg.text or ""
            if text.startswith("/start"):
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🪞 Зеркало живо", callback_data="mirror_info")],
                ])
                try:
                    await msg.answer_photo(
                        photo=types.FSInputFile(str(__import__("pathlib").Path(__file__).parent / "cache/cards/arch_hero.png")),
                        caption="<b>Arch V3</b> · зеркало",
                        parse_mode=ParseMode.HTML,
                        show_caption_above_media=True,
                        reply_markup=kb,
                    )
                except Exception:
                    await msg.answer("Arch V3 — зеркало работает.", parse_mode=ParseMode.HTML)
            else:
                await msg.answer("❌ Нет команды — используйте /start.", parse_mode=ParseMode.HTML)

        @dp.callback_query()
        async def any_cb(cb: types.CallbackQuery):
            await cb.answer("🪞 Зеркало работает", show_alert=True)

        await dp.start_polling(bot, handle_updates=True)
    except Exception as e:
        import logging
        logging.getLogger("arch-v3.mirror").warning(f"mirror dead: {e}")


def start_mirror(token: str) -> bool:
    tok = token.strip()
    if tok in _running_mirrors:
        return True
    if not os.environ.get("BOT_TOKEN"):
        return False
    task = asyncio.create_task(mirror_poller(tok))
    _running_mirrors[tok] = task
    return True


def stop_mirror(token: str) -> None:
    task = _running_mirrors.pop(token, None)
    if task:
        task.cancel()


def list_mirrors_for(owner_id: int) -> list[dict]:
    data = _mirror_store()
    return [
        {"token": k, "username": v.get("username"), "running": k in _running_mirrors}
        for k, v in data.items()
        if v.get("owner") == owner_id
    ]
