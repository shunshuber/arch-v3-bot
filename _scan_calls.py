# -*- coding: utf-8 -*-
import re
src = open("snoser.py", encoding="utf-8").read()
print("triple-quote lines:", src.count('"""'))
for pat in ["await msg.answer(", "await message.answer(",
            "await cb.message.answer(", ".edit_caption(",
            "await bot.send_message(", "await client.send_message(",
            ".edit_text(", ".answer_photo(", "await cb.answer(",
            "msg.answer(", "send_message(", "edit_caption("]:
    print(f"{src.count(pat):4}  {pat}")
