"""Mass abuse@telegram.org mailer via IMAP-verified creds.

Providers: mail.ru / rambler.ru / gmail / hotmail / mail.com
Uses SMTP (465 SSL / starttls 587) per provider.
Runs from GH Actions (outbound 25/465/587 is open there).
"""
import os
import ssl
import smtplib
import imaplib
import random
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv()

ABUSE_TO = "abuse@telegram.org"
SMTP_HOSTS = {
    "mail.ru":    ("smtp.mail.ru", 465),
    "inbox.ru":   ("smtp.mail.ru", 465),
    "list.ru":    ("smtp.mail.ru", 465),
    "bk.ru":      ("smtp.mail.ru", 465),
    "rambler.ru": ("smtp.rambler.ru", 465),
    "lenta.ru":   ("smtp.rambler.ru", 465),
    "gmail.com":  ("smtp.gmail.com", 465),
    "hotmail.com": ("smtp-mail.outlook.com", 587),  # STARTTLS
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "live.com":   ("smtp-mail.outlook.com", 587),
    "mail.com":   ("smtp.mail.com", 465),
    "usa.com":    ("smtp.mail.com", 465),
    "email.com":  ("smtp.mail.com", 465),
}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def smtp_config_for(email: str):
    dom = email.rsplit("@", 1)[-1].lower()
    if dom in SMTP_HOSTS:
        return SMTP_HOSTS[dom]
    # try default mail.com
    return ("smtp.mail.com", 465)


def imap_check(email, pwd):
    dom = email.rsplit("@", 1)[-1].lower()
    IMAP_HOSTS = {
        "mail.ru": ("imap.mail.ru", 993),
        "rambler.ru": ("imap.rambler.ru", 993),
        "gmail.com": ("imap.gmail.com", 993),
        "mail.com": ("imap.mail.com", 993),
    }
    if dom not in IMAP_HOSTS:
        return False, "no-imap"
    host, port = IMAP_HOSTS[dom]
    try:
        c = imaplib.IMAP4_SSL(host, port, ssl_context=SSL_CTX)
        c.login(email, pwd)
        c.logout()
        return True, "authorized"
    except imaplib.IMAP4.error as e:
        return False, str(e)[:60]
    except Exception as e:
        return False, f"{type(e).__name__}"


def send_one_abuse(from_email, from_pwd, target_link, reason, comment=""):
    host, port = smtp_config_for(from_email)
    dom = from_email.rsplit("@", 1)[-1].lower()

    msg = MIMEMultipart()
    msg["From"] = formataddr(("Telegram User", from_email))
    msg["To"] = ABUSE_TO
    msg["Subject"] = Header(f"Complaint about Telegram violation: {target_link}", "utf-8")

    body_lines = [
        "Dear Telegram Support,",
        "",
        f"I would like to report the following Telegram entity for policy violations:",
        "",
        f"Target: {target_link}",
        f"Violation type: {reason}",
    ]
    if comment.strip():
        body_lines.append(f"Details: {comment.strip()}")
    body_lines += [
        "",
        "Please review this account/channel/bot and take the necessary measures.",
        "",
        f"Reported by: {from_email}",
        f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    msg.attach(MIMEText("\n".join(body_lines), "plain", "utf-8"))

    try:
        if dom == "hotmail.com" or dom == "outlook.com" or dom == "live.com":
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls(context=SSL_CTX)
        else:
            server = smtplib.SMTP_SSL(host, port, context=SSL_CTX, timeout=20)
        server.login(from_email, from_pwd)
        server.sendmail(from_email, [ABUSE_TO], msg.as_string())
        server.quit()
        return True, "sent"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"auth: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def imap_check_all(creds_file="emails_valid.txt"):
    """Verify all creds from file before sending."""
    if not os.path.exists(creds_file):
        return []
    rows = []
    with io.open(creds_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "|" not in line:
                continue
            em, pw = line.split("|", 1)
            rows.append((em.strip(), pw.strip()))
    return rows


def main():
    targets = open("abuse_targets.txt", encoding="utf-8").read().splitlines() if os.path.exists("abuse_targets.txt") else ["@durov"]
    reason = os.environ.get("ABUSE_REASON", "spam")
    comment = os.environ.get("ABUSE_COMMENT", "")
    creds = imap_check_all("emails_valid.txt")
    print(f"creds pool: {len(creds)}, targets: {len(targets)}")
    if not creds:
        print("no valid creds — add to emails_valid.txt")
        return

    results = []
    with ThreadPoolExecutor(max_workers=1) as ex:
        for tgt in targets:
            for em, pw in creds:
                ok, out = send_one_abuse(em, pw, tgt, reason, comment)
                mark = "✅" if ok else "❌"
                print(f"  {mark} {em} -> {tgt}: {out}")
                results.append((em, tgt, ok, out))
                time.sleep(2)  # rate limit per account

    valid = [r for r in results if r[2]]
    print(f"\nAbuse mails sent successfully: {len(valid)} / {len(results)}")
    with io.open("abuse_sent.txt", "w", encoding="utf-8") as f:
        for em, tgt, ok, out in results:
            f.write(f"{em} -> {tgt} | {'OK' if ok else 'FAIL: ' + out}\n")


if __name__ == "__main__":
    main()
