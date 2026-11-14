# -*- coding: utf-8 -*-
"""One-shot patcher v2: premium custom emoji (pack tgmacicons).

Regex-based parse_mode detection (multiline kwargs supported)."""
import json
import re

P = "snoser.py"
src = open(P, encoding="utf-8").read()

emap = json.load(open("_emoji_map.json", encoding="utf-8"))
pairs = sorted(emap.items(), key=lambda kv: -len(kv[0]))

dict_lines = ["_CUSTOM_EMOJI = {"]
for ch, eid in pairs:
    dict_lines.append(f"    {ch!r}: {eid!r},")
dict_lines.append("}")
DICT_SRC = "\n".join(dict_lines)

CX_SRC = '''

def _cx(text: str) -> str:
    """Swap plain emoji chars for <tg-emoji> custom entities (premium pack
    tgmacicons). Idempotent: existing <tg-emoji> blocks pass through."""
    if not text:
        return text
    parts = re.split(r"(<tg-emoji\\s[^>]*>.*?</tg-emoji>)", text)
    for i, part in enumerate(parts):
        if i % 2 == 1:
            continue
        for ch, eid in _CUSTOM_EMOJI.items():
            if ch in part:
                part = part.replace(
                    ch, f'<tg-emoji emoji-id="{eid}">{ch}</tg-emoji>')
        parts[i] = part
    return "".join(parts)
'''

BLOCK = ("\n# ── premium custom emoji (pack: t.me/addemoji/tgmacicons) ──\n"
         + DICT_SRC + CX_SRC + "\n")

anchor = "MAINTENANCE_ADMIN_IDS = {8661362112}"
ia = src.index(anchor)
src = src[:ia] + BLOCK + "\n" + src[ia:]

PM_RE = re.compile(r",\s*parse_mode=ParseMode\.HTML")


def skip_str(s, k):
    """Skip a string starting at quote k; return index after it."""
    triple = s[k:k + 3] in ('"""', "'''")
    q = s[k:k + 3] if triple else s[k]
    j = k + len(q)
    n = len(s)
    while j < n:
        if s[j] == "\\":
            j += 2
            continue
        if s.startswith(q, j):
            return j + len(q)
        j += 1
    return n


def scan_arg(s, k):
    """Scan an expression from k to its matching close bracket at depth 1.
    Returns (end_index_of_close, close_pos)."""
    n = len(s)
    depth = 1
    while k < n:
        c = s[k]
        if c == "#":
            k = s.find("\n", k)
            if k < 0:
                k = n
            continue
        if c in "\"'":
            k = skip_str(s, k)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return -1


def first_top_comma(s, start, end):
    n = len(s)
    k = start
    while k < end:
        c = s[k]
        if c == "#":
            k = s.find("\n", k)
            if k < 0 or k > end:
                return -1
            continue
        if c in "\"'":
            k = skip_str(s, k)
            if k > end:
                return -1
            continue
        if c in "([{":
            k = scan_arg(s, k)
            if k < 0:
                return -1
            continue
        if c == ",":
            return k
        k += 1
    return -1


edits = []  # (offset, text) inserts, applied desc

# generic first-arg wraps: msg.answer( / message.answer( / edit_text(
for pat in ["msg.answer(", "message.answer(", "msg.edit_text(",
            "message.edit_text("]:
    i = 0
    n = len(src)
    while True:
        i = src.find(pat, i)
        if i < 0:
            break
        op = i + len(pat) - 1
        nxt = src[op + 1] if op + 1 < n else ""
        if nxt == "_":          # answer_photo / answer_poll etc.
            i = op + 1
            continue
        close = scan_arg(src, op + 1)
        if close < 0:
            i = op + 1
            continue
        seg = src[op:close]
        m = PM_RE.search(seg)
        if not m:
            i = op + 1
            continue
        edits.append((op + 1, "_cx("))
        pm_abs = op + m.start()
        edits.append((pm_abs, ")"))
        i = close
        continue

# caption kwarg wraps: edit_caption / answer_photo
for pat in ["edit_caption(", "answer_photo("]:
    i = 0
    while True:
        i = src.find(pat, i)
        if i < 0:
            break
        op = i + len(pat) - 1
        cap = src.find("caption=", op)
        close_call = scan_arg(src, op + 1)
        if cap < 0 or close_call < 0 or cap > close_call:
            i = op + 1
            continue
        a = cap + len("caption=")
        close_cap = scan_arg(src, a)
        if close_cap < 0:
            i = op + 1
            continue
        seg = src[op:close_call]
        if not PM_RE.search(seg):
            i = op + 1
            continue
        edits.append((a, "_cx("))
        m = PM_RE.search(seg)
        edits.append((op + m.start(), ")"))
        i = close_call
        continue

# chat_id-first sends: wrap the second argument
for pat in ["bot.send_message(", "_BOT.send_message(",
            "client.send_message("]:
    i = 0
    while True:
        i = src.find(pat, i)
        if i < 0:
            break
        op = i + len(pat) - 1
        close = scan_arg(src, op + 1)
        if close < 0:
            i = op + 1
            continue
        seg = src[op:close]
        if not PM_RE.search(seg):
            i = op + 1
            continue
        c1 = first_top_comma(src, op + 1, close)
        if c1 < 0:
            i = op + 1
            continue
        edits.append((c1 + 1, " _cx("))
        m = PM_RE.search(seg)
        edits.append((op + m.start(), ")"))
        i = close
        continue

edits.sort(key=lambda t: -t[0])
for off, txt in edits:
    src = src[:off] + txt + src[off:]
print("send calls wrapped:", len(edits) // 2)

# gate message branch: entities + HTML (callback alert stays plain)
gate_old = "                await event.message.answer(text)"
gate_new = ("                await event.message.answer(\n"
            "                    _cx(text), parse_mode=ParseMode.HTML)")
assert src.count(gate_old) == 1, "gate answer not found"
src = src.replace(gate_old, gate_new)

# plain-mode replies carrying emoji -> HTML + wrap
def rx_sub(pattern, repl_fmt):
    global src
    m = list(re.finditer(pattern, src))
    assert m, f"{pattern}: no matches"
    src = re.sub(pattern, repl_fmt, src, count=len(m))

rx_sub(r'await msg\.answer\("(.{1,3}? Команда для админов\.)"\)',
       r'await msg.answer(_cx("\1"),\n                         parse_mode=ParseMode.HTML)')
rx_sub(r'await msg\.answer\("(.{1,3}? Нужно целое положительное число дней\.)"\)',
       r'await msg.answer(_cx("\1"),\n                         parse_mode=ParseMode.HTML)')
rx_sub(r'await msg\.answer\(f"(.{1,3}? Токен уже есть / лимит \(\{n\}\))"\)',
       r'await msg.answer(_cx(f"\1"),\n                         parse_mode=ParseMode.HTML)')

open(P, "w", encoding="utf-8", newline="\n").write(src)
print("patched ok")
