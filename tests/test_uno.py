"""ทดสอบตรรกะ UNO (ไม่ต้องใช้ discord/เน็ต)   รัน: PYTHONPATH=. python3 tests/test_uno.py"""
import random
import sys

from bagley.features.games.uno_engine import (COLORS, HAND_SIZE, Card, UnoError, UnoGame, build_deck)

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


def total_cards(g):
    return len(g.draw_pile) + len(g.discard) + sum(len(h) for h in g.hands.values())


def make(n=3, seed=1):
    return UnoGame(list(range(1, n + 1)), {i: f"P{i}" for i in range(1, n + 1)}, random.Random(seed))


def rig(g, hands, top, color=None):
    """จัดไพ่ตามต้องการ (ไพ่ส่วนที่เหลือคงที่ เพื่อให้จำนวนรวมยัง 108)"""
    g.draw_pile = [Card("R", "5")] * 30
    g.discard = [top]
    g.color = color or top.color
    for p, h in hands.items():
        g.hands[p] = list(h)
    g.has_drawn, g.drawn_index, g.winner, g.turn, g.direction = False, None, None, 0, 1


# ---- สำรับ ----
deck = build_deck()
check("สำรับ 108 ใบ", len(deck) == 108)
check("Wild 8 ใบ (wild 4 + draw4 4)", sum(c.is_wild for c in deck) == 8)
check("เลข 0 มีสีละ 1 ใบ", all(sum(1 for c in deck if c.color == col and c.value == "0") == 1 for col in COLORS))

# ---- เริ่มเกม ----
g = make(4)
check("แจกคนละ 7 ใบ", all(len(h) == HAND_SIZE for h in g.hands.values()))
check("ไพ่ใบแรกเป็นเลข", g.top.is_number)
check("สีปัจจุบันตรงไพ่แรก", g.color == g.top.color)
check("ไพ่รวม 108 ใบ", total_cards(g) == 108)
for bad_n in (1, 9):
    try:
        UnoGame(list(range(bad_n)))
        check(f"จำนวนผู้เล่น {bad_n} ต้อง error", False)
    except ValueError:
        check(f"จำนวนผู้เล่น {bad_n} ต้อง error", True)

