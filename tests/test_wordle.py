"""ทดสอบเกมทายคำ (Wordle): ให้สี/ตัวซ้ำ + สมองแบ็คลี่ + ปุ่ม/ช่องกรอก (ของปลอม)   รัน: PYTHONPATH=. python3 tests/test_wordle.py"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
import discord  # noqa: E402
from _fakes import I, Msg, U  # noqa: E402
from bagley.features.games import wordle as wd  # noqa: E402

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


check("คลังคำ 5 ตัว a–z ไม่ซ้ำ", len(wd.ANSWERS) > 300 and all(len(w) == 5 and w.isalpha() and w.islower() for w in wd.ANSWERS)
      and len(set(wd.ANSWERS)) == len(wd.ANSWERS), str(len(wd.ANSWERS)))
check("คำเปิดของแบ็คลี่อยู่ในคลัง", wd.OPENER in wd.ANSWERS)

# ---- ให้สี (รวมกรณีตัวอักษรซ้ำ)
check("ถูกหมด", wd.score_guess("crane", "crane") == list("ggggg"))
check("ไม่มีตัวไหนตรงเลย", wd.score_guess("crane", "tuxis") == list("bbbbb"))
check("ผิดที่ = เหลือง (nacre: สี่ตัวผิดที่ e ถูกที่)", wd.score_guess("crane", "nacre") == list("yyyyg"))
check("ซ้ำ: คำลับมี e ตัวเดียว ทาย eerie ได้ e ตัวเดียว", wd.score_guess("crane", "eerie") == list("bbybg"))
check("ซ้ำ: เขียวมาก่อนเหลือง (apple/paper)", wd.score_guess("apple", "paper") == list("yygyb"))
check("ซ้ำ: ทาย speed ใส่คำลับ abide มี e ตัวเดียว -> e ตัวหลังต้องดำ", wd.score_guess("abide", "speed") == list("bbyby"))
check("ซ้ำ: speed/abide", wd.score_guess("speed", "abide") == list("bbbyy"))
check("ซ้ำ: hello/lolly เขียวสองตัวก่อน แล้ว o เหลือง l ตัวแรกดำ", wd.score_guess("hello", "lolly") == list("byggb"))
check("ซ้ำ: ทาย lll.. ได้ตามจำนวนที่มีจริง", wd.score_guess("hello", "llama").count("g") + wd.score_guess("hello", "llama").count("y") == 2)

# ---- ตรรกะเกม
g = wd.WordleGame("crane")
check("ทายไม่ครบ 5 ตัว/ไม่ใช่ a–z = invalid", all(g.guess(x) == "invalid" for x in ("cran", "cranes", "cr4ne", "ครบห้า", "")))
check("ทายแล้วบันทึก", g.guess("SLATE") == "ok" and g.history[0][0] == "slate")
check("ทายซ้ำ = dup", g.guess("slate") == "dup" and len(g.history) == 1)
check("ทายถูก = ชนะ", g.guess("crane") == "ok" and g.status == "won")
g = wd.WordleGame("crane")
for w in ("slate", "pious", "dumpy", "forth", "light", "magic"):
    g.guess(w)
check("ทายครบ 6 ครั้งไม่ถูก = แพ้", g.status == "lost")
g = wd.WordleGame("crane")
g.guess("slate")
kb = g.keyboard()
check("คีย์บอร์ด: a,e = เขียว, s,l,t = ดำ", kb["a"] == "g" and kb["e"] == "g" and kb["s"] == "b" and kb["l"] == "b")
check("กระดานมี 6 แถว", len(g.board().split("\n")) == 6 and "SLATE" in g.board())

# ---- สมองแบ็คลี่: แก้ได้ทุกคำในคลัง ไม่เกิน 6 ครั้ง
rng = random.Random(5)
fails, repeats, steps = 0, 0, []
for a in wd.ANSWERS:
    gg = wd.WordleGame(a)
    while gg.status == "playing":
        w = gg.bot_guess(rng=rng)
        if w is None or gg.guess(w) != "ok":
            repeats += 1
            break
    if gg.status == "won":
        steps.append(len(gg.history))
    else:
        fails += 1
check("แบ็คลี่ไม่ทายซ้ำ/ไม่ติด", repeats == 0)
check("แบ็คลี่แก้ได้เกือบทุกคำใน 6 ครั้ง (>97%)", fails < 0.03 * len(wd.ANSWERS), f"แพ้ {fails}/{len(wd.ANSWERS)} เฉลี่ย {sum(steps)/len(steps):.2f} ครั้ง")
gg = wd.WordleGame("crane")
gg.history.append(("zzzzz", wd.score_guess("crane", "zzzzz")))
check("candidates ตัดคำที่ขัดกับใบ้ออก", "crane" in gg.candidates() and all(not set(c) & {"z"} for c in gg.candidates()))


# ---- Discord (ของปลอม)
async def main():
    host, a, admin = U(1, "ชะอม"), U(2, "เพื่อน"), U(4, "แอดมิน", manage=True)
    sent = []

    async def send(*args, **kw):
        sent.append((args, kw))
        return Msg()

    wd._active.clear()
    v = await wd.start_wordle(send, 200, host)
    check("เปิดเกม: มีปุ่ม 3 ปุ่ม", v is not None and len([c for c in v.children if isinstance(c, discord.ui.Button)]) == 3
          and "Wordle" in sent[0][1]["content"])
    check("ช่องเดียวกันเปิดซ้อนไม่ได้", await wd.start_wordle(send, 200, a) is None)
    v.game = wd.WordleGame("crane")
    btns = {c.label: c for c in v.children if isinstance(c, discord.ui.Button)}
    i = I(a)
    await btns["ทายคำ"].callback(i)
    check("ปุ่มทายคำเปิดช่องกรอก", i.response.modals)
    modal = i.response.modals[0]
    modal.box.value = "ab1de"
    i = I(a)
    await modal.on_submit(i)
    check("คำไม่ถูกรูปแบบ -> ปฏิเสธ ไม่นับครั้ง", i.response.sent and not v.game.history)
    modal.box.value = "slate"
    i = I(a)
    await modal.on_submit(i)
    check("ทายแล้วแสดงสี + นับครั้ง", len(v.game.history) == 1 and "SLATE" in i.response.edited[0]["content"])
    i = I(host)
    await modal.on_submit(i)
    check("ทายคำซ้ำ -> ปฏิเสธ", i.response.sent and "ไปแล้ว" in i.response.sent[0] and len(v.game.history) == 1)
    btns = {c.label: c for c in v.children if isinstance(c, discord.ui.Button)}
    v.game.bot_guess = lambda pool=None, rng=None: "crate"        # ล็อกคำที่แบ็คลี่เดา ไม่ให้บังเอิญชนะเอง
    i = I(host)
    await btns["ให้แบ็คลี่ช่วยเดา"].callback(i)
    check("แบ็คลี่ช่วยเดา 1 ครั้ง", len(v.game.history) == 2 and "แบ็คลี่" in i.response.edited[0]["content"])
    i = I(a)
    await btns["จบเกม"].callback(i)
    check("คนทั่วไปจบเกมไม่ได้", i.response.sent and wd.get_active(200) is v)
    modal.box.value = "crane"
    i = I(a)
    await modal.on_submit(i)
    out = i.response.edited[0]["content"]
    check("ทายถูก: ชนะ + เฉลย + เครดิต + ปลดห้อง", "ถูกต้อง" in out and "CRANE" in out and "เพื่อน" in out
          and wd.get_active(200) is None and not v.children)

    v2 = await wd.start_wordle(send, 201, host)
    btns = {c.label: c for c in v2.children if isinstance(c, discord.ui.Button)}
    i = I(admin)
    await btns["จบเกม"].callback(i)
    check("แอดมินจบเกมได้ + เฉลยคำ", wd.get_active(201) is None and v2.game.answer.upper() in i.response.edited[0]["content"])

    v3 = await wd.start_wordle(send, 202, host)
    v3.game = wd.WordleGame("crane")                                  # ล็อกคำลับ ให้ทายผิดครบ 6 ครั้งได้แน่
    for w in ("slate", "pious", "dumpy", "forth", "light", "magic"):
        if v3.game.status == "playing" and v3.game.answer != w:
            i = I(a)
            await v3.do_guess(i, w)
    check("ครบ 6 ครั้งไม่ถูก = แพ้ ปลดห้อง", v3.game.status == "lost" and wd.get_active(202) is None, v3.game.answer)

    v4 = await wd.start_wordle(send, 203, host)
    await v4.on_timeout()
    check("หมดเวลา: ปลดห้อง + เฉลยคำ", wd.get_active(203) is None and "หมดเวลา" in v4.message.kw.get("content", ""))
    v5 = await wd.start_wordle(send, 204, host)
    check("force_end จบเกมที่ค้าง", await wd.force_end(204, "แอดมิน") and wd.get_active(204) is None and not await wd.force_end(204))


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
