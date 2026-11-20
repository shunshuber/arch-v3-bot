"""DSA Report worker for Arch V3 — browser form at telegram.org/dsa-report.

Turnstile sitekey comes from the original worker: 0x4AAAAAABCHiDxTcTJ4azUp.
CapMonster API key lives in the CAPMONSTER_KEY secret.
Complaint text comes from free_llm (no paid Groq key needed).
"""
import asyncio
import os
import random
import time
from urllib.parse import urlparse

import aiohttp

TARGET_URL = "https://telegram.org/dsa-report"
TURNSTILE_SITEKEY = "0x4AAAAAABCHiDxTcTJ4azUp"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")

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

# default subcategory when the form splits a reason into radio subgroups
SUB_FOR_REASON = {
    "drugs": "Drugs",
    "porn": "Child abuse",
    "personal": "Private images",
    "spam": "Phishing",
    "fraud": "Fraudulent sales",
    "fake": "Impersonation",
}

NAMES = ["James", "Michael", "Robert", "Maria", "Anna", "David", "Sophie", "Daniel"]
SURNAMES = ["Smith", "Brown", "Wilson", "Miller", "Taylor", "Anderson", "Thomas"]
ADDRESSES = ["12 King Street, Berlin", "8 Market Road, Munich", "45 Park Avenue, Hamburg"]
EMAILS = ["j.smith.2271@gmail.com", "m.wilson.4419@outlook.com", "a.taylor.8832@gmail.com"]
PHONES = ["+4915123456789", "+4915987654321", "+4917076543210"]


def _pick(variants):
    return random.choice(variants)


def _browser_proxy():
    """Playwright proxy dict from DSA_PROXY_URL (http/socks5 with login:pass)."""
    raw = os.getenv("DSA_PROXY_URL", "").strip()
    if not raw:
        return None, None
    u = urlparse(raw)
    if not u.hostname:
        return None, None
    scheme = u.scheme or "http"
    px = {"server": f"{scheme}://{u.hostname}:{u.port or (1080 if scheme == 'socks5' else 80)}"}
    if u.username:
        px["username"] = u.username
    if u.password:
        px["password"] = u.password
    cap = {"proxyAddress": u.hostname, "proxyPort": u.port or 80,
           "proxyType": "HTTP" if scheme == "http" else "SOCKS5"}
    if u.username:
        cap["proxyLogin"] = u.username
    if u.password:
        cap["proxyPassword"] = u.password
    return px, cap


async def _solve_turnstile(page_url: str, key: str, cap_proxy=None,
                           action=None, cdata=None):
    # CapMonster TurnstileTask field names are pageAction and data (NOT
    # action/cdata) — docs.capmonster.cloud/docs/captchas/turnstile-task
    task = {"type": "TurnstileTask", "websiteURL": page_url,
            "websiteKey": TURNSTILE_SITEKEY,
            "userAgent": BROWSER_UA}
    if action:
        task["pageAction"] = action
    if cdata:
        task["data"] = cdata
    if cap_proxy:
        task.update(cap_proxy)
    else:
        task["type"] = "TurnstileTaskProxyless"
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://api.capmonster.cloud/createTask",
            json={"clientKey": key, "task": task},
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


