"""bagley/features/games/uno.py — ห้องเล่น UNO บน Discord (ปุ่ม/เมนู) ให้แบ็คลี่ร่วมเล่นเป็นผู้เล่นได้

ขั้นตอน: /uno -> ห้องรอ (ปุ่มเข้าร่วม/ให้แบ็คลี่เล่นด้วย/เริ่ม) -> ข้อความกระดานกลาง (ทุกคนเห็น: ไพ่บนสุด, จำนวนไพ่แต่ละคน, ตาใคร)
ไพ่ในมือเห็นคนเดียวผ่านปุ่ม "🃏 ไพ่ของฉัน" (ข้อความ ephemeral) -> เลือกไพ่จากเมนู / จั่ว / ผ่าน
เก็บห้องไว้ในแรมเท่านั้น (รีสตาร์ทบอท = เกมที่เล่นค้างหายไป)
"""
from __future__ import annotations

import asyncio
import random
from collections import Counter
from typing import Awaitable, Callable, Optional

import discord

from bagley.core.logutil import print
from bagley.features.games import banter
from bagley.features.games.uno_engine import (
    COLOR_EMOJI, COLOR_NAME, COLORS, MAX_PLAYERS, MIN_PLAYERS, VALUE_LABEL,
    Card, UnoError, UnoGame,
)

BOT_NAME = "แบ็คลี่"
LOBBY_TIMEOUT = 300          # ห้องรอ 5 นาที ไม่เริ่มก็ปิด
TURN_TIMEOUT = 90            # ผู้เล่นคนนึงคิดได้ตาละ 90 วิ เกินแล้วระบบจั่ว/ผ่านให้
MAX_IDLE_KICKS = 2           # หมดเวลาติดกัน 2 ตา = ถูกเชิญออกจากเกม
BOT_DELAY = (1.3, 2.4)       # แบ็คลี่ "คิด" ก่อนลงไพ่ (วินาที) ไม่ให้เร็วเหมือนเครื่อง

EMBED_COLOR = {"R": 0xE74C3C, "Y": 0xF1C40F, "G": 0x2ECC71, "B": 0x3498DB}

RULES_TEXT = (
    "**กติกา UNO (แบบเล่นง่าย)**\n"
    "• แจกคนละ 7 ใบ ลงไพ่ที่ *สีเดียวกัน / เลข-สัญลักษณ์เดียวกัน / Wild* ได้\n"
    "• 🚫 ข้าม = ข้ามคนถัดไป • 🔄 ย้อนทาง = กลับทิศ (เล่น 2 คน = ได้เล่นอีกตา)\n"
    "• +2 = คนถัดไปจั่ว 2 ใบและโดนข้าม • 🌈 Wild = เลือกสี • +4 Wild = เลือกสี + คนถัดไปจั่ว 4 ใบและโดนข้าม\n"
    "• ลงไพ่ไม่ได้ให้ *จั่ว* 1 ใบ ถ้าใบที่จั่วลงได้จะเลือกลง หรือกด *ผ่าน* ก็ได้\n"
    "• ระบบประกาศ UNO ให้เองเมื่อเหลือใบเดียว • ไม่มีการต่อ +2/+4 ซ้อน • หมดมือก่อนชนะ 🏆\n"
    f"• คิดนานเกิน {TURN_TIMEOUT} วิ ระบบจั่ว/ผ่านให้ และถ้าหมดเวลาติดกัน {MAX_IDLE_KICKS} ตาจะถูกเชิญออก"
)

