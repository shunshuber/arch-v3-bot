"""One-shot targeted report launcher (no Telegram sessions needed).

Fires the mail vector (SMTP senders, 1/3 rotating pool, unique texts per
email) and optionally the web vector (support-form posts) against ONE
target with the chosen themes. Runs on GitHub Actions:
    python targeted_report.py "<target>" "<evidence>" porn,sexwork 1

Logs land in the Logs channel (BOT_TOKEN + LOGS_CHAT_ID env).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snoser  # noqa: E402


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    evidence = sys.argv[2] if len(sys.argv) > 2 else ""
    reasons = [r.strip() for r in (sys.argv[3] if len(sys.argv) > 3
                                   else "sexwork,porn").split(",") if r.strip()]
    web = len(sys.argv) > 4 and sys.argv[4] == "1"
    if not target:
        print("[TARGETED] no target given", flush=True)
        return
    # the violator string carries the account AND the evidence post link
    violator = target + (f" — пост: {evidence}" if evidence else "")

    # Logs-channel logging works outside the bot process too
    if os.getenv("BOT_TOKEN"):
        try:
            from aiogram import Bot
            snoser._BOT = Bot(os.getenv("BOT_TOKEN"))
        except Exception as e:
            print(f"[TARGETED] logs bot unavailable: {e}", flush=True)

    for r in reasons:
        label = snoser.REASONS.get(r, snoser.REASONS["other"])["l"]
        print(f"[TARGETED] mail campaign: {violator} theme={r} ({label})",
              flush=True)
        try:
            res = await snoser.mail_bulk_send(violator, r)
            print(f"[TARGETED] mail {r}: ok={res['ok']} fail={res['fail']} "
                  f"total={res['total']}", flush=True)
        except Exception as e:
            print(f"[TARGETED] mail {r} crashed: {type(e).__name__}: {e}",
                  flush=True)
        if web:
            print(f"[TARGETED] web shots: {violator} theme={r}", flush=True)
            try:
                wres = await snoser.fire_web_reports(
                    violator, label, "", r)
                print(f"[TARGETED] web {r}: ok={wres['ok']} "
                      f"fail={wres['fail']} total={wres['total']}", flush=True)
            except Exception as e:
                print(f"[TARGETED] web {r} failed: {type(e).__name__}: {e}",
                      flush=True)


if __name__ == "__main__":
    asyncio.run(main())