def _subseq(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


async def _click(page, text):
    xp = _xpath(text)
    for sel in (f"span.radio-label >> text={text}",
                f"label.radio-item >> text={text}", xp):
        try:
            el = page.locator(sel).first
            if await el.count() and await el.is_visible(timeout=2000):
                await el.click(force=True)
                return True
        except Exception:
            continue
    # Telegram injects random letters into visible labels, so textContent is
    # e.g. "GeXrmYany" instead of "Germany". Match as a subsequence instead.
    target = "".join(c for c in text.lower() if c.isalpha())
    if len(target) < 4:
        return False
    try:
        labels = page.locator(".radio-label, label.radio-item, [role='radio']")
        n = await labels.count()
        for i in range(min(n, 80)):
            el = labels.nth(i)
            try:
                if not await el.is_visible(timeout=300):
                    continue
            except Exception:
                continue
            raw = await el.inner_text()
            shown = "".join(c for c in raw.lower() if c.isalpha())
            if target and _subseq(target, shown):
                print("DSA radio matched:", repr(text), "->",
                      repr(raw[:60]), flush=True)
                await el.evaluate("e => e.click()")
                return True
    except Exception:
        pass
    return False


async def _fill(page, value):
    target = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and target is None:
        loc = page.locator(".cd-comment-input").first
        if await loc.count():
            try:
                if await loc.is_visible(timeout=500):
                    target = loc
                    break
            except Exception:
                pass
        for alt in (".cd-comment-input", "textarea",
                    "[contenteditable='true']", "[class*='comment']",
                    "input[type=text]", "input:not([type=hidden])"):
            cands = page.locator(alt)
            for i in range(min(await cands.count(), 20)):
                cand = cands.nth(i)
                try:
                    if await cand.is_visible(timeout=500):
                        target = cand
                        break
                except Exception:
                    continue
            if target is not None:
                break
        if target is None:
            await page.wait_for_timeout(500)
    dump = await page.eval_on_selector_all(
        "input, textarea",
        "els => els.slice(0,25).map(e => ({tag:e.tagName,cls:(e.className||'').slice(0,40),"
        "type:e.type||'',ph:e.placeholder||'',vis:!!(e.offsetWidth||e.offsetHeight)}))")
    print("DSA fill:", str(value)[:40], "inputs=", dump, flush=True)
    if not await target.count():
        raise RuntimeError(f"no input for '{str(value)[:30]}': inputs={dump}")
    await asyncio.sleep(0.3)
    try:
        await target.click(timeout=6000)
    except Exception:
        # overlay / interceptor — click through JS, like the start button
        await target.evaluate("e => e.click()")
    for ch in str(value):
        await page.keyboard.type(ch, delay=random.randint(15, 45))
    await asyncio.sleep(0.2)
    btn = page.locator(".cd-submit-comment-btn").first
    if not await btn.count():
        btn = page.locator("button:has-text('Submit'), button:has-text('Next')").first
    try:
        await btn.click(timeout=8000)
    except Exception as e:
        try:
            await btn.evaluate("e => e.click()")
        except Exception:
            try:
                buttons = await page.eval_on_selector_all(
                    "button",
                    "els => els.slice(0,30).map(e => ({cls:(e.className||'').slice(0,60),"
                    "text:(e.textContent||'').trim().slice(0,40)}))")
            except Exception:
                buttons = []
            raise RuntimeError(
                f"submit click failed after '{str(value)[:30]}': "
                f"{type(e).__name__}; buttons={buttons}") from e


async def _dump_elements(page, limit: int = 5000) -> str:
    try:
        items = await page.eval_on_selector_all(
            "input, button, label, [role='radio'], [class*='radio'], "
            "[class*='option'], [class*='choice']",
            """els => els.slice(0,80).map(e => ({
                tag: e.tagName, id: e.id || '',
                cls: (e.className||'').toString().slice(0,70),
                type: e.type || '', val: e.value || '',
                vis: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
                text: (e.textContent||'').trim().slice(0,50)
            }))""")
        return str(items)[:limit]
    except Exception as e:
        return f"dump error {type(e).__name__}"


async def _visible_labels(page, limit: int = 6000) -> str:
    try:
        labels = page.locator(".radio-label, label.radio-item, [role='radio']")
        out = []
        for i in range(min(await labels.count(), 100)):
            el = labels.nth(i)
            try:
                if await el.is_visible(timeout=300):
                    out.append((await el.inner_text()).strip())
            except Exception:
                continue
        return str(out)[:limit]
    except Exception as e:
        return f"labels dump error {type(e).__name__}"


async def _dump_pages(context, limit: int = 1200) -> str:
    out = []
    for p in context.pages:
        try:
            title = await p.title()
            body = (await p.locator("body").inner_text(timeout=3000))[:500]
            out.append(f"{p.url} | {title} | {body}")
        except Exception as e:
            out.append(f"{p.url} | dump {type(e).__name__}")
    return " || ".join(out)[:limit]


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
        px, cap_proxy = _browser_proxy()
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            proxy=px,
            user_agent=BROWSER_UA)
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await context.new_page()
        cap_responses = []

        async def _grab_captcha(resp):
            if "/captcha" not in resp.url:
                return
            try:
                body = (await resp.text())[:300]
            except Exception:
                body = ""
            cap_responses.append((resp.status, body))

        page.on("response", lambda r: asyncio.ensure_future(_grab_captcha(r)))
        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            widget = await page.query_selector("[data-sitekey]")
            action = await widget.get_attribute("data-action") if widget else None
            cdata = await widget.get_attribute("data-cdata") if widget else None
            print("DSA turnstile action/cdata:", action, cdata, flush=True)
            token, err = await _solve_turnstile(
                TARGET_URL, cap_key, cap_proxy, action, cdata)
            if not token:
                return False, err or "no captcha token"
            await page.evaluate("""
                () => {
                    window.__dsaAlert = '';
                    if (typeof window.showAlert === 'function') {
                        window.showAlert = m => { window.__dsaAlert = String(m); };
                    }
                }
            """)
            await page.evaluate("""
                (token) => {
                    document.querySelectorAll(
                      'input[name="cf-turnstile-response"], input[id*="cf-chl-widget"]'
                    ).forEach(el => el.value = token);
                }
            """, token)
            btn = await page.query_selector(".js-report-start-btn")
            if not btn:
                return False, "start button missing; " + await _dump_pages(context)
            # onTurnstileSuccess POSTs /dsa-report/captcha. Its own retry uses
            # setTimeout(onTurnstileSuccess, 200) with NO token, which makes
            # the server answer "Please reload the page". Re-call it ourselves
            # with the same token until the button is enabled.
            ready = False
            for _ in range(6):
                await page.evaluate("t => window.onTurnstileSuccess(t)", token)
                for _ in range(5):
                    if not await btn.is_disabled():
                        ready = True
                        break
                    await asyncio.sleep(0.4)
                if ready:
                    break
                await asyncio.sleep(0.5)
            if not ready:
                alert = await page.evaluate("() => window.__dsaAlert || ''")
                return False, ("captcha not accepted; alert="
                               + str(alert)[:200] + " responses="
                               + str(cap_responses)[:400]
                               + "; " + await _dump_pages(context))
            state = await btn.evaluate(
                "el => ({disabled: el.disabled, cls: el.className, "
                "text: (el.textContent||'').trim().slice(0,40)})")
            print("DSA start button:", state, flush=True)
            try:
                async with page.expect_popup(timeout=8000) as pi:
                    # JS click bypasses Playwright actionability checks — the
                    # widget can leave the button covered/disabled visually.
                    await btn.evaluate("el => el.click()")
                pop = await pi.value
                await pop.wait_for_load_state("domcontentloaded", timeout=10000)
                for sel in ("a[href*='unauth=1']", ".login_footer_text a",
                            "a:has-text('without logging in')",
                            "a:has-text('Continue without')"):
                    try:
                        el = await pop.wait_for_selector(sel, timeout=2500,
                                                         state="visible")
                        if el:
                            await el.evaluate("e => e.click()")
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue
            except Exception as e:
                # no popup — the form can open in the same tab
                print("DSA popup skipped:", type(e).__name__, flush=True)
                try:
                    await btn.evaluate("el => el.click()")
                except Exception:
                    pass
                await asyncio.sleep(2)

            found = False
            for _ in range(25):
                for p in context.pages:
                    for sel in (".cd-comment-input", "textarea",
                                "[placeholder*='link' i]", "[class*='comment']"):
                        try:
                            await p.wait_for_selector(sel, timeout=500)
                            page = p
                            found = True
                            break
                        except Exception:
                            continue
                    if found:
                        break
                if found:
                    break
                await asyncio.sleep(1)
            if not found:
                return False, "DSA form not found; " + await _dump_pages(context)

            # step 1: target link
            await _fill(page, target)
            await asyncio.sleep(0.8)
            # step 2: reason radio (and its subcategory, if any)
            if not await _click(page, reason):
                return False, ("reason radio not found: " + reason + "; "
                               + await _dump_elements(page))
            await asyncio.sleep(0.8)
            sub = SUB_FOR_REASON.get(str(reason_key or "").lower())
            if sub and not await _click(page, sub):
                return False, ("sub radio not found: " + sub + "; "
                               + await _dump_elements(page))
            await asyncio.sleep(0.8)
            # step 3: complaint text, then the link once more
            await _fill(page, complaint or "Please review this content.")
            await asyncio.sleep(0.8)
            await _fill(page, target)
            await asyncio.sleep(0.8)
            # "My own behalf" step was removed on the current form —
            # only country and documentation radio remain here.
            for choice in ("Germany", "I don't have links to relevant laws"):
                if not await _click(page, choice):
                    return False, (f"radio not found: {choice}; "
                               "visible=" + await _visible_labels(page)
                               + "; els=" + await _dump_elements(page)
                               + "; pages=" + await _dump_pages(context))
                await asyncio.sleep(0.6)
            for value in (fullname, _pick(ADDRESSES), _pick(EMAILS), _pick(PHONES)):
                await _fill(page, value)
                await asyncio.sleep(0.6)
            # Current form has no separate Confirm radio — the last name
            # field with its submit button finalizes the report.
            await _fill(page, fullname)
            await asyncio.sleep(2)
            return True, ""
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        finally:
            await browser.close()
