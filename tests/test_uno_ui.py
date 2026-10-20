"""ทดสอบชั้น Discord ของ UNO ด้วยของปลอม (ไม่ต้องต่อเน็ต/ไม่ต้องใช้โทเคน): ห้องรอ -> เริ่มเกม -> เมนูเลือกไพ่ -> แบ็คลี่เดินเอง -> จบเกม
รัน: PYTHONPATH=. python3 tests/test_uno_ui.py   (ต้องมี discord.py)"""
import asyncio
import random
import sys

import discord

from bagley.features.games import uno
from bagley.features.games.uno_engine import UnoError

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


class FakeMessage:
    def __init__(self, **kw):
        self.kw, self.edits = kw, []

    async def edit(self, **kw):
        self.edits.append(kw)
        self.kw.update(kw)


class FakeChannel:
    def __init__(self, cid=100):
        self.id, self.sent = cid, []

    async def send(self, *a, **kw):
        m = FakeMessage(**kw)
        if a:
            m.kw["content"] = a[0]
        self.sent.append(m)
        return m


class FakeUser:
    def __init__(self, uid, name):
        self.id, self.display_name = uid, name


class FakeResponse:
    def __init__(self):
        self.sent, self.edited = [], []

    async def send_message(self, content=None, **kw):
        self.sent.append((content, kw))

    async def edit_message(self, **kw):
        self.edited.append(kw)


class FakeInteraction:
    def __init__(self, user):
        self.user, self.response = user, FakeResponse()


BOT_ID = 999


async def pump(session, until, timeout=5.0):
    t = 0.0
    while not until() and t < timeout:
        await asyncio.sleep(0.02)
        t += 0.02
    return until()


