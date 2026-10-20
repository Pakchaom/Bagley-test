"""ทดสอบคำพูดตอบโต้ของแบ็คลี่ในทุกเกม (ระบบกลาง + จุดที่เกมเรียกใช้)   รัน: PYTHONPATH=. python3 tests/test_banter.py"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
import discord  # noqa: E402
from _fakes import I, Msg, U  # noqa: E402
from bagley.features.games import banter, hangman as hm, rps, wordle as wd, xo  # noqa: E402
from bagley.features.games.uno import UnoSession  # noqa: E402
from bagley.features.games.uno_engine import UnoGame  # noqa: E402

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


def forms(game, event, **kw):
    """ประโยคที่เป็นไปได้ทั้งหมดของเหตุการณ์นี้ (หลังแทนค่า)"""
    return {t.format_map(banter._Safe(kw)).strip() for t in banter.POOLS[game][event]}


def has_line(text, game, event, **kw):
    return any(f in text for f in forms(game, event, **kw))


FORCE = 1000.0
# ---------------------------------------------------------------- ระบบกลาง
check("ครบทั้ง 5 เกม", set(banter.POOLS) == {"xo", "hangman", "wordle", "rps", "uno"})
check("ทุกเหตุการณ์มีอย่างน้อย 2 ประโยค (ไม่พูดซ้ำเดิมตลอด)", all(len(v) >= 2 for g in banter.POOLS.values() for v in g.values()))
check("ประโยคทุกอันแทนค่าได้ ไม่เหลือวงเล็บปีกกา", all("{" not in f and "}" not in f for g, evs in banter.POOLS.items() for e in evs
                                                     for f in forms(g, e, name="ชะอม", category="สัตว์", move="✊")))
banter.CHANCE_SCALE = FORCE
check("ไม่ส่งค่าที่ต้องแทน (name) ก็ไม่พัง", banter.say("hangman", "hit") is not None)
check("เหตุการณ์ที่ไม่มี -> None", banter.say("xo", "nope") is None and banter.say("nogame", "x") is None)
seq = [banter.say("rps", "draw") for _ in range(40)]
check("ไม่พูดประโยคเดิมติดกัน", all(a != b for a, b in zip(seq, seq[1:])))
banter.CHANCE_SCALE = 0
check("CHANCE_SCALE=0 -> เงียบ", all(banter.say("xo", "block") is None for _ in range(20)))
banter.CHANCE_SCALE = 1.0
check("chance=0.3 พูดบ้างไม่พูดบ้าง", 0 < sum(banter.say("xo", "mid", chance=0.3, rng=random.Random(i)) is not None for i in range(200)) < 200)
banter.CHANCE_SCALE = FORCE
banter.ENABLED = False
check("ENABLED=False -> เงียบหมด", banter.say("xo", "block") is None and banter.tag(None) == "")
banter.ENABLED = True
check("tag มีชื่อแบ็คลี่ + ขึ้นบรรทัดใหม่", banter.tag("สวัสดี") == "\n💬 **แบ็คลี่:** สวัสดี")

# ---------------------------------------------------------------- XO
me, friend = U(1, "ชะอม"), U(2, "เพื่อน")
v = xo.XOView(me, None, "ยาก")                           # ผู้เล่น = X, แบ็คลี่ = O
v.board, v.turn = list("XX  O    "), "O"
v.bot_turn_if_needed()
check("XO: แบ็คลี่ล็อกให้ + จำได้ว่าเป็นการบล็อก", v.board[2] == "O" and v._ctx == "block")
v.quip = v.choose_quip()
check("XO: บล็อกแล้วพูดตอบ และขึ้นในหัวข้อ", has_line(v.quip, "xo", "block") and "💬" in v.header())
v2 = xo.XOView(me, None, "ยาก")
v2.result = "O"
check("XO: แบ็คลี่ชนะ -> พูดปิดเกม", has_line(v2.choose_quip(), "xo", "end_bot_win", name="ชะอม"))
v2.result = "X"
check("XO: ผู้เล่นชนะ -> ชมผู้เล่นตามชื่อ", has_line(v2.choose_quip(), "xo", "end_player_win", name="ชะอม"))
v2.result = "draw"
check("XO: เสมอ -> พูดเสมอ", has_line(v2.choose_quip(), "xo", "end_draw"))
v3 = xo.XOView(me, friend, "ยาก")
check("XO: คนเล่นกับคน แบ็คลี่ไม่พูดแทรก", v3.choose_quip() == "" and "💬" not in v3.header())


async def main():
    sent = {}

    async def send(*a, **kw):
        sent.update(kw)
        return Msg()

    # XO เปิดเกม
    for _ in range(12):
        vv = await xo.start_xo(send, me, None, "ยาก")
        if vv.players["X"] is None:
            check("XO: เปิดเกมโดยแบ็คลี่เดินก่อน -> ทักทาย", has_line(sent["content"], "xo", "start_bot_first", name="ชะอม"))
            break
    else:
        check("XO: สุ่มได้แบ็คลี่เดินก่อน", False)
    for _ in range(12):
        vv = await xo.start_xo(send, me, None, "ยาก")
        if vv.players["X"] is me:
            check("XO: ผู้เล่นเดินก่อน -> เชิญเดิน", has_line(sent["content"], "xo", "start_player_first", name="ชะอม"))
            break

    # Hangman
    hm._active.clear()
    hv = await hm.start_hangman(send, 1, me, "en", "สัตว์")
    check("Hangman: เปิดเกมมีคำทัก + บอกหมวด", has_line(sent["content"], "hangman", "start", category=hv.game.category))
    hv.game = hm.HangmanGame("tiger", "en", "สัตว์")
    i = I(friend)
    await hv.do_letter(i, "t")
    check("Hangman: ทายถูก -> ชมตามชื่อ", has_line(i.response.edited[0]["content"], "hangman", "hit", name="เพื่อน"))
    i = I(friend)
    await hv.do_letter(i, "z")
    check("Hangman: ทายผิด -> พูดแซว", has_line(i.response.edited[0]["content"], "hangman", "miss", name="เพื่อน"))
    hv.game.wrong_letters = list("abcd")                 # เหลือ 2 ดวง -> ผิดอีกเหลือ 1
    hv.game.guessed |= set("abcd")
    i = I(friend)
    await hv.do_letter(i, "m")
    check("Hangman: เหลือหัวใจดวงสุดท้าย -> เตือน", hv.game.lives_left == 1 and has_line(i.response.edited[0]["content"], "hangman", "low"))
    hv.game = hm.HangmanGame("elephant", "en")
    i = I(me)
    await hv._hint_btn(i)
    check("Hangman: ขอใบ้ -> พูด", has_line(i.response.edited[0]["content"], "hangman", "hint"))
    banter.ENABLED = False
    i = I(friend)
    await hv.do_letter(i, "q")
    check("Hangman: ปิดระบบพูดแล้วเงียบ", "💬" not in i.response.edited[0]["content"])
    banter.ENABLED = True
    hm._active.clear()

    # Wordle
    wd._active.clear()
    wv = await wd.start_wordle(send, 2, me)
    check("Wordle: เปิดเกมมีคำทัก", has_line(sent["content"], "wordle", "start"))
    wv.game = wd.WordleGame("crane")
    i = I(me)
    await wv.do_guess(i, "tuxis")
    check("Wordle: ไม่ตรงเลย -> แซว", has_line(i.response.edited[0]["content"], "wordle", "all_gray"))
    i = I(me)
    await wv.do_guess(i, "crate")
    check("Wordle: ถูกที่ 4 ตัว -> บอกว่าใกล้แล้ว", has_line(i.response.edited[0]["content"], "wordle", "close"))
    for w in ("blimp", "dough"):
        await wv.do_guess(I(me), w)
    i = I(me)
    await wv.do_guess(i, "fjord")                         # ครั้งที่ 5
    check("Wordle: เหลือครั้งสุดท้าย -> ลุ้น", has_line(i.response.edited[0]["content"], "wordle", "last_try"))
    wv2 = await wd.start_wordle(send, 3, me)
    wv2.game = wd.WordleGame("crane")
    i = I(me)
    await wv2.do_guess(i, "crane")
    check("Wordle: ทายถูกในครั้งเดียว -> ทึ่ง", has_line(i.response.edited[0]["content"], "wordle", "win_fast"))
    wd._active.clear()

    # RPS
    rv = await rps.start_rps(send, me, 7, "ยาก")
    last = None
    for _ in range(3):
        i = I(me)
        await rv.buttons[0].callback(i)
        last = i.response.edited[0]["content"]
    check("RPS: ออกท่าเดิม 3 ตาติด -> แบ็คลี่สังเกตเห็น", has_line(last, "rps", "streak", move="✊ ค้อน"))
    g = rps.RPSGame(3)
    g.score = {"player": 1, "bot": 0}
    rv2 = rps.RPSView(me, g)
    check("RPS: ผู้เล่นอีกแต้มเดียวชนะ -> พูดลุ้น", has_line(rv2._banter("rock", "draw"), "rps", "match_point_player"))
    g.score = {"player": 0, "bot": 1}
    check("RPS: แบ็คลี่อีกแต้มเดียว -> พูดข่ม", has_line(rv2._banter("rock", "draw"), "rps", "match_point_bot"))
    g.score = {"player": 0, "bot": 0}
    check("RPS: ตานิ่งๆ พูดถึงผลของตา", has_line(rv2._banter("rock", "lose"), "rps", "lose"))
    g.score = {"player": 2, "bot": 0}
    check("RPS: เกมจบแล้วไม่พูดซ้ำกับบรรทัดสรุป", rv2._banter("rock", "win") == "")

    # UNO: ทดสอบการเลือกประโยคจากเหตุการณ์ในเกม
    class Chan:
        id = 9

    sess = UnoSession(Chan(), me, 999)
    sess.game = UnoGame([1, 999], {1: "ชะอม", 999: "แบ็คลี่"})
    e_attack = ["แบ็คลี่ ลง +2", "💥 ชะอม จั่ว 2 ใบและโดนข้ามตา"]
    check("UNO: แบ็คลี่โจมตีผู้เล่น -> พูดพร้อมเรียกชื่อ", has_line(sess._bot_banter(e_attack) or "", "uno", "bot_attack", name="ชะอม"))
    check("UNO: แบ็คลี่เหลือใบเดียว -> ประกาศ", has_line(sess._bot_banter(["แบ็คลี่ ลง 5", "🔔 แบ็คลี่: UNO! เหลือไพ่ใบสุดท้าย"]) or "", "uno", "bot_uno"))
    check("UNO: แบ็คลี่ข้ามตา/จั่ว มีพูดตามเหตุการณ์",
          has_line(sess._bot_banter(["แบ็คลี่ ลง 🚫", "🚫 ชะอม โดนข้ามตา"]) or "", "uno", "bot_skip")
          and has_line(sess._bot_banter(["แบ็คลี่ จั่วไพ่ 1 ใบ (ลงไม่ได้ ข้ามตา)"]) or "", "uno", "bot_draw"))
    check("UNO: ตาธรรมดาไม่มีเหตุการณ์ -> เงียบ (ปล่อยให้คำพูดสุ่มเดิมทำงาน)", sess._bot_banter(["แบ็คลี่ ลง เขียว 5"]) is None)
    check("UNO: ผู้เล่นโจมตีแบ็คลี่ -> แบ็คลี่โอดครวญ", has_line(sess._human_banter(["ชะอม ลง +4", "💥 แบ็คลี่ จั่ว 4 ใบและโดนข้ามตา"], 1) or "", "uno", "human_hit_bot", name="ชะอม"))
    check("UNO: ผู้เล่นเหลือใบเดียว -> แบ็คลี่ตื่นเต้น", has_line(sess._human_banter(["ชะอม ลง 7", "🔔 ชะอม: UNO! เหลือไพ่ใบสุดท้าย"], 1) or "", "uno", "human_uno", name="ชะอม"))
    check("UNO: ผู้เล่นเดินธรรมดา -> เงียบ", sess._human_banter(["ชะอม ลง เขียว 7"], 1) is None)


asyncio.run(main())
banter.CHANCE_SCALE = 1.0
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
