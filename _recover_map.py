# -*- coding: utf-8 -*-
"""Recover cp866 mojibake keys -> real emoji chars; inventory snoser.py."""
import json

raw = json.load(open("_emoji_map.json", encoding="utf-8"))
clean = {}
skipped = []
for moji, eid in raw.items():
    try:
        key = moji.encode("cp866").decode("utf-8")
        clean[key] = eid
    except Exception:
        skipped.append(moji)

print("recovered:", len(clean), "skipped:", len(skipped))
for k in skipped:
    print("  SKIP", repr(k))

json.dump(clean, open("_emoji_map.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# inventory: which of these chars appear in snoser.py, and on which line kinds
src = open("snoser.py", encoding="utf-8").read().split("\n")
hits = {}
for n, ln in enumerate(src, 1):
    for ch in clean:
        if ch in ln:
            hits.setdefault(ch, []).append(n)

print("\nchars present in snoser.py:")
present = {}
for ch, lns in sorted(hits.items()):
    btn = any("InlineKeyboardButton" in src[l-1] or "callback_data" in src[l-1]
              for l in lns[:20])
    present[ch] = lns
    ctx = src[lns[0]-1].strip()[:90]
    print(f"  {'BTN!' if btn else 'txt '} {ch!r} x{len(lns)}  e.g. L{lns[0]}: {ctx}")

json.dump(present, open("_emoji_hits.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
