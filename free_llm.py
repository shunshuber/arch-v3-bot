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
import os
import random
import re
from pathlib import Path

import aiohttp

GEMINI_KEY = os.getenv("GEMINI_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
POLLINATIONS_MODEL = os.getenv("POLLINATIONS_MODEL", "openai-fast").strip()
DATA_DIR = Path(__file__).parent / "dsa_data"

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


async def _gemini(system: str, user: str) -> str:
    if not GEMINI_KEY:
        return ""
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    payload = {"model": GEMINI_MODEL,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.7, "max_tokens": 120}
    headers = {"Authorization": f"Bearer {GEMINI_KEY}",
               "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        return await _post_json(s, url, payload, headers)


async def _pollinations(system: str, user: str) -> str:
    url = "https://text.pollinations.ai/openai"
    payload = {"model": POLLINATIONS_MODEL,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.7}
    async with aiohttp.ClientSession() as s:
        return await _post_json(s, url, payload, {"Content-Type": "application/json"})


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
