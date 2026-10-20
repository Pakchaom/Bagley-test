"""bagley/features/games/xo.py — เกม XO (ทิกแทกโท) เล่นกับแบ็คลี่ (3 ระดับ) หรือท้าเพื่อน ผ่านปุ่ม 3x3

ส่วนตรรกะ (check_winner / bot_choose) ไม่ผูกกับ Discord เทสต์ได้ตรงๆ
"""
from __future__ import annotations

import random
from functools import lru_cache
from typing import Awaitable, Callable, Optional

import discord

from bagley.features.games import banter

BOT_NAME = "แบ็คลี่"
LEVELS = ("ง่าย", "กลาง", "ยาก")
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
EMOJI = {"X": "❌", "O": "⭕"}


# ---------------------------------------------------------------- ตรรกะล้วนๆ
def check_winner(board: tuple | list) -> tuple[Optional[str], Optional[tuple[int, int, int]]]:
    for a, b, c in LINES:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a], (a, b, c)
    return None, None


def _empty(board) -> list[int]:
    return [i for i, v in enumerate(board) if v == " "]


@lru_cache(maxsize=None)
def _score(board: tuple, turn: str, me: str) -> int:
    """minimax: +ชนะ / 0 เสมอ / -แพ้ (มองจากฝั่ง me) เร็วกว่าชนะดีกว่า"""
    w, _ = check_winner(board)
    if w:
        return 10 - sum(v != " " for v in board) if w == me else -(10 - sum(v != " " for v in board))
    empt = _empty(board)
    if not empt:
        return 0
    nxt = "O" if turn == "X" else "X"
    scores = [_score(board[:i] + (turn,) + board[i + 1:], nxt, me) for i in empt]
    return max(scores) if turn == me else min(scores)


def bot_choose(board: list[str], mark: str, level: str = "ยาก", rng: Optional[random.Random] = None) -> int:
    rng = rng or random
    empt = _empty(board)
    if not empt:
        raise ValueError("กระดานเต็มแล้ว")
    opp = "O" if mark == "X" else "X"
    if level == "ง่าย":
        return rng.choice(empt)
    if level == "กลาง":
        for who in (mark, opp):                      # ชนะได้ก็ชนะ ไม่งั้นกันอีกฝั่งชนะ ไม่งั้นสุ่ม
            for i in empt:
                t = list(board)
                t[i] = who
                if check_winner(t)[0] == who:
                    return i
        return rng.choice(empt)
    t = tuple(board)
    scored = {i: _score(t[:i] + (mark,) + t[i + 1:], opp, mark) for i in empt}
    best = max(scored.values())
    return rng.choice([i for i, s in scored.items() if s == best])