BOT_QUIPS = [
    "ฮึ่ม ผมเริ่มมองเกมออกแล้วนะครับ 😏",
    "ไพ่ใบนี้ผมวางแผนไว้แล้วครับ 😎",
    "ใครจะรอดผมล่ะ 🤭",
    "ขอโทษทีนะครับ แต่ต้องลงใบนี้จริงๆ 😅",
    "เกมนี้ผมไม่ยอมแพ้ง่ายๆ หรอกครับ 💪",
]
BOT_WIN_LINES = [
    "ผมชนะแล้วครับ 😎 ขอบคุณที่เล่นด้วยนะครับ เอาใหม่ไหม?",
    "ไพ่หมดมือแล้วครับ! ผมชนะ 🏆 แต่สู้กันได้สนุกมากครับ",
]
BOT_LOSE_LINES = [
    "โอ้โห เก่งมากครับ ผมยอมแพ้ 🙇 เอาอีกตาไหมครับ?",
    "แพ้แล้วครับ ยินดีด้วยนะ 👏 เดี๋ยวตาหน้าผมแก้มือ!",
]

# channel_id -> UnoSession (ห้องรอหรือเกมที่กำลังเล่น หนึ่งห้องแชทต่อหนึ่งเกม)
_sessions: dict[int, "UnoSession"] = {}


def get_session(channel_id: int) -> Optional["UnoSession"]:
    return _sessions.get(channel_id)


# ---------------------------------------------------------------- ตัวช่วยแสดงผล
def _short(card: Card) -> str:
    return card.value if card.is_number else VALUE_LABEL[card.value]


def _sort_key(card: Card):
    order = ["skip", "reverse", "draw2", "wild", "draw4"]
    return (0, int(card.value)) if card.is_number else (1, order.index(card.value))


