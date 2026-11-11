import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
d = json.load(open("users.json", encoding="utf-8-sig"))
print("users total:", len(d))
hits = [(k, v) for k, v in d.items()
        if isinstance(v, dict) and "basyxa" in json.dumps(v).lower()]
for k, v in hits:
    print(k, json.dumps(v, ensure_ascii=False)[:400])
if not hits:
    print("no username hits — sample recs:")
    for k, v in list(d.items())[:12]:
        print(k, json.dumps(v, ensure_ascii=False)[:200])