# ---------------------------------------------------------------- Discord
class XOView(discord.ui.View):
    def __init__(self, x_player, o_player, level: str = "ยาก"):
        """x_player / o_player = ผู้ใช้ Discord หรือ None (= แบ็คลี่)"""
        super().__init__(timeout=180)
        self.players = {"X": x_player, "O": o_player}
        self.level = level
        self.board = [" "] * 9
        self.turn = "X"
        self.result: Optional[str] = None          # "X" / "O" / "draw"
        self.win_line: Optional[tuple] = None
        self.message: Optional[discord.Message] = None
        self.buttons: list[discord.ui.Button] = []
        self.quip = ""                  # คำพูดล่าสุดของแบ็คลี่ (เฉพาะเล่นกับแบ็คลี่)
        self._ctx: Optional[str] = None  # เหตุการณ์ตาที่แบ็คลี่เพิ่งเดิน: block / threat
        for i in range(9):
            b = discord.ui.Button(emoji="⬜", style=discord.ButtonStyle.secondary, row=i // 3)
            b.callback = self._make_cb(i)
            self.buttons.append(b)
            self.add_item(b)

    # ----- ข้อความ
    def _name(self, mark: str) -> str:
        p = self.players[mark]
        return BOT_NAME if p is None else p.display_name

    def header(self) -> str:
        vs = f"{EMOJI['X']} {self._name('X')}  vs  {EMOJI['O']} {self._name('O')}"
        if self.players["X"] is None or self.players["O"] is None:
            vs += f"  (ระดับ: {self.level})"
        if self.result == "draw":
            return f"{vs}\n🤝 เสมอกัน! สูสีมากครับ" + banter.tag(self.quip)
        if self.result:
            w = self.players[self.result]
            line = (f"🏆 {self._name(self.result)} ชนะ! " + ("ผมชนะแล้วครับ 😎" if w is None
                    else ("เก่งมากครับ 👏" if None in self.players.values() else "ยินดีด้วยครับ 👏")))
            return f"{vs}\n{line}" + banter.tag(self.quip)
        return f"{vs}\nตาของ {EMOJI[self.turn]} **{self._name(self.turn)}**" + banter.tag(self.quip)

    # ----- ลงหมาก
    def _apply(self, idx: int, mark: str) -> None:
        self.board[idx] = mark
        b = self.buttons[idx]
        b.emoji, b.disabled = EMOJI[mark], True
        b.style = discord.ButtonStyle.danger if mark == "X" else discord.ButtonStyle.primary
        w, line = check_winner(self.board)
        if w:
            self.result, self.win_line = w, line
        elif not _empty(self.board):
            self.result = "draw"
        else:
            self.turn = "O" if mark == "X" else "X"
        if self.result:
            for i, btn in enumerate(self.buttons):
                btn.disabled = True
                if line and i in line:
                    btn.style = discord.ButtonStyle.success
            self.stop()

    def bot_turn_if_needed(self) -> None:
        while self.result is None and self.players[self.turn] is None:
            mark = self.turn
            opp = "O" if mark == "X" else "X"
            idx = bot_choose(self.board, mark, self.level)
            blocked = check_winner(self.board[:idx] + [opp] + self.board[idx + 1:])[0] == opp   # ช่องนี้คืนช่องที่ฝั่งตรงข้ามจะชนะ
            self._apply(idx, mark)
            two = any(sum(self.board[i] == mark for i in ln) == 2 and sum(self.board[i] == " " for i in ln) == 1
                      for ln in LINES)
            self._ctx = "block" if blocked else ("threat" if two and self.result is None else None)

    def vs_bot(self) -> bool:
        return None in self.players.values()

    def choose_quip(self) -> str:
        """เลือกคำพูดตอบโต้หลังตาล่าสุด (เล่นกับคนด้วยกันไม่พูด) — จบเกม/บล็อก/ข่มขู่ พูดบ่อย ตานิ่งๆ พูดนานๆ ที"""
        if not self.vs_bot():
            return ""
        human = next((p for p in self.players.values() if p is not None), None)
        name = getattr(human, "display_name", "")
        if self.result == "draw":
            return banter.say("xo", "end_draw", name=name) or ""
        if self.result:
            ev = "end_bot_win" if self.players[self.result] is None else "end_player_win"
            return banter.say("xo", ev, name=name) or ""
        if self._ctx == "block":
            return banter.say("xo", "block", chance=0.9) or ""
        if self._ctx == "threat":
            return banter.say("xo", "threat", chance=0.6) or ""
        return banter.say("xo", "mid", chance=0.25) or ""

    def _make_cb(self, idx: int):
        async def cb(interaction: discord.Interaction):
            if self.result is not None:
                return await interaction.response.send_message("เกมนี้จบแล้วครับ", ephemeral=True)
            cur = self.players[self.turn]
            if cur is None or interaction.user.id != cur.id:
                who = "ตาของแบ็คลี่" if cur is None else f"ตาของ {cur.display_name}"
                return await interaction.response.send_message(f"ยังไม่ถึงตาคุณครับ ตอนนี้เป็น{who}", ephemeral=True)
            if self.board[idx] != " ":
                return await interaction.response.send_message("ช่องนี้มีคนลงแล้วครับ", ephemeral=True)
            self._ctx = None
            self._apply(idx, self.turn)
            self.bot_turn_if_needed()
            self.quip = self.choose_quip()
            await interaction.response.edit_message(content=self.header(), view=self)
        return cb

    async def on_timeout(self) -> None:
        if self.result is None and self.message is not None:
            for b in self.buttons:
                b.disabled = True
            try:
                await self.message.edit(content=self.header() + "\n⌛ หมดเวลาแล้วครับ (ไม่มีใครลงต่อ)", view=self)
            except Exception:
                pass


async def start_xo(send: Callable[..., Awaitable[discord.Message]], author, opponent=None, level: str = "ยาก") -> XOView:
    """เปิดเกม XO: opponent=None -> เล่นกับแบ็คลี่ (สุ่มว่าใครเดินก่อน) / ระบุคน -> ท้าคนนั้น"""
    if opponent is not None and (getattr(opponent, "bot", False) or opponent.id == author.id):
        opponent = None      # ท้าบอท/ท้าตัวเอง -> เล่นกับแบ็คลี่แทน
    if level not in LEVELS:
        level = "ยาก"
    if opponent is None:
        x, o = (author, None) if random.random() < 0.5 else (None, author)
    else:
        x, o = (author, opponent) if random.random() < 0.5 else (opponent, author)
    view = XOView(x, o, level)
    view.bot_turn_if_needed()          # ถ้าแบ็คลี่ได้เดินก่อน ลงหมากแรกให้เลย
    if view.vs_bot():
        view.quip = banter.say("xo", "start_bot_first" if x is None else "start_player_first",
                               name=getattr(author, "display_name", "")) or ""
    view.message = await send(content=view.header(), view=view)
    return view
