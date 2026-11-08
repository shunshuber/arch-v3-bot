"""Valid Gmail sender emails pool — verified via IMAP through GH Actions.

Format: file emails_valid.txt, one line per entry: email|password.
The bot's web reporter prefers these (already warmed, no captcha-ban risk).
"""

import random
import io
from pathlib import Path

EMAILS_FILE = Path(__file__).parent / "emails_valid.txt"

_POOL: list[tuple[str, str]] = []


def load_email_pool() -> list[tuple[str, str]]:
    global _POOL
    if _POOL:
        return _POOL
    if EMAILS_FILE.exists():
        try:
            for line in EMAILS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "|" in line:
                    em, pw = line.split("|", 1)
                    _POOL.append((em.strip(), pw.strip()))
        except Exception:
            pass
    return _POOL


def pick_valid_email() -> str:
    pool = load_email_pool()
    if not pool:
        return ""
    return random.choice(pool)[0]
