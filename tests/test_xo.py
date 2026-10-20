"""ทดสอบเกม XO: ตรรกะบอท + การทำงานของปุ่ม (ของปลอม ไม่ต้องต่อ Discord)   รัน: PYTHONPATH=. python3 tests/test_xo.py"""
import asyncio
import random
import sys

from bagley.features.games import xo

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


def play_out(bot_mark, level, rng):
    """บอท (ระดับที่กำหนด) vs ผู้เล่นสุ่ม -> คืนผู้ชนะ X/O/None"""
    board, turn = [" "] * 9, "X"
    while True:
        i = xo.bot_choose(board, turn, level, rng) if turn == bot_mark else rng.choice([k for k, v in enumerate(board) if v == " "])
        board[i] = turn
        w, _ = xo.check_winner(board)
        if w:
            return w
        if " " not in board:
            return None
        turn = "O" if turn == "X" else "X"


check("ชนะแนวนอน", xo.check_winner(list("XXX OO   "))[0] == "X")
check("แนวทแยงถูกต้อง", xo.check_winner(list("XO  X  OX"))[0] == "X")
check("เสมอ = ไม่มีผู้ชนะ", xo.check_winner(list("XOXXOOOXX"))[0] is None)

rng = random.Random(3)
losses = sum(play_out(m, "ยาก", rng) == ("O" if m == "X" else "X") for m in ("X", "O") for _ in range(300))
check("ระดับยาก ไม่เคยแพ้ผู้เล่นสุ่มเลย 600 เกม", losses == 0, f"แพ้ {losses}")
wins = sum(play_out("X", "ยาก", rng) == "X" for _ in range(300))
check("ระดับยากชนะผู้เล่นสุ่มส่วนใหญ่ (>85%)", wins > 255, f"{wins}/300")
easy_loss = sum(play_out("X", "ง่าย", rng) == "O" for _ in range(300))
check("ระดับง่ายพลาดแพ้ได้บ้าง (เล่นสุ่ม)", easy_loss > 20, f"แพ้ {easy_loss}/300")
mid = [play_out("X", "กลาง", rng) for _ in range(300)]
check("ระดับกลางเก่งกว่าระดับง่าย", sum(w == "O" for w in mid) < easy_loss, f"แพ้ {sum(w == 'O' for w in mid)}")

b = list("XX OO    ")
check("ระดับกลาง/ยาก ชนะทันทีถ้าชนะได้", xo.bot_choose(b, "X", "กลาง") == 2 and xo.bot_choose(b, "X", "ยาก") == 2)
b = list("XX  O  O ")
check("ระดับกลาง/ยาก บล็อกเมื่อจะแพ้", xo.bot_choose(list("OO  X    "), "X", "กลาง") == 2 and xo.bot_choose(list("OO  X    "), "X", "ยาก") == 2)

# ---- ปุ่ม ----


class U:
    def __init__(self, uid, name):
        self.id, self.display_name, self.bot = uid, name, False


class Resp:
    def __init__(self):
        self.sent, self.edited = [], []

    async def send_message(self, c=None, **kw):
        self.sent.append(c)

    async def edit_message(self, **kw):
        self.edited.append(kw)


class I:
    def __init__(self, u):
        self.user, self.response = u, Resp()


class Msg:
    async def edit(self, **kw):
        self.kw = kw


async def main():
    me, friend = U(1, "ชะอม"), U(2, "เพื่อน")
    # เล่นกับแบ็คลี่
    sent = {}

    async def send(**kw):
        sent.update(kw)
        return Msg()
    v = await xo.start_xo(send, me, None, "ยาก")
    check("เปิดเกมกับแบ็คลี่ มีปุ่ม 9 ช่อง", len(v.buttons) == 9 and "vs" in sent["content"])
    guard = 0
    while v.result is None and guard < 20:
        guard += 1
        cur = v.players[v.turn]
        if cur is None:
            break
        free = next(i for i, x in enumerate(v.board) if x == " ")
        i = I(me)
        await v.buttons[free].callback(i)
        check("ลงหมากแล้วแก้ข้อความ", i.response.edited) if guard == 1 else None
    check("เล่นจบ (ชนะหรือเสมอ) ปุ่มถูกปิดหมด", v.result is not None and all(b.disabled for b in v.buttons), str(v.result))
    i = I(me)
    await v.buttons[0].callback(i)
    check("เกมจบแล้วกดต่อไม่ได้", i.response.sent and "จบแล้ว" in i.response.sent[0])

    # ท้าเพื่อน: คนผิดตาต้องกดไม่ได้
    async def send2(**kw):
        return Msg()
    v2 = await xo.start_xo(send2, me, friend, "ยาก")
    cur = v2.players[v2.turn]
    other = friend if cur is me else me
    i = I(other)
    await v2.buttons[4].callback(i)
    check("ไม่ใช่ตาแล้วกด -> ถูกปฏิเสธ ช่องยังว่าง", i.response.sent and v2.board[4] == " ")
    i = I(cur)
    await v2.buttons[4].callback(i)
    check("ถึงตาแล้วลงได้", v2.board[4] != " " and v2.turn != v2.board[4])
    i = I(other)
    await v2.buttons[4].callback(i)
    check("กดช่องที่มีคนลงแล้ว -> ถูกปฏิเสธ", i.response.sent and "ลงแล้ว" in i.response.sent[0])
    v3 = await xo.start_xo(send2, me, me, "ยาก")
    check("ท้าตัวเอง -> กลายเป็นเล่นกับแบ็คลี่", None in v3.players.values())

    # แบ็คลี่ได้เดินก่อนต้องลงหมากแรกให้แล้ว
    firsts = 0
    for _ in range(30):
        vv = await xo.start_xo(send2, me, None, "ยาก")
        if vv.players["X"] is None:
            firsts += 1
            check("แบ็คลี่เป็น X -> ลงหมากแรกให้แล้ว", sum(c != " " for c in vv.board) == 1) if firsts == 1 else None
    check("สุ่มให้แบ็คลี่ได้เดินก่อนบ้าง", 0 < firsts < 30, f"{firsts}/30")


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
