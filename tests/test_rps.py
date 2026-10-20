"""ทดสอบเป่ายิ้งฉุบ: ตัดสินผล + สมองแบ็คลี่ (ไม่โกง) + ปุ่ม (ของปลอม)   รัน: PYTHONPATH=. python3 tests/test_rps.py"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _fakes import I, Msg, U  # noqa: E402
from bagley.features.games import rps  # noqa: E402

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


R, P, S = "rock", "paper", "scissors"
check("ค้อนชนะกรรไกร", rps.rps_result(R, S) == "win" and rps.rps_result(S, R) == "lose")
check("กระดาษชนะค้อน", rps.rps_result(P, R) == "win" and rps.rps_result(R, P) == "lose")
check("กรรไกรชนะกระดาษ", rps.rps_result(S, P) == "win" and rps.rps_result(P, S) == "lose")
check("ท่าเดียวกัน = เสมอ", all(rps.rps_result(m, m) == "draw" for m in rps.MOVES))
check("ชนะก่อนกี่ตา", [rps.wins_needed(n) for n in (1, 3, 5, 7)] == [1, 2, 3, 4])

rng = random.Random(1)
check("ระดับง่ายสุ่มกระจายทุกท่า", len({rps.bot_pick([R] * 10, "ง่าย", rng) for _ in range(60)}) == 3)
check("ยังไม่มีประวัติ -> สุ่ม", len({rps.bot_pick([], "ยาก", rng) for _ in range(60)}) == 3)
res = [rps.rps_result(R, rps.bot_pick([R] * 10, "ยาก", rng)) for _ in range(600)]
check("ระดับยากจับทางคนออกค้อนซ้ำได้ (แพ้ผู้เล่นน้อยกว่าสุ่ม)", res.count("lose") > res.count("win") * 1.5, f"win {res.count('win')} lose {res.count('lose')}")
res = [rps.rps_result(m, rps.bot_pick([], "ยาก", rng)) for m in rps.MOVES for _ in range(300)]
check("ผู้เล่นออกสุ่มล้วน สูสีกับแบ็คลี่ (ไม่โกงไปข้างเดียว)", abs(res.count("win") - res.count("lose")) < 120, f"{res.count('win')}/{res.count('lose')}")

# บอทเลือกก่อนรู้ท่าตานี้: bot_pick ไม่รับท่าปัจจุบันเป็นพารามิเตอร์ และ history ไม่รวมตานี้
g = rps.RPSGame(3, "ยาก", random.Random(3))
g.play(R)
check("ประวัติที่บอทใช้ตัดสินใจ = เฉพาะตาก่อนหน้า", g.player_moves == [R] and len(g.rounds) == 1)
g = rps.RPSGame(3, "ง่าย", random.Random(4))
while g.status == "playing":
    g.play(random.choice(rps.MOVES))
check("เกมจบเมื่อฝั่งใดฝั่งหนึ่งถึง 2 แต้ม", max(g.score.values()) == 2 and g.status in ("won", "lost"))
try:
    g.play(R)
    check("เกมจบแล้วเล่นต่อไม่ได้", False)
except ValueError:
    check("เกมจบแล้วเล่นต่อไม่ได้", True)
check("best_of ที่ไม่รองรับ -> 3", rps.RPSGame(4).best_of == 3 and rps.RPSGame(5).best_of == 5)


async def main():
    me, other = U(1, "ชะอม"), U(2, "เพื่อน")
    sent = {}

    async def send(**kw):
        sent.update(kw)
        return Msg()

    v = await rps.start_rps(send, me, 3, "ยาก")
    check("เปิดเกม: มี 3 ปุ่ม + หัวข้อ", len(v.buttons) == 3 and "เป่ายิ้งฉุบ" in sent["content"])
    i = I(other)
    await v.buttons[0].callback(i)
    check("คนอื่นกดไม่ได้ (เฉพาะเจ้าของเกม)", i.response.sent and not v.game.rounds)
    guard = 0
    while v.game.status == "playing" and guard < 30:
        guard += 1
        i = I(me)
        await v.buttons[guard % 3].callback(i)
        if guard == 1:
            check("กดแล้วแก้ข้อความ แสดงท่าทั้งสองฝั่ง", i.response.edited and "ผมออก" in i.response.edited[0]["content"])
    check("จบเกม: ปุ่มถูกปิดหมด + ประกาศผล", v.game.status != "playing" and all(b.disabled for b in v.buttons)
          and ("ชนะเกมนี้" in v.header()))
    i = I(me)
    await v.buttons[0].callback(i)
    check("จบแล้วกดต่อไม่ได้", i.response.sent and "จบแล้ว" in i.response.sent[0])
    v2 = await rps.start_rps(send, me, 5, "ง่าย")
    await v2.on_timeout()
    check("หมดเวลา: ปิดปุ่ม", all(b.disabled for b in v2.buttons) and "หมดเวลา" in v2.message.kw.get("content", ""))


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
