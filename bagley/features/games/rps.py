"""bagley/features/games/rps.py — เป่ายิ้งฉุบ (ค้อน/กระดาษ/กรรไกร) สู้กับแบ็คลี่ แบบเก็บแต้ม (ชนะก่อน = เจ้าของเกม)

กดปุ่ม ✊ ✋ ✌️ ได้เฉพาะคนที่เปิดเกม — แบ็คลี่ไม่ได้ดูว่าคุณเลือกอะไรก่อนลงมือ (เลือกพร้อมกัน)
ระดับ "ง่าย" สุ่มล้วนๆ / "ยาก" แบ็คลี่จะจับทางว่าคุณชอบออกอะไรบ่อยแล้วออกสวน (บางตาเท่านั้น ยังสุ่มปนอยู่ ไม่โกง)

ส่วนตรรกะ (rps_result / bot_pick) ไม่ผูกกับ Discord เทสต์ได้ตรงๆ
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Awaitable, Callable, Optional

import discord

from bagley.features.games import banter

BOT_NAME = "แบ็คลี่"
LEVELS = ("ง่าย", "ยาก")
MOVES = ("rock", "paper", "scissors")
EMOJI = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
LABEL = {"rock": "ค้อน", "paper": "กระดาษ", "scissors": "กรรไกร"}
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}      # key ชนะ value
COUNTER = {v: k for k, v in BEATS.items()}                              # ท่าที่ชนะท่านี้
IDLE_TIMEOUT = 120
READ_CHANCE = 0.5            # ระดับยาก: โอกาสที่จะออกสวนท่าที่ผู้เล่นออกบ่อยสุด
BEST_OF = (1, 3, 5, 7)


# ---------------------------------------------------------------- ตรรกะล้วนๆ
def rps_result(player: str, bot: str) -> str:
    """มองจากฝั่งผู้เล่น: win / lose / draw"""
    if player == bot:
        return "draw"
    return "win" if BEATS[player] == bot else "lose"


def bot_pick(history: list[str], level: str = "ยาก", rng: Optional[random.Random] = None) -> str:
    """history = ท่าที่ผู้เล่นออกมาแล้ว (ก่อนตานี้เท่านั้น — ไม่แอบดูท่าตานี้)"""
    rng = rng or random
    if level != "ยาก" or len(history) < 2 or rng.random() >= READ_CHANCE:
        return rng.choice(MOVES)
    top = Counter(history).most_common()
    best = [m for m, n in top if n == top[0][1]]
    return COUNTER[rng.choice(best)]                       # ออกท่าที่ชนะท่าที่ผู้เล่นชอบออกบ่อยสุด


def wins_needed(best_of: int) -> int:
    return best_of // 2 + 1


class RPSGame:
    def __init__(self, best_of: int = 3, level: str = "ยาก", rng: Optional[random.Random] = None):
        self.best_of = best_of if best_of in BEST_OF else 3
        self.level = level if level in LEVELS else "ยาก"
        self.rng = rng or random
        self.player_moves: list[str] = []
        self.score = {"player": 0, "bot": 0}
        self.rounds: list[tuple[str, str, str]] = []        # (ท่าผู้เล่น, ท่าบอท, ผล)

    @property
    def status(self) -> str:
        need = wins_needed(self.best_of)
        if self.score["player"] >= need:
            return "won"
        return "lost" if self.score["bot"] >= need else "playing"

    def play(self, move: str) -> tuple[str, str]:
        """เล่น 1 ตา -> (ท่าบอท, ผล) ; เกมจบแล้วเล่นต่อไม่ได้"""
        if move not in MOVES:
            raise ValueError("ท่าไม่ถูกต้อง")
        if self.status != "playing":
            raise ValueError("เกมจบแล้ว")
        bm = bot_pick(self.player_moves, self.level, self.rng)
        res = rps_result(move, bm)
        self.player_moves.append(move)
        if res == "win":
            self.score["player"] += 1
        elif res == "lose":
            self.score["bot"] += 1
        self.rounds.append((move, bm, res))
        return bm, res


# ---------------------------------------------------------------- Discord
class RPSView(discord.ui.View):
    def __init__(self, player, game: RPSGame):
        super().__init__(timeout=IDLE_TIMEOUT)
        self.player, self.game = player, game
        self.message: Optional[discord.Message] = None
        self.buttons: list[discord.ui.Button] = []
        for m in MOVES:
            b = discord.ui.Button(label=LABEL[m], emoji=EMOJI[m], style=discord.ButtonStyle.primary)
            b.callback = self._make_cb(m)
            self.buttons.append(b)
            self.add_item(b)

    def header(self, note: str = "") -> str:
        g = self.game
        s = g.score
        lines = [f"✊✋✌️ **เป่ายิ้งฉุบ** · {self.player.display_name} vs {BOT_NAME} "
                 f"(ชนะก่อน {wins_needed(g.best_of)} ตา · ระดับ: {g.level})",
                 f"คะแนน: **{self.player.display_name} {s['player']} – {s['bot']} {BOT_NAME}**"]
        if g.rounds:
            lines.append("ตาที่ผ่านมา: " + "  ".join(
                f"{EMOJI[p]}vs{EMOJI[b]}{'🟢' if r == 'win' else '🔴' if r == 'lose' else '🟡'}" for p, b, r in g.rounds))
        if note:
            lines.append(note)
        if g.status == "won":
            lines.append("🏆 คุณชนะเกมนี้! เก่งมากครับ 👏 ผมขอแก้มือ!")
        elif g.status == "lost":
            lines.append("😎 ผมชนะเกมนี้ครับ! ขอบคุณที่เล่นด้วยนะ เอาใหม่ไหม?")
        else:
            lines.append("เลือกท่าของคุณได้เลยครับ 👇")
        return "\n".join(lines)

    def _banter(self, move: str, res: str) -> str:
        """คำพูดหลังจบตา: ออกท่าเดิมซ้ำ 3 ตา > ลุ้นแต้มสุดท้าย > พูดถึงผลตานั้น (จบเกมแล้วไม่พูดซ้ำกับบรรทัดสรุป)"""
        g = self.game
        if g.status != "playing":
            return ""
        need = wins_needed(g.best_of)
        pm = g.player_moves
        q = None
        if len(pm) >= 3 and pm[-1] == pm[-2] == pm[-3]:
            q = banter.say("rps", "streak", move=f"{EMOJI[move]} {LABEL[move]}")
        elif need > 1 and g.score["player"] == need - 1 and g.score["bot"] != need - 1:
            q = banter.say("rps", "match_point_player", chance=0.7)
        elif need > 1 and g.score["bot"] == need - 1 and g.score["player"] != need - 1:
            q = banter.say("rps", "match_point_bot", chance=0.7)
        if q is None:
            q = banter.say("rps", res, chance=0.6)
        return banter.tag(q)

    def _make_cb(self, move: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.player.id:
                return await interaction.response.send_message(
                    f"เกมนี้ของ {self.player.display_name} ครับ อยากเล่นบ้างพิมพ์ /rps ได้เลย", ephemeral=True)
            if self.game.status != "playing":
                return await interaction.response.send_message("เกมนี้จบแล้วครับ", ephemeral=True)
            bm, res = self.game.play(move)
            verdict = {"win": "✅ คุณชนะตานี้", "lose": "❌ ผมชนะตานี้", "draw": "🤝 เสมอ"}[res]
            note = f"คุณออก {EMOJI[move]} {LABEL[move]} · ผมออก {EMOJI[bm]} {LABEL[bm]} → {verdict}" + self._banter(move, res)
            if self.game.status != "playing":
                for b in self.buttons:
                    b.disabled = True
                self.stop()
            await interaction.response.edit_message(content=self.header(note), view=self)
        return cb

    async def on_timeout(self) -> None:
        if self.game.status == "playing" and self.message is not None:
            for b in self.buttons:
                b.disabled = True
            try:
                await self.message.edit(content=self.header("⌛ หมดเวลาแล้วครับ (ไม่มีใครกดต่อ)"), view=self)
            except Exception:
                pass


async def start_rps(send: Callable[..., Awaitable[discord.Message]], author, best_of: int = 3,
                    level: str = "ยาก") -> RPSView:
    """เปิดเกมเป่ายิ้งฉุบกับแบ็คลี่ (หลายคนเล่นพร้อมกันในช่องได้ — คนละเกมคนละข้อความ)"""
    view = RPSView(author, RPSGame(best_of, level))
    view.message = await send(content=view.header(), view=view)
    return view