async def main():
    uno.BOT_DELAY = (0.0, 0.0)
    host, friend = FakeUser(1, "ชะอม"), FakeUser(2, "เพื่อน")
    ch = FakeChannel()

    async def send(*a, **kw):
        return await ch.send(*a, **kw)

    # ---- ห้องรอ ----
    s = await uno.open_uno_lobby(ch, host, BOT_ID, send=send)
    check("เปิดห้องรอได้", s is not None and uno.get_session(ch.id) is s)
    dup = await uno.open_uno_lobby(ch, friend, BOT_ID, send=send)
    check("เปิดห้องซ้ำในช่องเดียวกันไม่ได้", dup is None and "เปิดอยู่" in ch.sent[-1].kw["content"])

    lv = uno.LobbyView(s)
    i = FakeInteraction(friend)
    await lv.join.callback(i)
    check("เพื่อนกดเข้าร่วมได้", 2 in s.humans and i.response.edited)
    i = FakeInteraction(friend)
    await lv.join.callback(i)
    check("กดเข้าร่วมซ้ำถูกปฏิเสธ", i.response.sent and "อยู่ในห้องแล้ว" in i.response.sent[0][0])
    i = FakeInteraction(friend)
    await lv.start.callback(i)
    check("คนที่ไม่ใช่เจ้าของกดเริ่มไม่ได้", s.phase == "lobby" and i.response.sent)
    i = FakeInteraction(host)
    await lv.toggle_bot.callback(i)
    check("เจ้าของห้องปิดแบ็คลี่ได้", s.with_bot is False)
    await lv.toggle_bot.callback(FakeInteraction(host))
    check("เปิดแบ็คลี่กลับได้", s.with_bot is True)

    # ---- เริ่มเกม (2 คน + แบ็คลี่) ----
    await lv.start.callback(FakeInteraction(host))
    check("เริ่มเกมแล้วเฟสเป็น playing", s.phase == "playing" and s.game is not None)
    check("ผู้เล่น 3 คน (คน 2 + แบ็คลี่)", sorted(s.game.players) == sorted([1, 2, BOT_ID]))
    check("ส่งกระดานกลางพร้อมปุ่ม", s.table_message is not None and s.table_message.kw.get("view") is not None)
    emb = s.table_embed()
    check("กระดานโชว์ไพ่บนสุดและจำนวนไพ่", "ไพ่บนสุด" in emb.description and any("7 ใบ" in f.value for f in emb.fields))

    # ---- ปุ่ม "ไพ่ของฉัน" ----
    tv = s.table_view
    outsider = FakeInteraction(FakeUser(77, "คนนอก"))
    await tv.my_hand.callback(outsider)
    check("คนนอกเกมกดดูไพ่ไม่ได้", outsider.response.sent and "ไม่ได้อยู่ในเกม" in outsider.response.sent[0][0])
    me = FakeInteraction(friend)
    await tv.my_hand.callback(me)
    content, kw = me.response.sent[0]
    check("ผู้เล่นเห็นไพ่ของตัวเองแบบส่วนตัว", kw.get("ephemeral") is True and "ไพ่ในมือ (7 ใบ)" in content)

    # ---- วนเล่นจนจบ: มนุษย์ใช้ HandView จริง (เมนู/ปุ่มจั่ว/ปุ่มผ่าน/เลือกสี) แบ็คลี่เดินเอง ----
    g = s.game
    rng = random.Random(7)
    used = {"select": 0, "color": 0, "draw": 0, "pass": 0, "refuse": 0}
    steps = 0
    while g.winner is None and steps < 800:
        steps += 1
        if g.current == BOT_ID:
            await pump(s, lambda: g.current != BOT_ID or g.winner is not None)
            continue
        uid = g.current
        user = host if uid == 1 else friend
        hv = uno.HandView(s, uid)
        sel = next((c for c in hv.children if isinstance(c, uno.CardSelect)), None)
        if sel is not None and rng.random() < 0.9:
            idx = int(sel.options[0].value)
            sel._values = [str(idx)]
            it = FakeInteraction(user)
            await sel.callback(it)
            used["select"] += 1
            if g.hands[uid][idx:idx + 1] and g.current == uid and it.response.edited and isinstance(it.response.edited[-1].get("view"), uno.ColorView):
                cv = it.response.edited[-1]["view"]
                it2 = FakeInteraction(user)
                await cv.children[rng.randrange(4)].callback(it2)
                used["color"] += 1
        else:
            buttons = [c for c in hv.children if isinstance(c, discord.ui.Button)]
            act = next((b for b in buttons if "จั่ว" in (b.label or "") or "ผ่าน" in (b.label or "")), None)
            if act is None:
                await asyncio.sleep(0.01)
                continue
            used["draw" if "จั่ว" in act.label else "pass"] += 1
            await act.callback(FakeInteraction(user))
        await asyncio.sleep(0)
        await pump(s, lambda: g.current != BOT_ID or g.winner is not None, 2.0)
    check("เล่นจนมีผู้ชนะ", g.winner is not None, f"steps={steps} {used}")
    check("เมนูเลือกไพ่/ปุ่มจั่วถูกใช้งานจริง", used["select"] > 0 and used["draw"] > 0, str(used))
    await pump(s, lambda: s.phase == "closed", 3.0)
    check("จบเกมแล้วปิดห้องและเคลียร์ session", s.phase == "closed" and uno.get_session(ch.id) is None)
    check("ประกาศผู้ชนะในช่อง", any("ชนะเกม UNO" in str(m.kw.get("content", "")) for m in ch.sent))
    final = s.table_message.kw.get("embed")
    check("กระดานสุดท้ายโชว์ผู้ชนะและเอาปุ่มออก", final is not None and "ชนะ" in final.title and s.table_message.kw.get("view") is None)

    # ---- ไม่ใช่ตา/ลงผิดต้องไม่พัง ----
    ch2 = FakeChannel(200)

    async def send2(*a, **kw):
        return await ch2.send(*a, **kw)
    s2 = await uno.open_uno_lobby(ch2, host, BOT_ID, send=send2)
    s2.with_bot = False
    s2.humans[2] = friend
    await uno.LobbyView(s2).start.callback(FakeInteraction(host))
    g2 = s2.game
    other = next(p for p in g2.players if p != g2.current)
    ok, msg = await s2.act(other, "draw")
    check("ไม่ใช่ตาแล้วกดจั่ว -> ถูกปฏิเสธพร้อมข้อความ", not ok and "ยังไม่ถึงตา" in msg, msg)
    ok, msg = await s2.act(g2.current, "pass")
    check("ผ่านก่อนจั่ว -> ถูกปฏิเสธ", not ok and "จั่วไพ่ก่อน" in msg, msg)

    # ---- หมดเวลา: ระบบจั่ว/ผ่านให้ แล้วเชิญออกเมื่อเงียบติดกัน ----
    uno.TURN_TIMEOUT = 0.15
    uno.MAX_IDLE_KICKS = 2
    s2._begin_turn()
    await pump(s2, lambda: s2.phase == "closed", 3.0)
    check("คนเงียบจนถูกเชิญออก เกมจบ (เหลือคนเดียวชนะ)", g2.winner is not None and len(g2.players) == 1,
          f"players={g2.players} winner={g2.winner}")

    # ---- ปุ่มจบเกมโดยเจ้าของ ----
    ch3 = FakeChannel(300)

    async def send3(*a, **kw):
        return await ch3.send(*a, **kw)
    s3 = await uno.open_uno_lobby(ch3, host, BOT_ID, send=send3)
    uno.TURN_TIMEOUT = 90
    await uno.LobbyView(s3).start.callback(FakeInteraction(host))
    nope = FakeInteraction(friend)
    await s3.table_view.end_game.callback(nope)
    check("คนอื่นกดจบเกมไม่ได้", s3.phase == "playing" and "เฉพาะเจ้าของ" in nope.response.sent[0][0])
    await s3.table_view.end_game.callback(FakeInteraction(host))
    check("เจ้าของกดจบเกมได้", s3.phase == "closed" and uno.get_session(ch3.id) is None)


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
