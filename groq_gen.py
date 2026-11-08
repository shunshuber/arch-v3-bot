"""X-Groq complaint text generator (Arch V3 upgrade).

Generates unique per-request complaint texts via Groq LLM, replacing static
template rotation. Used by omnikill (abuse@emails), web-reporter (DSA/support),
snos (SendCode/TIDA), telegram.web-form: unique text per email.

Env: GROQ_KEY (secret) — fetch from https://console.groq.com
Model: llama-3.3-70b — Cheapest-tier for under 500 tok per call, batched.
Fallback: returns static template if GROQ_KEY missing / request fails.
"""
import os
import random
import asyncio
import aiohttp

GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
KEY = os.environ.get("GROQ_KEY", "")

PROMPT_BASE = (
    "You generate text-complaints to Telegram support for reporting accounts "
    "that violate the TOS. Style: politeness, English only, USE THE "
    "COMPLAINT CATEGORY provided. Never include markdown. "
    "Never use `@mentions` or URLs. Max 180 chars. Directly finish with "
    "a statement to block/take down the target. Output ONLY the complaint "
    "text. Do not use quotes, apostrophes or markdown."
)


async def generate_complaint(reason_label: str, target_hint: str = "",
                             extra: str = "", max_tokens: int = 120) -> str:
    """Generate complaint. Returns empty string on failure (caller falls back)."""
    if not KEY:
        return ""
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_BASE},
            {"role": "user", "content": (
                f"Reason: {reason_label}\n"
                + (f"Target hint: {target_hint}\n" if target_hint else "")
                + (f"Additional info: {extra[:400]}\n" if extra else "")
                + "Output the complaint. English. Max 180 chars.")
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0.85,
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(GROQ_API, json=body,
                                 headers={"Authorization": f"Bearer {KEY}"},
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json(content_type=None)
                if r.status != 200:
                    return ""
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("text", "")
                return text.strip()[:280] if text else ""
    except Exception:
        return ""


def fallback_complaint(reason_label: str, target_hint: str) -> str:
    """Static fallback for when Groq is unavailable."""
    tpl = [
        f"Complaint: {reason_label} — please review and take down.",
        f"This account violates Telegram TOS ({reason_label}). Block required.",
        f"Urgent: {reason_label} — requesting immediate enforcement against this target.",
        f"Reporting {reason_label} violation. Please take appropriate action.",
    ]
    return random.choice(tpl) + (f" Target: {target_hint}" if target_hint else "")
