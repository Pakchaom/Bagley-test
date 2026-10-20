"""bagley/features/games/uno_engine.py — ตรรกะเกม UNO ล้วนๆ (ไม่ผูกกับ Discord เลย เทสต์ได้ตรงๆ)

กติกาที่ใช้ (เล่นง่าย ไม่ซับซ้อน):
  • ไพ่ 108 ใบ แจกคนละ 7 ใบ — ลงไพ่ที่ "สีเดียวกัน / เลขหรือสัญลักษณ์เดียวกัน / ไพ่ Wild" ได้
  • ข้าม = ข้ามคนถัดไป | ย้อนทาง = กลับทิศ (2 คนเล่น = ข้าม) | +2 = คนถัดไปจั่ว 2 แล้วโดนข้าม
  • Wild = เลือกสีใหม่ | Wild +4 = เลือกสี + คนถัดไปจั่ว 4 แล้วโดนข้าม (ไม่มีกติกาท้า/ไม่ต้องไม่มีสีตรง)
  • ไม่มีการต่อ +2/+4 ซ้อนกัน
  • ไม่มีไพ่ลงได้ -> จั่ว 1 ใบ ถ้าใบที่จั่วลงได้ เลือกลงเลยหรือผ่านก็ได้
  • หมดมือก่อนคือชนะ (ระบบประกาศ "UNO!" ให้เองเมื่อเหลือใบเดียว)
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

COLORS = ("R", "Y", "G", "B")
COLOR_EMOJI = {"R": "🟥", "Y": "🟨", "G": "🟩", "B": "🟦", "W": "⬛"}
COLOR_NAME = {"R": "แดง", "Y": "เหลือง", "G": "เขียว", "B": "น้ำเงิน"}
VALUE_LABEL = {
    "skip": "ข้าม 🚫",
    "reverse": "ย้อนทาง 🔄",
    "draw2": "+2",
    "wild": "เปลี่ยนสี 🌈",
    "draw4": "+4 เปลี่ยนสี 🌈",
}
MAX_PLAYERS = 8
MIN_PLAYERS = 2
HAND_SIZE = 7


class UnoError(Exception):
    """ทำตามที่ขอไม่ได้ (ไม่ใช่ตาคุณ / ลงไพ่ใบนี้ไม่ได้ ฯลฯ) — ข้อความเป็นภาษาไทยพร้อมโชว์ผู้เล่น"""


@dataclass(frozen=True)
class Card:
    color: str   # R / Y / G / B หรือ W (ไพ่ Wild)
    value: str   # "0".."9", skip, reverse, draw2, wild, draw4

    @property
    def is_wild(self) -> bool:
        return self.color == "W"

    @property
    def is_number(self) -> bool:
        return self.value.isdigit()

    def label(self) -> str:
        return f"{COLOR_EMOJI[self.color]} {VALUE_LABEL.get(self.value, self.value)}"

    __str__ = label


def build_deck() -> list[Card]:
    deck: list[Card] = []
    for c in COLORS:
        deck.append(Card(c, "0"))
        for n in range(1, 10):
            deck += [Card(c, str(n))] * 2
        for special in ("skip", "reverse", "draw2"):
            deck += [Card(c, special)] * 2
    deck += [Card("W", "wild")] * 4
    deck += [Card("W", "draw4")] * 4
    return deck  # 108 ใบ


class UnoGame:
    def __init__(self, player_ids: list[int], names: Optional[dict[int, str]] = None,
                 rng: Optional[random.Random] = None):
        if not (MIN_PLAYERS <= len(player_ids) <= MAX_PLAYERS):
            raise ValueError(f"UNO ต้องมีผู้เล่น {MIN_PLAYERS}-{MAX_PLAYERS} คน")
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("มีผู้เล่นซ้ำ")
        self.rng = rng or random.Random()
        self.players: list[int] = list(player_ids)
        self.names: dict[int, str] = dict(names or {})
        self.hands: dict[int, list[Card]] = {p: [] for p in self.players}
        self.draw_pile: list[Card] = build_deck()
        self.rng.shuffle(self.draw_pile)
        self.discard: list[Card] = []
        self.direction = 1
        self.turn = 0
        self.color: str = "R"
        self.winner: Optional[int] = None
        self.has_drawn = False                 # คนที่ถึงตาจั่วไปแล้วในตานี้
        self.drawn_index: Optional[int] = None  # ตำแหน่งไพ่ที่เพิ่งจั่ว (ลงได้เฉพาะใบนี้)

        for _ in range(HAND_SIZE):
            for p in self.players:
                self.hands[p].append(self._pop_draw())  # ไพ่ครบ 108 ใบเสมอ เริ่มต้นไม่มีทางหมดกอง

        # เปิดไพ่ใบแรก: ต้องเป็นเลขเท่านั้น (ไพ่ action/wild ใส่ก้นกองไปก่อน)
        while True:
            c = self._pop_draw()
            if c.is_number:
                self.discard.append(c)
                self.color = c.color
                break
            self.draw_pile.insert(0, c)

    # ---------- ข้อมูลที่ UI ใช้ ----------
    def name(self, pid: int) -> str:
        return self.names.get(pid, str(pid))

    @property
    def current(self) -> int:
        return self.players[self.turn]

    @property
    def top(self) -> Card:
        return self.discard[-1]

    def next_player(self, steps: int = 1) -> int:
        return self.players[(self.turn + self.direction * steps) % len(self.players)]

    def hand_sizes(self) -> list[tuple[int, int]]:
        return [(p, len(self.hands[p])) for p in self.players]

    # ---------- ไพ่ ----------
    def _pop_draw(self) -> Optional[Card]:
        if not self.draw_pile and len(self.discard) > 1:
            top = self.discard.pop()
            self.draw_pile = self.discard
            self.discard = [top]
            self.rng.shuffle(self.draw_pile)
        return self.draw_pile.pop() if self.draw_pile else None

    def _draw_cards(self, pid: int, n: int) -> int:
        got = 0
        for _ in range(n):
            c = self._pop_draw()
            if c is None:
                break
            self.hands[pid].append(c)
            got += 1
        return got

    def is_playable(self, card: Card) -> bool:
        return card.is_wild or card.color == self.color or card.value == self.top.value

    def playable_indices(self, pid: int) -> list[int]:
        hand = self.hands.get(pid, [])
        if pid == self.current and self.has_drawn:
            i = self.drawn_index
            return [i] if i is not None and i < len(hand) and self.is_playable(hand[i]) else []
        return [i for i, c in enumerate(hand) if self.is_playable(c)]

    # ---------- การกระทำของผู้เล่น ----------
    def _check_turn(self, pid: int) -> None:
        if self.winner is not None:
            raise UnoError("เกมจบไปแล้วครับ")
        if pid not in self.players:
            raise UnoError("คุณไม่ได้อยู่ในเกมนี้ครับ")
        if pid != self.current:
            raise UnoError(f"ยังไม่ถึงตาคุณครับ ตอนนี้เป็นตาของ {self.name(self.current)}")

    def _advance(self, steps: int = 1) -> None:
        self.turn = (self.turn + self.direction * steps) % len(self.players)
        self.has_drawn = False
        self.drawn_index = None

    def play(self, pid: int, index: int, chosen_color: Optional[str] = None) -> list[str]:
        self._check_turn(pid)
        hand = self.hands[pid]
        if not (0 <= index < len(hand)):
            raise UnoError("ไม่พบไพ่ใบนั้นในมือคุณครับ (มือเปลี่ยนไปแล้ว ลองกด “ไพ่ของฉัน” ใหม่)")
        if index not in self.playable_indices(pid):
            if self.has_drawn:
                raise UnoError("ตานี้ลงได้เฉพาะใบที่เพิ่งจั่วเท่านั้นครับ (หรือกดผ่าน)")
            raise UnoError("ไพ่ใบนี้ลงไม่ได้ครับ ต้องสี/เลข/สัญลักษณ์ตรงกับไพ่บนสุด หรือเป็นไพ่ Wild")
        card = hand[index]
        if card.is_wild and chosen_color not in COLORS:
            raise UnoError("ไพ่ Wild ต้องเลือกสีด้วยครับ")

        hand.pop(index)
        self.discard.append(card)
        self.color = chosen_color if card.is_wild else card.color
        events = [f"{self.name(pid)} ลง {card.label()}" + (f" → เลือกสี {COLOR_EMOJI[self.color]} {COLOR_NAME[self.color]}" if card.is_wild else "")]

        if not hand:
            self.winner = pid
            events.append(f"🏆 {self.name(pid)} ไพ่หมดมือ ชนะเกมนี้!")
            return events
        if len(hand) == 1:
            events.append(f"🔔 {self.name(pid)}: UNO! เหลือไพ่ใบสุดท้าย")

        if card.value == "skip":
            events.append(f"🚫 {self.name(self.next_player())} โดนข้ามตา")
            self._advance(2)
        elif card.value == "reverse":
            self.direction *= -1
            if len(self.players) == 2:
                events.append("🔄 ย้อนทาง (เล่น 2 คน = ได้เล่นอีกตา)")
                self._advance(2)
            else:
                events.append("🔄 ย้อนทิศทางการเล่น")
                self._advance(1)
        elif card.value in ("draw2", "draw4"):
            n = 2 if card.value == "draw2" else 4
            victim = self.next_player()
            got = self._draw_cards(victim, n)
            events.append(f"💥 {self.name(victim)} จั่ว {got} ใบและโดนข้ามตา")
            self._advance(2)
        else:
            self._advance(1)
        return events

    def draw(self, pid: int) -> tuple[Optional[Card], bool, list[str]]:
        """จั่ว 1 ใบ -> (ไพ่ที่จั่ว, ลงใบนี้ได้ไหม, ข้อความ) ถ้าลงไม่ได้ ระบบข้ามตาให้เอง"""
        self._check_turn(pid)
        if self.has_drawn:
            raise UnoError("คุณจั่วไปแล้วในตานี้ครับ ลงใบที่จั่วหรือกดผ่านได้เลย")
        got = self._pop_draw()
        if got is None:
            self._advance(1)
            return None, False, [f"{self.name(pid)} ไม่มีไพ่ให้จั่วแล้ว ข้ามตา"]
        self.hands[pid].append(got)
        self.has_drawn = True
        self.drawn_index = len(self.hands[pid]) - 1
        if self.is_playable(got):
            return got, True, [f"{self.name(pid)} จั่วไพ่ 1 ใบ"]
        self._advance(1)
        return got, False, [f"{self.name(pid)} จั่วไพ่ 1 ใบ (ลงไม่ได้ ข้ามตา)"]

    def pass_turn(self, pid: int) -> list[str]:
        self._check_turn(pid)
        if not self.has_drawn:
            raise UnoError("ต้องจั่วไพ่ก่อนถึงจะผ่านได้ครับ")
        self._advance(1)
        return [f"{self.name(pid)} ไม่ลงใบที่จั่ว ผ่านตา"]

    def remove_player(self, pid: int) -> list[str]:
        """เอาผู้เล่นออกจากเกม (ออกเอง/หมดเวลาหลายครั้ง) ไพ่ในมือกลับเข้าก้นกอง"""
        if pid not in self.players:
            return []
        i = self.players.index(pid)
        was_current = (i == self.turn)
        self.players.pop(i)
        self.draw_pile[0:0] = self.hands.pop(pid)
        events = [f"🚪 {self.name(pid)} ออกจากเกม"]
        if len(self.players) == 1:
            self.winner = self.players[0]
            events.append(f"🏆 เหลือ {self.name(self.winner)} คนเดียว ชนะไปเลย!")
            return events
        if was_current:
            self.has_drawn = False
            self.drawn_index = None
            self.turn = (i if self.direction == 1 else i - 1) % len(self.players)
        elif i < self.turn:
            self.turn -= 1
        return events

    # ---------- ตัวเล่นของแบ็คลี่ ----------
    def _best_color(self, pid: int) -> str:
        counts = {c: 0 for c in COLORS}
        for card in self.hands[pid]:
            if not card.is_wild:
                counts[card.color] += 1
        best = max(counts.values())
        return self.rng.choice([c for c, n in counts.items() if n == best])

    def _bot_pick(self, pid: int) -> Optional[int]:
        options = self.playable_indices(pid)
        if not options:
            return None
        hand = self.hands[pid]
        nxt_cards = len(self.hands[self.next_player()])
        color_count = {c: sum(1 for x in hand if x.color == c) for c in COLORS}

        def score(i: int) -> float:
            c = hand[i]
            s = self.rng.random()  # สุ่มเล็กน้อยกันเล่นซ้ำซากเดาง่าย
            if c.is_wild:
                s -= 5  # เก็บ Wild ไว้ใช้ตอนจำเป็น
                if c.value == "draw4" and nxt_cards <= 2:
                    s += 9  # คนถัดไปใกล้หมดมือ โจมตีเลย
            else:
                s += color_count[c.color] * 0.3
                if c.value in ("skip", "draw2", "reverse") and nxt_cards <= 3:
                    s += 4
                elif c.value in ("skip", "draw2", "reverse"):
                    s += 0.5
                if c.is_number:
                    s += int(c.value) * 0.05
            return s

        return max(options, key=score)

    def bot_move(self, pid: int) -> list[str]:
        """ให้ผู้เล่นคนนี้ (บอท) เดินหนึ่งตาแบบอัตโนมัติ"""
        self._check_turn(pid)
        events: list[str] = []
        pick = self._bot_pick(pid)
        if pick is None:
            card, can_play, ev = self.draw(pid)
            events += ev
            if not can_play:
                return events
            pick = self._bot_pick(pid)
            if pick is None:
                return events + self.pass_turn(pid)
        color = self._best_color(pid) if self.hands[pid][pick].is_wild else None
        return events + self.play(pid, pick, color)
