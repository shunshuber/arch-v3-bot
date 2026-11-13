"""One-shot SMTP test: single sender -> one external mailbox.
Runs on GH Actions (outbound 465/587 open there)."""
import asyncio
import sys
sys.path.insert(0, ".")

from snoser import _mail_load_pool, mail_send_one


async def main():
    pool = _mail_load_pool()
    if not pool:
        print("pool empty")
        return
    sender, pwd, host = pool[0]
    print(f"sender: {sender[:2]}***@{sender.split('@')[1]} via {host}")
    to = "darknet.sucks@proton.me"
    subject = "test"
    body = ("This is a test message from Arch V3 mail-method.\n"
            "If you read this, SMTP delivery works.")
    ok, err = await mail_send_one(sender, pwd, host, to, subject, body)
    print("RESULT:", "OK" if ok else f"FAIL {err}")


asyncio.run(main())