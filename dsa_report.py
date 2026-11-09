"""DSA-framed abuse@submission for @losers_46 — Art. 20 DSA special format sends mail."""

import io
import os
import ssl
import smtplib
import random
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from pathlib import Path

BASE = Path(__file__).parent
EMAIL_POOL_FILE = BASE / "emails_valid.txt"
LOG_FILE = BASE / "dsa_tracked_log.txt"
ABUSE_TO = "dsa@telegram.org"   # this address is the DSA reporting inbox

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# DSA-framed complaint — target: @losers_46
COMPLAINT_BODY = """Dear Telegram Trust & Safety / DSA Reporting Team,

I am submitting this notice as a trusted-flagger under Regulation (EU) 2022/2065 (Digital Services Act), Article 16, for an account that operates on Telegram's public platform.

Under DSA Article 22, I request this report be processed via the trusted-flagger channel, which prioritises a rapid-handling SLA within 24-72 hours.

Affected parties: 1 minor (14 years old), self-confirmed by account
Nature of content: Distribution of non-consensual sexual imagery and pornographic content to minors, on-sale of vape/nicotine devices, subject of confirmed physical threats / school-mining threat.

Reported Telegram entity:
    Telegram user: @losers_46
    Telegram user ID: 8309667200

Specific violations observed:
1. Distribution of pornographic content to a minor in a public chat @idealizationchat, 11 October 2026, 06:55-06:58 UTC.
2. Trading of nicotine vaping devices (750-900 RUB) in @baraholkazheleznogorsk46, 23-29 April 2026.
3. Subject of on-platform blackmail involving "school will be mined", 27 October 2026, 06:01-06:02 UTC.
4. Refer to @TIDABot (Take It Down Act), DSA Content category "Illegal adult content / Distribution of non-consensual sexual imagery" and @EURegulation (EDSR) for the EU jurisdiction routing.

Requesting immediate enforcement: temporary OR permanent suspension of this account while data is preserved for the legal jursidictions concerned (EU - DSA Art. 20).

Submissions reproducible via Telegram public snapshots; further evidence archived to the reporter.

Respectfully,
- Data-protected submitter under GDPR Art. 5
- Telegram ID visible for submission-purposes only: +7 985 271 8892
"""


def smtp_send(from_email, from_pwd, msg):
    dom = from_email.rsplit("@", 1)[-1].lower()
    CFG = {
        "mail.ru":    ("smtp.mail.ru", 465, True),
        "gmail.com":  ("smtp.gmail.com", 465, True),
        "mail.com":   ("smtp.mail.com", 465, True),
        "hotmail.com": ("smtp-mail.outlook.com", 587, False),
        "rambler.ru": ("smtp.rambler.ru", 465, True),
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
    if not pool:
        print("no creds")
        return
    sender, pwd = random.choice(pool)
    msg = MIMEMultipart()
    msg["From"] = formataddr(("DSA Trusted Flagger", sender))
    msg["To"] = ABUSE_TO
    msg["Subject"] = Header("[DSA Art. 16 Report] @losers_46 (8309667200) - Adult content to minors", "utf-8")
    msg.attach(MIMEText(COMPLAINT_BODY, "plain", "utf-8"))
    ok, out = smtp_send(sender, pwd, msg)
    mark = "✅" if ok else "❌"
    line = f"{mark} DSA {sender} -> {ABUSE_TO}: {out}"
    print(line)
    with io.open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    main()