# ---- กติกาลงไพ่ ----
g = make(3)
rig(g, {1: [Card("R", "3"), Card("B", "7"), Card("W", "wild")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
check("ลงสีเดียวกันได้", g.playable_indices(1) == [0, 2])
try:
    g.play(2, 0)
    check("ไม่ใช่ตา -> ต้อง error", False)
except UnoError:
    check("ไม่ใช่ตา -> ต้อง error", True)
try:
    g.play(1, 1)
    check("ลงไพ่ผิดสี -> ต้อง error", False)
except UnoError:
    check("ลงไพ่ผิดสี -> ต้อง error", True)
try:
    g.play(1, 2)
    check("Wild ไม่เลือกสี -> ต้อง error", False)
except UnoError:
    check("Wild ไม่เลือกสี -> ต้อง error", True)
g.play(1, 0)
check("ลงแล้วเปลี่ยนเป็นตาคนถัดไป", g.current == 2 and g.top == Card("R", "3"))

g = make(3)
rig(g, {1: [Card("B", "9"), Card("W", "wild")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
check("เลขเดียวกันต่างสีลงได้", g.playable_indices(1) == [0, 1])
g.play(1, 1, "G")
check("Wild เปลี่ยนสีได้", g.color == "G" and g.current == 2)

# ---- ไพ่พิเศษ ----
g = make(3)
rig(g, {1: [Card("R", "skip"), Card("R", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.play(1, 0)
check("Skip ข้ามคนถัดไป", g.current == 3)

g = make(3)
rig(g, {1: [Card("R", "reverse"), Card("R", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.play(1, 0)
check("Reverse 3 คน -> ย้อนกลับไปหาคนที่ 3", g.current == 3 and g.direction == -1)

g = make(2)
rig(g, {1: [Card("R", "reverse"), Card("R", "1")], 2: [Card("G", "1")] * 3}, Card("R", "9"))
g.play(1, 0)
check("Reverse 2 คน = เล่นอีกตา", g.current == 1)

g = make(3)
rig(g, {1: [Card("R", "draw2"), Card("R", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.play(1, 0)
check("+2 คนถัดไปได้ 5 ใบและโดนข้าม", len(g.hands[2]) == 5 and g.current == 3)

g = make(3)
rig(g, {1: [Card("W", "draw4"), Card("R", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.play(1, 0, "B")
check("+4 คนถัดไปได้ 7 ใบ โดนข้าม และเปลี่ยนสี", len(g.hands[2]) == 7 and g.current == 3 and g.color == "B")

# ---- จั่ว/ผ่าน ----
g = make(3)
rig(g, {1: [Card("B", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.draw_pile = [Card("B", "2")]           # ลงไม่ได้
card, can, _ = g.draw(1)
check("จั่วใบที่ลงไม่ได้ -> ข้ามตาอัตโนมัติ", not can and g.current == 2 and len(g.hands[1]) == 2)

g = make(3)
rig(g, {1: [Card("B", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.draw_pile = [Card("R", "2")]           # ลงได้
card, can, _ = g.draw(1)
check("จั่วได้ใบที่ลงได้ -> ยังเป็นตาเดิม", can and g.current == 1)
check("หลังจั่วลงได้เฉพาะใบที่จั่ว", g.playable_indices(1) == [1])
try:
    g.draw(1)
    check("จั่วซ้ำ -> ต้อง error", False)
except UnoError:
    check("จั่วซ้ำ -> ต้อง error", True)
g.pass_turn(1)
check("ผ่านตาได้หลังจั่ว", g.current == 2 and not g.has_drawn)
try:
    g.pass_turn(2)
    check("ผ่านโดยไม่จั่ว -> ต้อง error", False)
except UnoError:
    check("ผ่านโดยไม่จั่ว -> ต้อง error", True)

# ---- กองหมด -> สับกองทิ้งกลับมา ----
g = make(2)
rig(g, {1: [Card("B", "1")], 2: [Card("G", "1")]}, Card("R", "9"))
g.draw_pile = []
g.discard = [Card("Y", "4"), Card("Y", "5"), Card("R", "9")]
g.color = "R"
c = g._pop_draw()
check("กองจั่วหมดแล้วสับกองทิ้งกลับมา (เหลือใบบนสุดไว้)", c is not None and g.discard == [Card("R", "9")] and len(g.draw_pile) == 1)

# ---- ชนะ ----
g = make(3)
rig(g, {1: [Card("R", "1")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
ev = g.play(1, 0)
check("ไพ่หมดมือ = ชนะ", g.winner == 1 and any("ชนะ" in e for e in ev))
try:
    g.play(1, 0)
    check("เกมจบแล้วเล่นต่อไม่ได้", False)
except UnoError:
    check("เกมจบแล้วเล่นต่อไม่ได้", True)

g = make(3)
rig(g, {1: [Card("R", "1"), Card("R", "2")], 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
ev = g.play(1, 0)
check("เหลือใบเดียวประกาศ UNO", any("UNO" in e for e in ev))

# ---- เอาผู้เล่นออก ----
g = make(3)
rig(g, {1: [Card("R", "1")] * 2, 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.remove_player(1)
check("ออกตอนเป็นตาตัวเอง -> ตาถัดไปคนต่อมา", g.players == [2, 3] and g.current == 2)
check("ไพ่ของคนออกกลับเข้ากอง (รวมยัง 108 ไม่นับไพ่ที่ rig)", 1 not in g.hands)

g = make(3)
rig(g, {1: [Card("R", "1")] * 2, 2: [Card("G", "1")] * 3, 3: [Card("G", "1")] * 3}, Card("R", "9"))
g.turn = 2
g.remove_player(1)
check("คนก่อนหน้าตาออก -> ยังเป็นตาคนเดิม", g.current == 3)

g = make(2)
g.remove_player(1)
check("เหลือคนเดียว -> ชนะทันที", g.winner == 2)

# ---- บอทเล่นกันเอง 300 เกม: ต้องจบ ไม่ crash ไพ่ไม่หาย/ไม่เพิ่ม ----
finished = unfinished = 0
for seed in range(300):
    n = 2 + seed % 7
    g = make(n, seed)
    steps = 0
    ok = True
    while g.winner is None and steps < 3000:
        g.bot_move(g.current)
        steps += 1
        if total_cards(g) != 108:
            ok = False
            break
    if not ok:
        check(f"ไพ่รวมคงที่ 108 (seed {seed})", False)
        break
    finished += g.winner is not None
    unfinished += g.winner is None
check("บอทเล่นกันเอง 300 เกมจบทุกเกม ไพ่ไม่หาย", finished == 300 and unfinished == 0, f"จบ {finished}/300")

print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
