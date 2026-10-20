"""ทดสอบเกม Hangman: ตรรกะ + สมองแบ็คลี่ + ปุ่ม/เมนู/ช่องกรอก (ของปลอม)   รัน: PYTHONPATH=. python3 tests/test_hangman.py"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
import discord  # noqa: E402
from _fakes import I, Msg, U  # noqa: E402
from bagley.features.games import hangman as hm  # noqa: E402

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


# ---- คลังคำ
check("คำอังกฤษเป็น a–z ล้วน", all(w.isalpha() and w.islower() and w.isascii() for w in hm.word_pool("en")))
check("คำไทยทุกคำมีพยัญชนะให้ทาย", all(hm._targets(w, "th") for w in hm.word_pool("th")))

# ---- ตรรกะอังกฤษ
g = hm.HangmanGame("tiger", "en", "สัตว์")
check("ทายถูก = hit", g.guess_letter("T") == "hit" and "t" in g.guessed)
check("ทายซ้ำ = dup (ไม่เสียหัวใจ)", g.guess_letter("t") == "dup" and g.lives_left == 6)
check("ทายผิด = miss เสียหัวใจ", g.guess_letter("z") == "miss" and g.lives_left == 5)
check("อักขระไม่ถูก = invalid", all(g.guess_letter(x) == "invalid" for x in ("", "ab", "1", "ก", " ")))
check("แสดงผลซ่อนตัวที่ยังไม่เจอ", g.display() == "T _ _ _ _")
for c in "iger":
    g.guess_letter(c)
check("เปิดครบ = ชนะ", g.status == "won" and g.display() == "T I G E R")
g = hm.HangmanGame("tiger")
for c in "abcdfh":
    g.guess_letter(c)
check("ผิด 6 ครั้ง = แพ้", g.status == "lost" and g.lives_lost == 6)
g = hm.HangmanGame("tiger")
check("ทายทั้งคำถูก = ชนะทันที", g.guess_word(" TIGER ") is True and g.status == "won")
g = hm.HangmanGame("tiger")
check("ทายทั้งคำผิด = เสียหัวใจ 1 ดวง", g.guess_word("lions") is False and g.lives_left == 5 and g.status == "playing")
check("ทายทั้งคำว่างเปล่า = None", g.guess_word("  ") is None and g.lives_left == 5)

# ---- ใบ้
g = hm.HangmanGame("tiger")
ch = g.hint(random.Random(1))
check("ใบ้เปิดตัวที่มีจริง เสียหัวใจ 1", ch in "tiger" and g.lives_left == 5 and g.hints_used == 1)
g = hm.HangmanGame("tiger")
g.wrong_letters = list("abcdf")                         # เหลือหัวใจ 1 ดวง
check("เหลือหัวใจ 1 ดวง ขอใบ้ไม่ได้", not g.can_hint()[0] and g.hint() is None)
g = hm.HangmanGame("tiger")
for c in "tige":
    g.guess_letter(c)
check("เหลือตัวสุดท้ายตัวเดียว ขอใบ้ไม่ได้", not g.can_hint()[0])

# ---- สมองแบ็คลี่
rng = random.Random(7)
solved = 0
used_repeat = False
for w in hm.word_pool("en"):
    g = hm.HangmanGame(w, "en")
    while g.status == "playing":
        c = g.bot_guess()
        if c is None or c in g.guessed:
            used_repeat = True
            break
        g.guess_letter(c)
    solved += g.status == "won"
check("แบ็คลี่ไม่เดาตัวซ้ำ", not used_repeat)
check("แบ็คลี่เดาคำในคลังได้ส่วนใหญ่ (>80%)", solved > 0.8 * len(hm.word_pool("en")), f"{solved}/{len(hm.word_pool('en'))}")
g = hm.HangmanGame("tiger")
g.wrong_letters = list("e")
g.guessed |= set("e")
check("แบ็คลี่ไม่เดาตัวที่ผิดไปแล้ว", g.bot_guess() != "e")
g = hm.HangmanGame("xyzzy-nothing"[:5], "en")
check("คำนอกคลัง แบ็คลี่ยังคืนตัวอักษรได้ (ถอยไปใช้ความถี่)", g.bot_guess() is not None)

# ---- ไทย
t = hm.HangmanGame("ช้าง", "th", "สัตว์")
check("ไทย: ซ่อนเฉพาะพยัญชนะ สระ/วรรณยุกต์โชว์", "▢้" in t.display() and "า" in t.display())
check("ไทย: ทายพยัญชนะถูก", t.guess_letter("ช") == "hit" and "ช" in t.display())
check("ไทย: สระ/วรรณยุกต์/ตัวอังกฤษ = invalid", all(t.guess_letter(x) == "invalid" for x in ("า", "้", "a")))
t.guess_letter("ง")
check("ไทย: เปิดพยัญชนะครบ = ชนะ", t.status == "won")
tt = hm.HangmanGame("ต้มยำกุ้ง", "th")
check("ไทย: แยกหน่วยไม่ทำให้เครื่องหมายหลุด", "".join(a + b for a, b, _ in hm.thai_units("ต้มยำกุ้ง")) == "ต้มยำกุ้ง")
rng = random.Random(2)
ok_th = 0
for w in hm.word_pool("th"):
    g = hm.HangmanGame(w, "th")
    while g.status == "playing":
        c = g.bot_guess()
        if c is None:
            break
        g.guess_letter(c)
    ok_th += g.status == "won"
check("ไทย: แบ็คลี่เดาคำในคลังได้ส่วนใหญ่ (>80%)", ok_th > 0.8 * len(hm.word_pool("th")), f"{ok_th}/{len(hm.word_pool('th'))}")
check("norm_lang", hm.norm_lang("ไทย") == "th" and hm.norm_lang("อังกฤษ") == "en" and hm.norm_lang(None) == "en")


# ---- Discord (ของปลอม)
async def main():
    host, a, b, admin = U(1, "ชะอม"), U(2, "เพื่อน"), U(3, "คนแปลกหน้า"), U(4, "แอดมิน", manage=True)
    sent = []

    async def send(*args, **kw):
        sent.append((args, kw))
        return Msg()

    hm._active.clear()
    v = await hm.start_hangman(send, 100, host, "en", "สัตว์")
    check("เปิดเกม: มีกระดานและเมนูตัวอักษร 2 อัน", v is not None and "Hangman" in sent[0][1]["content"]
          and sum(isinstance(c, discord.ui.Select) for c in v.children) == 2)
    check("ช่องเดียวกันเปิดซ้อนไม่ได้", await hm.start_hangman(send, 100, a) is None and "อยู่แล้ว" in sent[1][0][0])
    v.game = hm.HangmanGame("tiger", "en", "สัตว์")
    v.build()

    sel = next(c for c in v.children if isinstance(c, discord.ui.Select) and any(o.value == "t" for o in c.options))
    sel.values = ["t"]
    i = I(a)
    await sel.callback(i)
    check("เลือกตัวจากเมนู: ถูก + แก้ข้อความ", "t" in v.game.guessed and i.response.edited and "ถูก" in i.response.edited[0]["content"])
    check("ตัวที่ทายแล้วหายจากเมนู", all(o.value != "t" for c in v.children if isinstance(c, discord.ui.Select) for o in c.options))
    sel2 = next(c for c in v.children if isinstance(c, discord.ui.Select) and any(o.value == "z" for o in c.options))
    sel2.values = ["z"]
    i = I(b)
    await sel2.callback(i)
    check("คนอื่นทายผิดได้ (เล่นรวมกัน) เสียหัวใจ", v.game.lives_left == 5)

    btns = {c.label: c for c in v.children if isinstance(c, discord.ui.Button)}
    i = I(a)
    await btns["ทายทั้งคำ"].callback(i)
    check("ปุ่มทายทั้งคำเปิดช่องกรอก", i.response.modals and i.response.modals[0].title == "ทายทั้งคำ")
    modal = i.response.modals[0]
    modal.box.value = "lions"
    i = I(a)
    await modal.on_submit(i)
    check("ทายทั้งคำผิด เสียหัวใจ", v.game.lives_left == 4 and i.response.edited)
    i = I(a)
    await btns["ใบ้ (-1 หัวใจ)"].callback(i)
    check("ปุ่มใบ้: เปิดตัวให้ + เสียหัวใจ", v.game.hints_used == 1 and v.game.lives_left == 3)
    i = I(b)
    await btns["ให้แบ็คลี่เดา"].callback(i)
    check("ปุ่มแบ็คลี่เดา: มีตัวใหม่ถูกเดา", i.response.edited and "แบ็คลี่" in i.response.edited[0]["content"])

    i = I(b)
    await btns["จบเกม"].callback(i)
    check("คนทั่วไปจบเกมไม่ได้", i.response.sent and "เฉพาะ" in i.response.sent[0] and hm.get_active(100) is v)

    # ชนะ: ทายทั้งคำ -> ปิดเกม ปลดห้อง เครดิตคนทาย
    v.game = hm.HangmanGame("tiger", "en", "สัตว์")
    v.build()
    modal = hm._GuessModal(v, "word")
    modal.box.value = "tiger"
    i = I(a)
    await modal.on_submit(i)
    out = i.response.edited[0]["content"]
    check("ทายถูก: ประกาศชนะ + เฉลย + ชมคนทาย", "ชนะ" in out and "TIGER" in out and "เพื่อน" in out)
    check("เกมจบ: ปลดห้อง ไม่มีปุ่มค้าง", hm.get_active(100) is None and not v.children)
    i = I(a)
    await v.do_letter(i, "x")
    check("เกมจบแล้วกดต่อไม่ได้", i.response.sent and "จบแล้ว" in i.response.sent[0])

    # ไทย: ใช้ปุ่ม + ช่องกรอกตัวเดียว
    v2 = await hm.start_hangman(send, 101, host, "th")
    v2.game = hm.HangmanGame("ช้าง", "th", "สัตว์")
    v2.build()
    check("ไทย: ไม่มีเมนูอังกฤษ มีปุ่มทายพยัญชนะ", not any(isinstance(c, discord.ui.Select) for c in v2.children)
          and any(getattr(c, "label", "") == "ทายพยัญชนะ" for c in v2.children))
    i = I(a)
    await v2.do_letter(i, "า")
    check("ไทย: ใส่สระ -> ปฏิเสธ ไม่เสียหัวใจ", i.response.sent and v2.game.lives_left == 6)
    i = I(a)
    await v2.do_letter(i, "ช")
    check("ไทย: ทายพยัญชนะถูก", "ช" in v2.game.guessed and i.response.edited)

    # แอดมินจบเกมได้ / เฉลยคำ
    btns2 = {c.label: c for c in v2.children if isinstance(c, discord.ui.Button)}
    i = I(admin)
    await btns2["จบเกม"].callback(i)
    check("แอดมินจบเกมได้ + เฉลยคำ", hm.get_active(101) is None and "ช้าง" in i.response.edited[0]["content"])

    # force_end (/hangman_end) และหมดเวลา
    v3 = await hm.start_hangman(send, 102, host, "en")
    check("force_end จบเกมที่ค้าง", await hm.force_end(102, "แอดมิน") and hm.get_active(102) is None)
    check("force_end ช่องที่ไม่มีเกม -> False", not await hm.force_end(102))
    v4 = await hm.start_hangman(send, 103, host, "en")
    await v4.on_timeout()
    check("หมดเวลา: ปลดห้อง + เฉลยคำในข้อความ", hm.get_active(103) is None and "หมดเวลา" in v4.message.kw.get("content", ""))


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
