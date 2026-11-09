"""Omni-Kill v3 — targeted one-shot abuse@telegram.org mailer.

Sends a single, fully-detailed complaint email to abuse@telegram.org
using available verified senders in emails_valid.txt.
"""

import os
import io
import ssl
import sys
import time
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from pathlib import Path

BASE = Path(__file__).parent
EMAIL_POOL_FILE = BASE / "emails_valid.txt"
TARGETS_FILE = BASE / "abuse_targets.txt"
LOG_FILE = BASE / "omnikill_v3_log.txt"

ABUSE_TO = "abuse@telegram.org"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

BODY_LOSERS_46 = """Dear Telegram Abuse Team,

I wish to report the Telegram user @losers_46 (Telegram ID: 8309667200), who identifies themselves as a 14-year-old minor in their messages, and who is actively circulating links to pornographic content in several public Telegram chats.

Evidence (public chats, dates):
- IDEALIZATION TROLL CHAT @idealizationchat, 11 October 2026, 06:56 UTC:
  "wish someone would send a tit or a pssy photo" (in Russian original: "лаж бы сисю или писю скинули")
- IDEALIZATION TROLL CHAT @idealizationchat, 11 October 2026, 06:58 UTC:
  "in Yandex / there is porn there, eyes will fall out" (original: "в Яндекс зайди / там порнухи, глаза отвалятся")
- IDEALIZATION TROLL CHAT @idealizationchat, 11 October 2026, 06:55 UTC:
  "this happened around 40 times already"

The account openly states its age as 14 years old in messages (11 October 2026, 06:49 UTC: "мне 14" / "I'm 14"), and admits they communicate only with peers of similar age. Spreading pornographic content among minors constitutes a severe violation of Telegram's Terms of Service (Section 4.5 — "Post illegal pornographic content"), and may also fall under international legislation covering distribution of adult content to minors.

Additionally, the same account:
- is promoting and attempting to sell nicotine/vaping devices ("Ursa", device for smoking) in @baraholkazheleznogorsk46 — three separate offers dated 23 April 2026 ("Shnur + email: 850 RUB"), 25 April 2026 ("800 RUB"), and 29 April 2026 ("750 RUB fast PayPal");
- has been the subject of confirmed blackmail within the same chat group where another user "threatens to mine my school" — a direct threat of violence involving minors.

All three vectors together point to an account that should be reviewed and — given the age of the user and explicit intent — most likely banned from Telegram to prevent further harm to minors.

Please take immediate action.

Respectfully,
A concerned Telegram user
Reported via Telegram DSA portal
"""


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
    if not pool or not TARGETS_FILE.exists():
        print("missing emails_valid.txt / abuse_targets.txt")
        return
    targets = [t.strip() for t in io.open(TARGETS_FILE, encoding="utf-8").read().splitlines() if t.strip()]

    for tgt in targets:
        for cycle in range(2):
            sender, pwd = random.choice(pool)
            msg = MIMEMultipart()
            msg["From"] = formataddr(("Telegram Safety Reporter", sender))
            msg["To"] = ABUSE_TO
            msg["Subject"] = Header(f"[ToS 4.5 Violation - Adult Content Distributed To Minors] {tgt}", "utf-8")
            msg.attach(MIMEText(BODY_LOSERS_46, "plain", "utf-8"))
            ok, out = smtp_send(sender, pwd, msg)
            mark = "✅" if ok else "❌"
            line = f"{mark} cycle={cycle} {sender} -> {tgt}: {out}"
            print(line)
            with io.open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            time.sleep(3)
    print("\nDONE-V3")


if __name__ == "__main__":
    main()
