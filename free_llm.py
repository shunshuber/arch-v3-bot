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
    "Ты пишешь жалобы на конкретные сообщения Telegram для модерации. "
    "Используй только то, что реально есть в Message text / Description / "
    "Message text. Не выдумывай товары, имена, организации и статьи закона, "
    "которых нет в исходнике. Если текст со скриншота — разбери "
    "именно то, что на нём написано.\n\n"
    "СТРУКТУРА каждой жалобы (строго по порядку):\n"
    "1. Первое предложение: «Сообщение содержит ...» — сразу конкретика. "
    "Перечисли нарушение дословно, как оно написано в исходнике, в кавычках: "
    "названия веществ, услуг, действий, цены, призывы. Никаких общих фраз "
    "вроде «различные нарушения» или «незаконный контент» без деталей.\n"
    "2. Что делает автор: публично предлагает доставку/продажу, приглашает "
    "купить, отсылает в чат или канал, публикует запрещённое. Назови вред: "
    "вовлечение в опасные схемы, угроза здоровью, распространение запрещённых "
    "материалов.\n"
    "3. Прямое указание на нарушение правил Telegram и конкретную статью "
    "закона РФ, если категория это позволяет: наркотики — ст. 228.1 УК РФ и "
    "ст. 6.8 КоАП РФ; персональные данные — ст. 152.1 ГК РФ; мошенничество — "
    "ст. 159 УК РФ; угрозы — ст. 119 УК РФ.\n"
    "4. Требование: удалить публикацию, заблокировать аккаунт и пресечь "
    "дальнейшее распространение через платформу.\n\n"
    "Русский язык, один абзац, 250-450 символов. Никаких эмодзи и скобок с "
    "сырыми символами: не пересказывай картинку списком значков, а сформулируй "
    "смысл нарушения словами. Если в исходнике только набор эмодзи или он "
    "нечитаем, пиши по категории и названию нарушения, не цитируя мусор. "
    "Без @username, без ссылок, без вступлений («Здравствуйте», "
    "«Я хочу сообщить»), без пояснений от себя. "
    "РОВНО 8 пронумерованных строк (1-8), по одной жалобе на строку. Каждая "
    "должна звучать по-разному, но сохранять ту же жёсткую конкретику "
    "и резкий финал. Не копируй пример дословно — только структуру.\n\n"
    "ПРИМЕР СТИЛЯ:\n"
    "Сообщение содержит прямую рекламу и предложение доставки запрещённых "
    "наркотических средств: экстази, метамфетамин («меф»), альфа-PVP, кокаин. "
    "Автор публично предлагает доставку и приглашает к покупке, отсылая в чат. "
    "Это нарушает правила Telegram и законодательство РФ (ст. 228.1 УК РФ, "
    "ст. 6.8 КоАП РФ). Прошу удалить публикацию, заблокировать аккаунт и "
    "пресечь распространение наркотиков через платформу."
)


_VARIANT_ANGLES = (
    "Сообщение содержит",
    "Публикация прямо предлагает",
    "В сообщении указано",
    "Материал содержит",
    "Автор публично разместил",
    "Из текста следует",
    "Сообщение рекламирует",
    "Опубликованный материал содержит",
)


def _law_hint(reason: str) -> str:
    s = (reason or "").lower()
    if "наркот" in s:
        return "(ст. 228.1 УК РФ, ст. 6.8 КоАП РФ)"
    if "персональн" in s or "данн" in s:
        return "(ст. 152.1 ГК РФ)"
    if "мошен" in s or "обман" in s:
        return "(ст. 159 УК РФ)"
    if "насил" in s or "угроз" in s:
        return "(ст. 119 УК РФ)"
    return "(соответствующие нормы законодательства РФ)"


def _parse_variants(raw: str, reason: str, sub_reason: str,
                    message_text: str = "", count: int = 8) -> list[str]:
    out = []
    for line in (raw or "").splitlines():
        line = re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip()
        line = _clean_source(_clean(line))
        if len(line) >= 60 and line not in out:
            out.append(line[:450])
    snippet = _clean_source(message_text, reason).strip()[:160]
    law = _law_hint(reason)
    i = 0
    while len(out) < count:
        angle = _VARIANT_ANGLES[i % len(_VARIANT_ANGLES)]
        text = (
            f"{angle}: «{snippet}». Автор публично распространяет этот "
            "материал и приглашает к участию, что создаёт риск для других "
            "пользователей. Такие действия нарушают правила Telegram и "
            f"законодательство РФ {law}. Прошу удалить публикацию, "
            "заблокировать аккаунт и "
            "пресечь дальнейшее распространение через платформу.")[:450]
        if text not in out:
            out.append(text)
        i += 1
    return out[:count]


def _clean_source(text: str, reason: str = "") -> str:
    """Drop emoji-only rows and raw symbol noise before feeding the LLM.
    Screenshots often arrive as a wall of pictographs — quoting that back
    produces the '🅰️🅰️🚚🚚' garbage instead of an actual complaint."""
    keep = []
    for line in (text or "").splitlines():
        letters = re.findall(r"[A-Za-zА-Яа-яЁё0-9]", line)
        if len(letters) >= 3:
            keep.append(line.strip())
    s = " ".join(keep)
    s = re.sub(r"[^\w\sа-яА-ЯЁё/,.:;!?()\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = []
    for word in s.split():
        if not tokens or word != tokens[-1]:
            tokens.append(word)
    return " ".join(tokens)[:400] or (reason or "").strip()


async def generate_complaint_variants(reason: str, sub_reason: str,
                                      message_text: str = "",
                                      count: int = 8) -> list[str]:
    """Premium: 8 unique AI texts tailored to reason + reported message."""
    user = f"Description: {reason}"
    if sub_reason:
        user += f"\nDetails: {sub_reason}"
    clean = _clean_source(message_text, reason)
    if clean:
        user += f"\nMessage text: {clean[:400]}"
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
