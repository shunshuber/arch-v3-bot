"""Free drop-in replacement for the Groq-based DSA complaint text generator.

Chain (first success wins):
  1. Gemini OpenAI-compatible endpoint — needs GEMINI_KEY (free tier at
     https://aistudio.google.com/apikey), model GEMINI_MODEL (default 2.5-flash).
  2. Pollinations text API — no key, no signup, free per-IP rate limit
     (one request per 45 seconds), model "openai-fast".
  3. Local templates — always works, no network.

Import and call exactly like the old function:
    from free_llm import generate_complaint_text
"""
import asyncio
import math
import os
import random
import re
import time
from pathlib import Path

import aiohttp

GEMINI_KEY = os.getenv("GEMINI_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
POLLINATIONS_MODEL = os.getenv("POLLINATIONS_MODEL", "openai-fast").strip()
POLLINATIONS_INTERVAL = float(os.getenv("POLLINATIONS_INTERVAL", "45"))
DATA_DIR = Path(__file__).parent / "dsa_data"

_poll_lock = asyncio.Lock()
_last_poll_ts = 0.0


def next_free_delay() -> int:
    """Seconds the next free (keyless) generation must wait. Feed this into
    the progress animation so a queued user sees a longer sending progress
    instead of a silent stall."""
    left = POLLINATIONS_INTERVAL - (time.monotonic() - _last_poll_ts)
    return max(0, math.ceil(left))

SYSTEM_PROMPT = (
    "You are a DSA complaint text generator for Telegram's official reporting "
    "system. Generate a complaint in English, UNDER 200 characters. Be direct "
    "and concise, no intro phrases. Do NOT mention @usernames or handles. "
    "Output ONLY the complaint text."
)

FALLBACKS = {
    "personal_data": (
        "This account publicly shares private personal information without "
        "consent. Please review the content and enforce the applicable rules."),
    "scam": (
        "The reported account runs a deceptive scheme to obtain money or "
        "credentials from users. Request a prompt review and enforcement."),
    "illegal_goods": (
        "The reported account offers regulated or prohibited goods. Please "
        "review the account and take appropriate action."),
    "illegal_adult": (
        "The reported account distributes illegal sexual content. Please "
        "review the material and enforce the applicable rules."),
    "child_abuse": (
        "The reported account is involved in sexual abuse of minors. Immediate "
        "review and enforcement are requested."),
    "violence": (
        "The reported account posts credible threats of violence. Please "
        "review the account and take appropriate action."),
    "terrorism": (
        "The reported account promotes violent extremist material. Please "
        "review the account and enforce the applicable rules."),
    "other": (
        "The reported content violates Telegram's rules and applicable law. "
        "Please review it and take appropriate action."),
}

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _clean(text: str, limit: int = 200) -> str:
    text = _THINK.sub("", str(text or "")).strip()
    text = re.sub(r"^[\"'`]+|[\"'`]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _local_fallback(reason: str, sub_reason: str = "") -> str:
    path = DATA_DIR / "reptexts.txt"
    if path.exists():
        try:
            lines = [x.strip() for x in path.read_text(encoding="utf-8").splitlines()
                     if x.strip()]
            if lines:
                return _clean(random.choice(lines))
        except Exception:
            pass
    return _clean(FALLBACKS.get(str(reason or "").strip().lower(),
                                FALLBACKS["other"]))


async def _post_json(session: aiohttp.ClientSession, url: str,
                     payload: dict, headers: dict) -> str:
    async with session.post(url, json=payload, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=20)) as resp:
        # Pollinations free tier: 402 + Retry-After when the IP slot is busy
        if resp.status in (402, 429):
            wait = int(float(resp.headers.get("Retry-After") or 5))
            await asyncio.sleep(min(wait, 5))
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=20)) as r2:
                if r2.status != 200:
                    return ""
                data = await r2.json(content_type=None)
        else:
            if resp.status != 200:
                return ""
            data = await resp.json(content_type=None)
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except Exception:
        return ""


