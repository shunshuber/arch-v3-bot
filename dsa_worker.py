"""DSA Report worker for Arch V3 — browser form at telegram.org/dsa-report.

Turnstile sitekey supplied by Kanha: 3d29ac4caebf423aace64bcc5730616d.
Complaint text comes from free_llm (no paid Groq key needed).
"""
import asyncio
import os
import random

import aiohttp

TARGET_URL = "https://telegram.org/dsa-report"
TURNSTILE_SITEKEY = "3d29ac4caebf423aace64bcc5730616d"

# Arch V3 reason -> radio label on the DSA form
REASON_SITE = {
    "child": "Child abuse",
    "violence": "Violence",
    "drugs": "Illegal goods",
    "porn": "Illegal adult content",
    "personal": "Personal data",
    "spam": "Scam or spam",
    "fraud": "Scam or spam",
    "fake": "Impersonation",
    "sexwork": "Other",
    "copyright": "Other",
    "other": "Other",
}

NAMES = ["James", "Michael", "Robert", "Maria", "Anna", "David", "Sophie", "Daniel"]
SURNAMES = ["Smith", "Brown", "Wilson", "Miller", "Taylor", "Anderson", "Thomas"]
ADDRESSES = ["12 King Street, Berlin", "8 Market Road, Munich", "45 Park Avenue, Hamburg"]
EMAILS = ["j.smith.2271@gmail.com", "m.wilson.4419@outlook.com", "a.taylor.8832@gmail.com"]
PHONES = ["+4915123456789", "+4915987654321", "+4917076543210"]


def _pick(variants):
    return random.choice(variants)


async def _solve_turnstile(page_url: str, key: str):
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://api.capmonster.cloud/createTask",
            json={"clientKey": key, "task": {
                "type": "TurnstileTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": TURNSTILE_SITEKEY}},
            timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.json(content_type=None)
        if data.get("errorId") != 0:
            return None, data.get("errorDescription", "createTask error")
        task_id = data.get("taskId")
        for _ in range(60):
            await asyncio.sleep(3)
            async with s.post(
                "https://api.capmonster.cloud/getTaskResult",
                json={"clientKey": key, "taskId": task_id},
                timeout=aiohttp.ClientTimeout(total=15)) as r:
                res = await r.json(content_type=None)
            if res.get("status") == "ready":
                return res.get("solution", {}).get("token"), ""
            if res.get("errorId") != 0:
                return None, res.get("errorDescription", "task error")
    return None, "captcha timeout"


def _xpath(text):
    if "'" not in text:
        return f"//*[text()='{text}']"
    parts = text.split("'")
    return "//*[text()=concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")]"


async def _click(page, text):
    xp = _xpath(text)
    try:
        await page.wait_for_selector(xp, timeout=15000)
    except Exception:
        return False
    for sel in (f"span.radio-label >> text={text}",
                f"label.radio-item >> text={text}", xp):
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click(force=True)
                return True
        except Exception:
            continue
    return False


async def _fill(page, value):
    await page.wait_for_selector(".cd-comment-input", timeout=40000)
    await asyncio.sleep(0.3)
    await page.locator(".cd-comment-input").first.click()
    for ch in str(value):
        await page.keyboard.type(ch, delay=random.randint(15, 45))
    await asyncio.sleep(0.2)
    await page.locator(".cd-submit-comment-btn").first.click()


async def run_dsa(target: str, reason_key: str, complaint: str,
                  cap_key: str) -> tuple[bool, str]:
    """One full DSA submission. Returns (success, error_or_empty)."""
    from playwright.async_api import async_playwright

    target = str(target or "").strip()
    if not target.startswith("http"):
        target = "https://" + target.lstrip("@").replace("t.me/", "https://t.me/", 1)
    reason = REASON_SITE.get(str(reason_key or "").lower(), "Other")
    fullname = f"{_pick(NAMES)} {_pick(SURNAMES)}"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36")
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await context.new_page()
        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            token, err = await _solve_turnstile(TARGET_URL, cap_key)
            if not token:
                return False, err or "no captcha token"
            await page.evaluate("""
                (token) => {
                    document.querySelectorAll(
                      'input[name="cf-turnstile-response"], input[id*="cf-chl-widget"]'
                    ).forEach(el => el.value = token);
                    if (window.onTurnstileSuccess) window.onTurnstileSuccess(token);
                    if (window.turnstileCallback) window.turnstileCallback(token);
                    const b = document.querySelector('.js-report-start-btn');
                    if (b) { b.removeAttribute('disabled'); b.classList.remove('disabled'); }
                }
            """, token)
            await asyncio.sleep(1)
            btn = await page.query_selector(".js-report-start-btn")
            if btn:
                try:
                    async with page.expect_popup(timeout=8000) as pi:
                        await btn.click()
                    pop = await pi.value
                    await pop.wait_for_load_state("domcontentloaded", timeout=10000)
                    for sel in ("a[href*='unauth=1']", ".login_footer_text a",
                                "a:has-text('without logging in')"):
                        try:
                            el = await pop.wait_for_selector(sel, timeout=3000,
                                                             state="visible")
                            if el:
                                await el.click()
                                await asyncio.sleep(2)
                                break
                        except Exception:
                            continue
                except Exception:
                    await btn.click()
                    await asyncio.sleep(2)

            found = False
            for p in page.context.pages:
                try:
                    await p.wait_for_selector(".cd-comment-input", timeout=8000)
                    page = p
                    found = True
                    break
                except Exception:
                    continue
            if not found:
                return False, "DSA form not found"

            for value in (target, reason, complaint or "Please review this content.",
                          target):
                await _fill(page, value)
                await asyncio.sleep(0.8)
            for choice in ("Germany", "Proceed without documentation",
                           "My own behalf"):
                if not await _click(page, choice):
                    return False, f"radio not found: {choice}"
                await asyncio.sleep(0.6)
            for value in (fullname, _pick(ADDRESSES), _pick(EMAILS), _pick(PHONES)):
                await _fill(page, value)
                await asyncio.sleep(0.6)
            for choice in ("I don't have a court order", "Confirm"):
                if not await _click(page, choice):
                    return False, f"radio not found: {choice}"
                await asyncio.sleep(0.6)
            await _fill(page, fullname)
            await asyncio.sleep(2)
            return True, ""
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        finally:
            await browser.close()