def format_hand(hand: list[Card]) -> str:
    if not hand:
        return "(ไม่มีไพ่)"
    lines = []
    for color in COLORS + ("W",):
        cards = sorted((c for c in hand if c.color == color), key=_sort_key)
        if not cards:
            continue
        counts = Counter(cards)
        seen, parts = set(), []
        for c in cards:
            if c in seen:
                continue
            seen.add(c)
            parts.append(_short(c) + (f"×{counts[c]}" if counts[c] > 1 else ""))
        title = COLOR_NAME.get(color, "Wild")
        lines.append(f"{COLOR_EMOJI[color]} **{title}**: " + ", ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------- เซสชัน (ห้องรอ + เกม)
class UnoSession:
    def __init__(self, channel: discord.abc.Messageable, host: discord.abc.User, bot_id: int):
        self.channel = channel
        self.host = host
        self.bot_id = bot_id
        self.humans: dict[int, discord.abc.User] = {host.id: host}
        self.with_bot = True
        self.phase = "lobby"                     # lobby | playing | closed
        self.game: Optional[UnoGame] = None
        self.lobby_message: Optional[discord.Message] = None
        self.table_message: Optional[discord.Message] = None
        self.table_view: Optional["TableView"] = None
        self.lock = asyncio.Lock()
        self.log: list[str] = []
        self.timeouts: dict[int, int] = {}
        self.turn_token = 0
        self._last_current: Optional[int] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._bot_task: Optional[asyncio.Task] = None
        self._tasks: set[asyncio.Task] = set()

    # ----- ห้องรอ
    def seats_used(self) -> int:
        return len(self.humans) + (1 if self.with_bot else 0)

    def lobby_embed(self) -> discord.Embed:
        e = discord.Embed(title="🃏 ห้องเล่น UNO", color=0xE74C3C,
                          description="กด **✋ เข้าร่วม** เพื่อเล่นด้วย เจ้าของห้องกด **▶️ เริ่มเกม** เมื่อพร้อม")
        rows = [f"{'👑' if uid == self.host.id else '•'} {u.display_name}" for uid, u in self.humans.items()]
        if self.with_bot:
            rows.append(f"🤖 **{BOT_NAME}** (ร่วมเล่นด้วย)")
        e.add_field(name=f"ผู้เล่น ({self.seats_used()}/{MAX_PLAYERS})", value="\n".join(rows), inline=False)
        e.set_footer(text=f"ต้องมีผู้เล่นอย่างน้อย {MIN_PLAYERS} คน (นับแบ็คลี่ด้วย) • ห้องจะปิดเองใน {LOBBY_TIMEOUT // 60} นาทีถ้าไม่เริ่ม")
        return e

    # ----- กระดานกลาง
    def _who(self, pid: int) -> str:
        return f"**{BOT_NAME}** 🤖" if pid == self.bot_id else f"<@{pid}>"

    def table_embed(self) -> discord.Embed:
        g = self.game
        e = discord.Embed(title="🃏 UNO", color=EMBED_COLOR.get(g.color, 0x95A5A6))
        e.description = (
            f"**ไพ่บนสุด:** {g.top.label()}\n"
            f"**สีที่ต้องลง:** {COLOR_EMOJI[g.color]} {COLOR_NAME[g.color]}\n"
            f"**ทิศ:** {'➡️' if g.direction == 1 else '⬅️'}  •  **กองจั่วเหลือ:** {len(g.draw_pile)} ใบ"
        )
        rows = []
        for pid, n in g.hand_sizes():
            arrow = "👉" if (pid == g.current and g.winner is None) else "▫️"
            rows.append(f"{arrow} {self._who(pid)} — {n} ใบ" + (" 🔔 UNO!" if n == 1 else ""))
        e.add_field(name="ผู้เล่น", value="\n".join(rows), inline=False)
        if self.log:
            e.add_field(name="เหตุการณ์ล่าสุด", value="\n".join(self.log[-6:]), inline=False)
        if g.winner is None:
            e.set_footer(text=f"ตาของ {g.name(g.current)} • กด 🃏 ไพ่ของฉัน เพื่อดูไพ่/ลงไพ่ (เห็นคนเดียว) • ตาละ {TURN_TIMEOUT} วิ")
        else:
            e.title = f"🏆 UNO — {g.name(g.winner)} ชนะ!"
            e.set_footer(text="จบเกมแล้ว พิมพ์ /uno เพื่อเปิดห้องใหม่")
        return e

    async def refresh_table(self) -> None:
        if self.game is None:
            return
        active = self.game.winner is None and self.phase == "playing"
        if self.table_view is None:
            self.table_view = TableView(self)
        view = self.table_view if active else None
        if not active:
            self.table_view.stop()
        try:
            if self.table_message is not None:
                await self.table_message.edit(embed=self.table_embed(), view=view)
                return
        except discord.HTTPException as e:
            print(f"⚠️ [UNO] แก้ข้อความกระดานไม่ได้ ส่งใหม่แทน: {e}")
        try:
            self.table_message = await self.channel.send(embed=self.table_embed(), view=view)
        except discord.HTTPException as e:
            print(f"❌ [UNO] ส่งกระดานไม่ได้: {e}")

    def _ensure_table_view(self) -> "TableView":
        if self.table_view is None:
            self.table_view = TableView(self)
        return self.table_view

    def _record(self, events: list[str]) -> None:
        self.log.extend(events)
        del self.log[:-12]

    def _spawn(self, coro: Awaitable) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    # ----- เริ่ม/จบเกม
    async def start_game(self) -> None:
        ids = list(self.humans)
        random.shuffle(ids)
        names = {uid: u.display_name[:24] for uid, u in self.humans.items()}
        if self.with_bot:
            ids.insert(random.randrange(len(ids) + 1), self.bot_id)
            names[self.bot_id] = BOT_NAME
        self.game = UnoGame(ids, names)
        self.phase = "playing"
        self.timeouts = {uid: 0 for uid in ids}
        self._record([f"เริ่มเกม! ไพ่แรกคือ {self.game.top.label()}"])
        intro = "🃏 เริ่มเกม UNO แล้ว!" + (f" {BOT_NAME} ลงสนามด้วย 😎" if self.with_bot else "")
        try:
            self.table_message = await self.channel.send(
                content=intro, embed=self.table_embed(), view=self._ensure_table_view(),
                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            print(f"❌ [UNO] เริ่มเกมไม่ได้: {e}")
            self.close()
            return
        if self.game.current == self.bot_id:
            self._kick_bot()
        else:
            self._begin_turn()

    def close(self) -> None:
        self.phase = "closed"
        if _sessions.get(self.channel.id) is self:
            _sessions.pop(self.channel.id, None)
        for t in list(self._tasks):
            if t is not asyncio.current_task():
                t.cancel()

    async def _finish(self) -> None:
        g = self.game
        winner = g.winner
        self.phase = "closed"
        await self.refresh_table()
        line = ""
        if winner == self.bot_id:
            line = random.choice(BOT_WIN_LINES)
        elif self.with_bot:
            line = random.choice(BOT_LOSE_LINES)
        try:
            await self.channel.send(f"🏆 {self._who(winner)} ชนะเกม UNO! {line}".strip(),
                                    allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
        self.close()

    async def end_by(self, who: discord.abc.User) -> None:
        self.phase = "closed"
        target = self.table_message or self.lobby_message
        if target is not None:
            try:
                await target.edit(content=f"🛑 {who.display_name} จบเกม UNO แล้วครับ", embed=None, view=None)
            except discord.HTTPException:
                pass
        self.close()

    # ----- การกระทำของผู้เล่นมนุษย์ (ถูกเรียกจากปุ่ม/เมนู) -> (สำเร็จไหม, ข้อความตอบ)
    async def act(self, uid: int, kind: str, idx: Optional[int] = None, color: Optional[str] = None) -> tuple[bool, str]:
        async with self.lock:
            g = self.game
            if self.phase != "playing" or g is None or g.winner is not None:
                return False, "เกมนี้จบแล้วครับ"
            try:
                if kind == "play":
                    events = g.play(uid, idx, color)
                    note = "✅ ลงไพ่แล้ว"
                elif kind == "draw":
                    card, can_play, events = g.draw(uid)
                    if card is None:
                        note = "ไม่มีไพ่ให้จั่วแล้ว ข้ามตาให้ครับ"
                    elif can_play:
                        note = f"🎴 คุณจั่วได้ {card.label()} — ลงได้! เลือกลง หรือกด ⏭️ ผ่าน"
                    else:
                        note = f"🎴 คุณจั่วได้ {card.label()} — ลงไม่ได้ ข้ามตาให้แล้วครับ"
                elif kind == "pass":
                    events = g.pass_turn(uid)
                    note = "⏭️ ผ่านตาแล้ว"
                else:
                    return False, "คำสั่งไม่ถูกต้อง"
            except UnoError as e:
                return False, f"❌ {e}"
            self.timeouts[uid] = 0
            if self.with_bot and kind == "play" and g.winner is None:
                line = self._human_banter(events, uid)
                if line:
                    events = events + [f"💬 {BOT_NAME}: {line}"]
            self._record(events)
        self._spawn(self._after_change())
        return True, note

    async def leave(self, uid: int) -> tuple[bool, str]:
        async with self.lock:
            g = self.game
            if self.phase != "playing" or g is None or g.winner is not None:
                return False, "เกมนี้จบแล้วครับ"
            if uid not in g.players or uid == self.bot_id:
                return False, "คุณไม่ได้อยู่ในเกมนี้ครับ"
            self._record(g.remove_player(uid))
        self._spawn(self._after_change())
        return True, "คุณออกจากเกมแล้วครับ"

    # ----- วงจรเกม
    async def _after_change(self) -> None:
        g = self.game
        await self.refresh_table()
        if g.winner is not None:
            await self._finish()
            return
        if g.current == self.bot_id:
            self._kick_bot()
        else:
            self._begin_turn()

    def _bot_banter(self, events: list[str]) -> Optional[str]:
        """แบ็คลี่พูดหลังตัวเองเดิน ตามสิ่งที่เพิ่งเกิด (โจมตี/ข้าม/เหลือใบเดียว/จั่ว) — None = เงียบ"""
        g = self.game
        bot = g.name(self.bot_id)
        text = "\n".join(events)
        victim = next((e for e in events if e.startswith("💥") and bot not in e), None)
        if victim is not None:
            name = victim[2:].split(" จั่ว")[0].strip()
            return banter.say("uno", "bot_attack", chance=0.8, name=name)
        if f"🔔 {bot}" in text:
            return banter.say("uno", "bot_uno")
        if "🚫" in text:
            return banter.say("uno", "bot_skip", chance=0.5)
        if f"{bot} จั่วไพ่" in text:
            return banter.say("uno", "bot_draw", chance=0.35)
        return None

    def _human_banter(self, events: list[str], uid: int) -> Optional[str]:
        """แบ็คลี่พูดตอบหลังผู้เล่นคนนั้นเดิน: โดนโจมตี / อีกฝ่ายเหลือใบเดียว"""
        g = self.game
        bot, who = g.name(self.bot_id), g.name(uid)
        if any(e.startswith("💥") and bot in e for e in events):
            return banter.say("uno", "human_hit_bot", chance=0.8, name=who)
        if any(e.startswith("🔔") for e in events):
            return banter.say("uno", "human_uno", chance=0.8, name=who)
        return None

    def _kick_bot(self) -> None:
        if self._bot_task is None or self._bot_task.done():
            self._bot_task = self._spawn(self._bot_loop())

    async def _bot_loop(self) -> None:
        try:
            while True:
                g = self.game
                if self.phase != "playing" or g.winner is not None or g.current != self.bot_id:
                    break
                await asyncio.sleep(random.uniform(*BOT_DELAY))
                async with self.lock:
                    if self.phase != "playing" or g.winner is not None or g.current != self.bot_id:
                        break
                    events = g.bot_move(self.bot_id)
                    if g.winner is None:
                        line = self._bot_banter(events)
                        if line is None and random.random() < 0.15:
                            line = random.choice(BOT_QUIPS)
                        if line:
                            events.append(f"💬 {BOT_NAME}: {line}")
                    self._record(events)
                await self.refresh_table()
                if g.winner is not None:
                    await self._finish()
                    return
            if self.phase == "playing" and self.game.winner is None:
                self._begin_turn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ [UNO] แบ็คลี่เล่นผิดพลาด: {e}")
            await self.end_by_error()

    async def end_by_error(self) -> None:
        try:
            await self.channel.send("😵 ขอโทษครับ เกม UNO มีข้อผิดพลาดเลยต้องปิดห้องนี้ไปก่อน ลองเปิดใหม่ด้วย /uno ได้เลยครับ")
        except discord.HTTPException:
            pass
        self.close()

    def _begin_turn(self) -> None:
        """ถึงตามนุษย์: ตั้งเวลานับถอยหลัง + ปิ้งเรียกถ้าเปลี่ยนคน"""
        g = self.game
        if g is None or g.winner is not None or g.current == self.bot_id:
            return
        self.turn_token += 1
        token = self.turn_token
        if self._timer_task is not None and self._timer_task is not asyncio.current_task():
            self._timer_task.cancel()
        self._timer_task = self._spawn(self._timeout_watch(token))
        if g.current != self._last_current:
            self._last_current = g.current
            self._spawn(self._ping(g.current))

    async def _ping(self, uid: int) -> None:
        try:
            await self.channel.send(f"🎯 <@{uid}> ถึงตาคุณแล้ว! กด 🃏 ไพ่ของฉัน", delete_after=25,
                                    allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass

    async def _timeout_watch(self, token: int) -> None:
        try:
            await asyncio.sleep(TURN_TIMEOUT)
        except asyncio.CancelledError:
            return
        async with self.lock:
            g = self.game
            if (token != self.turn_token or self.phase != "playing" or g is None
                    or g.winner is not None or g.current == self.bot_id):
                return
            pid = g.current
            self.timeouts[pid] = self.timeouts.get(pid, 0) + 1
            events = [f"⏰ {g.name(pid)} คิดนานเกินไป"]
            if self.timeouts[pid] >= MAX_IDLE_KICKS:
                events += g.remove_player(pid)
            else:
                try:
                    if not g.has_drawn:
                        g.draw(pid)
                    if g.winner is None and g.current == pid and g.has_drawn:
                        g.pass_turn(pid)
                    events.append("ระบบจั่วให้และข้ามตา")
                except UnoError:
                    pass
            self._record(events)
        await self._after_change()


# ---------------------------------------------------------------- ปุ่ม/เมนู
class LobbyView(discord.ui.View):
    def __init__(self, session: UnoSession):
        super().__init__(timeout=LOBBY_TIMEOUT)
        self.session = session

    async def on_timeout(self) -> None:
        s = self.session
        if s.phase == "lobby":
            s.close()
            try:
                await s.lobby_message.edit(content="⌛ ห้อง UNO หมดเวลาแล้วครับ (ไม่มีใครกดเริ่ม) เปิดใหม่ด้วย /uno ได้เลย",
                                           embed=None, view=None)
            except Exception:
                pass

    @discord.ui.button(label="เข้าร่วม", style=discord.ButtonStyle.success, emoji="✋")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        if s.phase != "lobby":
            return await interaction.response.send_message("เกมเริ่มไปแล้วครับ", ephemeral=True)
        if interaction.user.id in s.humans:
            return await interaction.response.send_message("คุณอยู่ในห้องแล้วครับ", ephemeral=True)
        if s.seats_used() >= MAX_PLAYERS:
            return await interaction.response.send_message("ห้องเต็มแล้วครับ", ephemeral=True)
        s.humans[interaction.user.id] = interaction.user
        await interaction.response.edit_message(embed=s.lobby_embed(), view=self)

    @discord.ui.button(label="ออก", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        if interaction.user.id == s.host.id:
            return await interaction.response.send_message("เจ้าของห้องออกไม่ได้ครับ ใช้ปุ่ม ❌ ยกเลิกห้อง แทน", ephemeral=True)
        if s.humans.pop(interaction.user.id, None) is None:
            return await interaction.response.send_message("คุณไม่ได้อยู่ในห้องนี้ครับ", ephemeral=True)
        await interaction.response.edit_message(embed=s.lobby_embed(), view=self)

    @discord.ui.button(label="แบ็คลี่เล่นด้วย: เปิด/ปิด", style=discord.ButtonStyle.primary, emoji="🤖")
    async def toggle_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        if interaction.user.id != s.host.id:
            return await interaction.response.send_message("เฉพาะเจ้าของห้องครับ", ephemeral=True)
        if not s.with_bot and s.seats_used() >= MAX_PLAYERS:
            return await interaction.response.send_message("ห้องเต็มแล้ว ไม่มีที่ให้แบ็คลี่ครับ", ephemeral=True)
        s.with_bot = not s.with_bot
        await interaction.response.edit_message(embed=s.lobby_embed(), view=self)

    @discord.ui.button(label="เริ่มเกม", style=discord.ButtonStyle.success, emoji="▶️", row=1)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        if interaction.user.id != s.host.id:
            return await interaction.response.send_message("เฉพาะเจ้าของห้องที่กดเริ่มได้ครับ", ephemeral=True)
        if s.phase != "lobby":
            return await interaction.response.send_message("เกมเริ่มไปแล้วครับ", ephemeral=True)
        if s.seats_used() < MIN_PLAYERS:
            return await interaction.response.send_message(
                "ต้องมีผู้เล่นอย่างน้อย 2 คนครับ — ชวนเพื่อนมากด ✋ หรือเปิด 🤖 ให้แบ็คลี่เล่นด้วยก็ได้", ephemeral=True)
        s.phase = "starting"
        await interaction.response.edit_message(content="🎮 กำลังเริ่มเกม...", embed=None, view=None)
        self.stop()
        await s.start_game()

    @discord.ui.button(label="กติกา", style=discord.ButtonStyle.secondary, emoji="📖", row=1)
    async def rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(RULES_TEXT, ephemeral=True)

    @discord.ui.button(label="ยกเลิกห้อง", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        perms = getattr(interaction.user, "guild_permissions", None)
        if interaction.user.id != s.host.id and not (perms and perms.manage_messages):
            return await interaction.response.send_message("เฉพาะเจ้าของห้องหรือแอดมินครับ", ephemeral=True)
        s.close()
        await interaction.response.edit_message(content="❌ ยกเลิกห้อง UNO แล้วครับ", embed=None, view=None)
        self.stop()


class TableView(discord.ui.View):
    def __init__(self, session: UnoSession):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="ไพ่ของฉัน", style=discord.ButtonStyle.primary, emoji="🃏")
    async def my_hand(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        g = s.game
        if g is None or interaction.user.id not in g.players:
            return await interaction.response.send_message("คุณไม่ได้อยู่ในเกมนี้ครับ", ephemeral=True)
        hv = HandView(s, interaction.user.id)
        await interaction.response.send_message(hv.content(), view=hv, ephemeral=True)

    @discord.ui.button(label="ออกจากเกม", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, msg = await self.session.leave(interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="จบเกม", style=discord.ButtonStyle.danger, emoji="🛑")
    async def end_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.session
        perms = getattr(interaction.user, "guild_permissions", None)
        if interaction.user.id != s.host.id and not (perms and perms.manage_messages):
            return await interaction.response.send_message("เฉพาะเจ้าของห้องหรือแอดมินที่จบเกมได้ครับ", ephemeral=True)
        await interaction.response.send_message("จบเกมให้แล้วครับ", ephemeral=True)
        await s.end_by(interaction.user)


class CardSelect(discord.ui.Select):
    def __init__(self, hand_view: "HandView", options: list[discord.SelectOption]):
        super().__init__(placeholder="เลือกไพ่ที่จะลง", options=options, min_values=1, max_values=1)
        self.hand_view = hand_view

    async def callback(self, interaction: discord.Interaction):
        hv = self.hand_view
        idx = int(self.values[0])
        g = hv.session.game
        hand = g.hands.get(hv.uid, []) if g else []
        if idx >= len(hand):
            return await hv.respond(interaction, "❌ ไพ่ในมือเปลี่ยนไปแล้วครับ")
        if hand[idx].is_wild:
            cv = ColorView(hv, idx)
            return await interaction.response.edit_message(content="🌈 เลือกสีที่ต้องการเปลี่ยน", view=cv)
        ok, note = await hv.session.act(hv.uid, "play", idx)
        await hv.respond(interaction, note)


class ColorView(discord.ui.View):
    _STYLE = {"R": discord.ButtonStyle.danger, "G": discord.ButtonStyle.success,
              "B": discord.ButtonStyle.primary, "Y": discord.ButtonStyle.secondary}

    def __init__(self, hand_view: "HandView", idx: int):
        super().__init__(timeout=120)
        self.hand_view = hand_view
        self.idx = idx
        for c in COLORS:
            b = discord.ui.Button(label=COLOR_NAME[c], emoji=COLOR_EMOJI[c], style=self._STYLE[c])
            b.callback = self._make_cb(c)
            self.add_item(b)
        back = discord.ui.Button(label="ย้อนกลับ", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    def _make_cb(self, color: str):
        async def cb(interaction: discord.Interaction):
            hv = self.hand_view
            ok, note = await hv.session.act(hv.uid, "play", self.idx, color)
            await hv.respond(interaction, note)
        return cb

    async def _back(self, interaction: discord.Interaction):
        await self.hand_view.respond(interaction, "")


class HandView(discord.ui.View):
    """หน้าต่างไพ่ส่วนตัว (ephemeral): เลือกไพ่/จั่ว/ผ่าน — สร้างใหม่ทุกครั้งที่สถานะเปลี่ยน"""

    def __init__(self, session: UnoSession, uid: int):
        super().__init__(timeout=600)
        self.session = session
        self.uid = uid
        self._rebuild()

    def _my_turn(self) -> bool:
        g = self.session.game
        return bool(g and g.winner is None and self.session.phase == "playing" and g.current == self.uid)

    def _rebuild(self) -> None:
        self.clear_items()
        g = self.session.game
        if self._my_turn():
            hand = g.hands[self.uid]
            seen: dict[Card, list[int]] = {}
            for i in g.playable_indices(self.uid):
                seen.setdefault(hand[i], []).append(i)
            options = [
                discord.SelectOption(label=_short(card)[:100], value=str(idxs[0]), emoji=COLOR_EMOJI[card.color],
                                     description=(f"มี {len(idxs)} ใบ" if len(idxs) > 1 else None))
                for card, idxs in sorted(seen.items(), key=lambda kv: (kv[0].color, _sort_key(kv[0])))
            ][:25]
            if options:
                self.add_item(CardSelect(self, options))
            if g.has_drawn:
                self._add_button("ผ่าน (ไม่ลงใบที่จั่ว)", discord.ButtonStyle.secondary, "⏭️", self._pass)
            else:
                self._add_button("จั่วไพ่", discord.ButtonStyle.primary, "🎴", self._draw)
        self._add_button("รีเฟรช", discord.ButtonStyle.secondary, "🔄", self._on_refresh)

    def _add_button(self, label, style, emoji, cb) -> None:
        b = discord.ui.Button(label=label, style=style, emoji=emoji)
        b.callback = cb
        self.add_item(b)

    def content(self, note: str = "") -> str:
        g = self.session.game
        if g is None or self.uid not in g.hands:
            return (note + "\n\n" if note else "") + "คุณไม่ได้อยู่ในเกมแล้วครับ"
        head = f"{note}\n\n" if note else ""
        state = f"**ไพ่บนสุด:** {g.top.label()}  •  **สี:** {COLOR_EMOJI[g.color]} {COLOR_NAME[g.color]}\n"
        if g.winner is not None:
            turn = "🏁 เกมจบแล้ว"
        elif g.current == self.uid:
            turn = "✅ **ถึงตาคุณแล้ว!**" + (" (จั่วแล้ว: ลงใบที่จั่วหรือกดผ่าน)" if g.has_drawn else "")
        else:
            turn = f"⏳ รอ {g.name(g.current)}"
        return f"{head}{state}{turn}\n\n**ไพ่ในมือ ({len(g.hands[self.uid])} ใบ)**\n{format_hand(g.hands[self.uid])}"

    async def respond(self, interaction: discord.Interaction, note: str) -> None:
        """แก้ข้อความส่วนตัวนี้ให้เป็นสถานะล่าสุด (สร้าง view ใหม่)"""
        nv = HandView(self.session, self.uid)
        await interaction.response.edit_message(content=nv.content(note), view=nv)
        self.stop()

    async def _draw(self, interaction: discord.Interaction):
        ok, note = await self.session.act(self.uid, "draw")
        await self.respond(interaction, note)

    async def _pass(self, interaction: discord.Interaction):
        ok, note = await self.session.act(self.uid, "pass")
        await self.respond(interaction, note)

    async def _on_refresh(self, interaction: discord.Interaction):
        await self.respond(interaction, "")


# ---------------------------------------------------------------- จุดเปิดห้อง (ใช้ร่วมกันทั้ง /uno และคำพูด "แบ็คลี่ เล่นอูโน่")
async def open_uno_lobby(channel: discord.abc.Messageable, host: discord.abc.User, bot_id: int,
                         send: Optional[Callable[..., Awaitable[discord.Message]]] = None) -> Optional[UnoSession]:
    cid = getattr(channel, "id", None)
    if cid in _sessions:
        old = _sessions[cid]
        text = ("มีห้อง UNO เปิดอยู่ในช่องนี้แล้วครับ" if old.phase == "lobby"
                else "ช่องนี้กำลังเล่น UNO อยู่ครับ รอให้จบก่อน หรือให้เจ้าของห้องกด 🛑 จบเกม")
        await (send or channel.send)(text)
        return None
    session = UnoSession(channel, host, bot_id)
    _sessions[cid] = session
    try:
        session.lobby_message = await (send or channel.send)(embed=session.lobby_embed(), view=LobbyView(session))
    except Exception:
        _sessions.pop(cid, None)
        raise
    return session
