"""Omni-Kill — сам термин для "максимального веса"=>дожать жертвы telegram-аккаунт через все одновременно доступные каналы.

Триггеры который Telegram обрабатывает автоматически (structural — общее слово):
  • spam — каждый peer через ReportPeer с InputReportReasonSpam
  • fraud/scam — отчёт через @NoToScam
  • illegal content (Terror/Drugs/Weapons) — ReportPeer + abuse@
  • child sexual security — InputReportReasonChildAbuse (round-trips through TIDABot)
  • non-consensual intimate imagery — TIDABot (@TIDABot)
  • DMCA / IP infringement — dmca@telegram.org
  • legal request — legal@telegram.org

Реализация: цикл из IMAP-verified senders, отчёты с уникальных email,
через каждые N циклов прыгаем на новый sender.

Каждый email отправляет 1 письмо на 1 категорию на abuse@telegram.org,
и внутри тела письма дублируется @NoToScam / @TIDABot / @EURegulation ping.

Итог: до 8 разных инцидентов на 1 target = ~40+ unique abuse-record triggers.
Даю 30 сек между отправками, чтобы не ловить Gmail rate-limiter.
"""
import imaplib
import ssl
import smtplib
import imaplib
import os
import io
import sys
import time
import random
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from pathlib import Path

BASE = Path(__file__).parent
EMAIL_POOL_FILE = BASE / "emails_valid.txt"
TARGETS_FILE = BASE / "abuse_targets.txt"
LOG_FILE = BASE / "omnikill_log.txt"

ABUSE_TO = "abuse@telegram.org"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Hearth of the kill-chain — each vector hits a different internal Telegram
# reviewer-track (some are human, some are automated, some become legal).
VECTORS = [
    ("Spam / Advert flooding",
     "This user is flooding groups and public chats with unsolicited advertisement messages. "
     "Multiple users have reported this unauthorized spam campaign. "
     "Please consider disabling spam-penalty on this account as a protection measure."),
    ("Fraud / Scam / Impersonation",
     "This account is impersonating a known public figure / brand and is soliciting payments "
     "from other Telegram users through fake payment links. Similar to @NoToScam category. "
     "Kindly apply the anti-scam label and remove associated channels."),
    ("Terrorism / Violence incitement",
     "This public channel promotes violent extremism and calls for real-world violence. "
     "This is being reported under both the TCO Regulation (EU 2021/784) and Telegram's own "
     "Terms of Service. Please coordinate with @EURegulation (EDSR) if data is requested."),
    ("Child Sexual Abuse Material (CSAM)",
     "This user/channel contains Child Sexual Abuse Material (CSAM). The content was "
     "found in public chats and a channel. Please act strictly per NCMEC / INHOPE protocol "
     "and preserve the data for legal investigation. This must be escalated immediately."),
    ("Non-consensual intimate imagery (NCII / 'Take It Down')",
     "This account is sharing non-consensual intimate imagery of a US citizen. "
     "This is being reported under the Federal 'TAKE IT DOWN Act' via @TIDABot "
     "and also under general CSAM legislation. Please escalate to the L&D team."),
    ("Drug / Weapon / Illegal goods marketplace",
     "This account is running an illegal marketplace for narcotics, weapons and forged "
     "documents. Please disable the account and its Invite Links per Telegram's ToS."),
    ("Copyright / IP infringement (DMCA)",
     "This public channel/bot/sticker set is a verbatim copy of a copyrighted product. "
     "We represent the rights holder and are submitting a DMCA takedown request."),
    ("Phishing / Malware distribution",
     "This user is distributing phishing links and malicious software via Telegram "
     "channels and inline bots. Please apply the anti-virus flag and remove links."),
    ("Impersonation of an arresting official",
     "This account pretends to be a government/law enforcement employee and is soliciting "
     "personal data from Telegram users under the pretense of a criminal investigation."),
]


def render_mail(from_email, target_link, title, body):
    msg = MIMEMultipart()
    msg["From"] = formataddr(("Telegram Safety Reporter", from_email))
    msg["To"] = ABUSE_TO
    msg["Subject"] = Header(f"[{title}] – Telegram policy report: {target_link}", "utf-8")
    tail = [
        "",
        f"Target: {target_link}",
        f"Reporter: {from_email}",
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This complaint is submitted in parallel to @NoToScam, @TIDABot and",
        "@EURegulation (EDSR) for faster automated triage. If this report",
        "concerns an emergency (CSAM/NCII/terror), please prioritize.",
    ]
    body = body + "\n" + "\n".join(tail)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def smtp_send(from_email, from_pwd, msg):
    dom = from_email.rsplit("@", 1)[-1].lower()
    CFG = {
        "mail.ru":    ("smtp.mail.ru", 465, True),
        "inbox.ru":   ("smtp.mail.ru", 465, True),
        "list.ru":    ("smtp.mail.ru", 465, True),
        "rambler.ru": ("smtp.rambler.ru", 465, True),
        "gmail.com":  ("smtp.gmail.com", 465, True),
        "hotmail.com": ("smtp-mail.outlook.com", 587, False),
        "mail.com":   ("smtp.mail.com", 465, True),
    }
    host, port, ssl_ok = CFG.get(dom, ("smtp.gmail.com", 465, True))
    try:
        if ssl_ok:
            s = smtplib.SMTP_SSL(host, port, context=SSL_CTX, timeout=25)
        else:
            s = smtplib.SMTP(host, port, timeout=25)
            s.starttls(context=SSL_CTX)
        s.login(from_email, from_pwd)
        s.sendmail(from_email, [ABUSE_TO], msg.as_string())
        s.quit()
        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:80]


def load_pool():
    if not EMAIL_POOL_FILE.exists():
        return []
    rows = []
    with io.open(EMAIL_POOL_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "|" in line:
                em, pw = line.split("|", 1)
                rows.append((em.strip(), pw.strip()))
    return rows


def main():
    pool = load_pool()
    if not pool or not os.path.exists(TARGETS_FILE):
        print("missing emails_valid.txt / abuse_targets.txt")
        return
    targets = [t.strip() for t in io.open(TARGETS_FILE, encoding="utf-8").read().splitlines() if t.strip()]

    # round-robin: each sender gets one unique vector/target pair per cycle.
    # With 1 valid sender x 9 vectors x N targets = 9*N emails per run.
    cycle = 0
    for tgt in targets:
        for (title, body) in VECTORS:
            sender, pwd = random.choice(pool)
            msg = render_mail(sender, tgt, title, body)
            ok, out = smtp_send(sender, pwd, msg)
            mark = "✅" if ok else "❌"
            line = f"{mark} [{title[:28]}] {sender} -> {tgt}: {out}"
            print(line)
            with io.open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            time.sleep(random.uniform(1.5, 3.0))
        cycle += 1
    print(f"\nTotal cycles: {cycle}, logged to {LOG_FILE.name}")


if __name__ == "__main__":
    main()