async def _gemini(system: str, user: str, max_tokens: int = 120) -> str:
    if not GEMINI_KEY:
        return ""
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    payload = {"model": GEMINI_MODEL,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.7, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {GEMINI_KEY}",
               "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        return await _post_json(s, url, payload, headers)


async def _pollinations(system: str, user: str, max_tokens: int | None = None) -> str:
    """Serialize keyless calls: the free API allows one request per 45s/IP.
    A second user simply keeps the 'sending' progress running a bit longer."""
    global _last_poll_ts
    url = "https://text.pollinations.ai/openai"
    payload = {"model": POLLINATIONS_MODEL,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.7}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    async with _poll_lock:
        wait = POLLINATIONS_INTERVAL - (time.monotonic() - _last_poll_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        out = ""
        try:
            async with aiohttp.ClientSession() as s:
                out = await _post_json(
                    s, url, payload, {"Content-Type": "application/json"})
        finally:
            _last_poll_ts = time.monotonic()
        return out


async def generate_complaint_text(reason: str, sub_reason: str,
                                  message_text: str = "") -> str:
    """Same signature as the Groq function. Never raises, always returns text."""
    user = f"Report reason: {reason}"
    if sub_reason:
        user += f"\nSub-reason: {sub_reason}"
    if message_text:
        user += f"\nMessage content: {message_text[:300]}"
    for call in (_gemini, _pollinations):
        try:
            out = _clean(await call(SYSTEM_PROMPT, user))
            if out:
                return out
        except Exception:
            continue
    return _local_fallback(reason, sub_reason)


VARIANTS_PROMPT = (
    "Ты пишешь жалобы для модерации Telegram в стиле примера ниже. "
    "Сгенерируй РОВНО 8 пронумерованных строк (1-8), по одной жалобе на строку. "
    "Каждая жалоба — развёрнутый абзац 250-450 символов на русском языке: "
    "конкретно описывай нарушение из Message text/Description, объясняй, "
    "какой вред оно наносит,ссылайся на нарушение правил и проси модерацию "
    "проверить и принять меры вплоть до блокировки. Не используй шаблонные "
    "обороты, каждая жалоба должна звучать по-разному. Без @username и ссылок. "
    "Только 8 строк, без пояснений.\n\n"
    "ПРИМЕР СТИЛЯ:\n"
    "Бот предоставляет данные людей без их согласия. Через него можно получить "
    "конфиденциальную информацию включая номера телефонов и другие частные "
    "сведения. Такие действия нарушают право на приватность и могут использоваться "
    "для доксинга и преследования. Прошу проверить этого бота и принять меры "
    "включая его блокировку!"
)


_VARIANT_ANGLES = (
    "В указанном сообщении прямо содержится",
    "Материал намеренно предлагает",
    "Публикация содержит признаки",
    "Из текста следует, что",
    "Такое поведение создаёт риск",
    "Анализ сообщения показывает",
    "Пользователи подталкиваются к",
    "Прошу обратить внимание на то, что",
)


def _parse_variants(raw: str, reason: str, sub_reason: str,
                    message_text: str = "", count: int = 8) -> list[str]:
    out = []
    for line in (raw or "").splitlines():
        line = re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip()
        line = _clean(line)
        if len(line) >= 60 and line not in out:
            out.append(line[:450])
    snippet = (message_text or reason).strip()[:160]
    i = 0
    while len(out) < count:
        angle = _VARIANT_ANGLES[i % len(_VARIANT_ANGLES)]
        text = (
            f"{angle}: {snippet}. Категория нарушения: {reason}. "
            "Подобные действия нарушают правила Telegram и могут нанести "
            "вред другим пользователям, включая незаконное распространение "
            "сведений и вовлечение в опасные схемы. Прошу модерацию тщательно "
            "проверить данный материал, принять меры вплоть до блокировки "
            "аккаунта и предотвратить дальнейшее распространение.")[:450]
        if text not in out:
            out.append(text)
        i += 1
    return out[:count]


async def generate_complaint_variants(reason: str, sub_reason: str,
                                      message_text: str = "",
                                      count: int = 8) -> list[str]:
    """Premium: 8 unique AI texts tailored to reason + reported message."""
    user = f"Description: {reason}"
    if sub_reason:
        user += f"\nDetails: {sub_reason}"
    if message_text:
        user += f"\nMessage text: {message_text[:600]}"
    user += f"\nСгенерируй {count} жалоб."
    for call in (_gemini, _pollinations):
        try:
            raw = await call(VARIANTS_PROMPT, user, max_tokens=3000)
            variants = _parse_variants(raw, reason, sub_reason,
                                       message_text, count)
            if variants:
                return variants[:count]
        except Exception:
            continue
    return _parse_variants("", reason, sub_reason, message_text, count)[:count]
