"""Batch-validate Gmail app-password logins (IMAP)."""
import imaplib
import ssl
import sys
import io
import os
import re
from concurrent.futures import ThreadPoolExecutor

HOST = "imap.gmail.com"
PORT = 993
CTX = ssl.create_default_context()

CREDS = {
    'huyznaet06@gmail.com': 'cyeb pnyi ctpj xxdx',
    'alabuga793@gmail.com': 'tzuk rehw syaw ozme',
    'editt1345@gmail.com': 'hezf xuel hzvz jzur',
    'dlatt7055@gmail.com': 'tpzd nxle odaw uqwf',
    'dlyabravla655@gmail.com': 'kprn ihvr bgia vdys',
    'dlatt6677@gmail.com': 'usun ruef otzx zcrh',
    'edittendo0@gmail.com': 'mzdl lrmx puyq epur',
    'shshsbsbsbwbwvw@gmail.com': 'jqrx qivo qxjy jejt',
    'IvanKarma2000@gmail.com': 'irlr cggo xksq tlbb',
    'misha28272727@gmail.com': 'kgwqxvkgjyccibkm',
    'vladimiradmiralov664@gmail.com': 'papq hkip geao rkuz',
    'maksimafanacefish@gmail.com': 'hdpn tbfp acwv jyro',
    'desireelinnert0@gmail.com': 'xwzb lzla ppve hevz',
    'Ivan27727272hwhs@gmail.com': 'ozcu edfd gmgk rkqg',
}


def check(entry):
    email, pwd = entry
    pwd_clean = pwd.replace(" ", "").strip()
    client = None
    try:
        client = imaplib.IMAP4_SSL(HOST, PORT, ssl_context=CTX)
        try:
            client.login(email, pwd_clean)
            code, _ = client.select("INBOX", readonly=True)
            status = "OK"
            return (email, status, "")
        except imaplib.IMAP4.error as e:
            msg = str(e).strip()
            if "AUTHENTICATIONFAILED" in msg.upper():
                return (email, "FAIL", "wrong creds")
            if "LOCKED" in msg.upper():
                return (email, "LOCKED", msg)
            return (email, "FAIL", msg[:80])
        except Exception as e:
            return (email, "ERR", f"{type(e).__name__}:{e}"[:80])
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as e:
        return (email, "CONN", f"{type(e).__name__}:{e}"[:80])


def main():
    src = os.environ.get("CREDS_LIST", "").strip()
    if src:
        uniq = {}
        for line in src.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            em, pw = line.split("|", 1)
            uniq[em.strip()] = pw.replace(" ", "").strip()
    else:
        uniq = {k: v.replace(" ", "").strip() for k, v in CREDS.items()}

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"checking {len(uniq)} unique accounts...")

    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for row in ex.map(check, uniq.items()):
            results.append(row)
            mark = {"OK": "OK", "FAIL": "FAIL", "LOCKED": "LOCK", "ERR": "ERR", "CONN": "CONN"}.get(row[1], "?")
            print(f"  {row[1]:<6} {row[0]:<44} {row[2]}")

    ok = [r for r in results if r[1] == "OK"]
    fail = [r for r in results if r[1] != "OK"]

    with io.open("valid_accounts.txt", "a", encoding="utf-8") as f:
        for email, _, _ in ok:
            f.write(f"{email}|{uniq[email]}\n")
    with io.open("fail_accounts.txt", "a", encoding="utf-8") as f:
        for email, s, reason in fail:
            f.write(f"{email}|{uniq[email]}|{s}|{reason}\n")

    print(f"\nvalid: {len(ok)}  fail: {len(fail)}")


if __name__ == "__main__":
    main()
