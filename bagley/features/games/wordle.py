"""bagley/features/games/wordle.py — เกมทายคำ 5 ตัวอักษรแบบ Wordle (ภาษาอังกฤษ) เล่นรวมกันทั้งช่อง

แบ็คลี่สุ่มคำลับ 5 ตัว ทุกคนช่วยกันทาย ทายได้ 6 ครั้ง หลังทายแต่ละครั้งจะได้ใบ้เป็นสี
  🟩 ถูกตัวและถูกตำแหน่ง   🟨 มีในคำแต่ผิดตำแหน่ง   ⬛ ไม่มีในคำ
  • ทายคำไหนก็ได้ที่เป็นตัวอักษร a–z 5 ตัว (ไม่ได้ตรวจกับพจนานุกรม)
  • 🤖 ให้แบ็คลี่ช่วยเดา = แบ็คลี่เลือกคำที่ยังเข้ากับใบ้ทั้งหมดที่มีมาแล้ว แล้วทายให้ 1 ครั้ง

ส่วนตรรกะ (score_guess / WordleGame) ไม่ผูกกับ Discord เทสต์ได้ตรงๆ — เก็บห้องในแรม หนึ่งช่องต่อหนึ่งเกม
"""
from __future__ import annotations

import random
import re
from collections import Counter
from typing import Awaitable, Callable, Optional

import discord

from bagley.features.games import banter

BOT_NAME = "แบ็คลี่"
MAX_TRIES = 6
WORD_LEN = 5
IDLE_TIMEOUT = 600
OPENER = "crane"
SQUARE = {"g": "🟩", "y": "🟨", "b": "⬛"}

ANSWERS = """
about above actor adult after again agree ahead alarm album alert alive allow alone along amaze angel anger angle
angry apple apply arena argue arise armor aroma array arrow aside asset avoid awake award aware basic beach beard
begin being below bench birth black blade blame blank blast blend bless blind block blood bloom board boost bound
brain brand bread break brick bride brief bring broad brown brush build bunch burst cabin cable candy carry catch
cause chain chair chalk charm chart chase cheap check cheer chess chest chief child chill choir civil claim class
clean clear clerk click cliff climb clock close cloud coach coast color couch count court cover craft crane crash
crazy cream crime cross crowd crown cycle daily dance dealt death debut delay depth dirty doubt dozen draft drama
dream dress drink drive eager early earth eight elite empty enemy enjoy enter equal error event every exact exist
extra faith false fancy fault feast fever field fight final first flame flash fleet flesh float flood floor flour
focus force forth forum found frame fresh front fruit funny ghost giant given glass globe glory grace grade grain
grand grant grape graph grass great green greet group guard guess guest guide habit happy harsh heart heavy hello
horse hotel house human humor ideal image index inner input issue ivory jelly joint judge juice knife known label
labor large laser later laugh layer learn least leave legal lemon level light limit local logic loose lucky lunch
magic major maple march match maybe mayor meant medal media merit metal meter might minor minus mixed model money
month moral motor mount mouse mouth movie music naked nerve never newly night noble noise north novel nurse ocean
offer often olive onion opera orbit order other ought outer owner paint panel paper party pasta peace pearl phase
phone photo piano pilot pitch pizza place plain plane plant plate point polar power press price pride prime print
prize proof proud pulse queen quick quiet quote radio raise range rapid ratio reach ready realm relax reply rider
right river robot rough round route royal rural salad scale scene scope score sense serve seven shade shake shape
share sharp sheep sheet shelf shell shift shine shirt shock shoot short shown sight silly since skill sleep slice
slide small smart smile smoke snake solar solid solve sound south space spare speak speed spell spend spice split
spoon sport staff stage stair stamp stand start state steam steel stick still stone store storm story strip study
style sugar suite sunny super sweet swing table taste teach teeth thank theme there thick thing think third three
throw thumb tiger tight timer title toast today token tooth topic total touch tough tower trace track trade trail
train treat trend trial tribe truck truly trust truth twice uncle under union unity until upper upset urban usage
usual valid value video virus visit vital vivid voice waste watch water weigh wheel where which while white whole
whose width woman world worry worth would write wrong young youth zebra
""".split()
ANSWERS = sorted(set(w for w in ANSWERS if len(w) == WORD_LEN and w.isalpha()))


# ---------------------------------------------------------------- ตรรกะล้วนๆ
def score_guess(answer: str, guess: str) -> list[str]:
    """ให้สีต่อตัว: g = ถูกที่, y = มีแต่ผิดที่, b = ไม่มี (จัดการตัวซ้ำถูกต้องแบบ Wordle จริง)"""
    res = ["b"] * len(answer)
    remain: Counter = Counter()
    for i, (a, g) in enumerate(zip(answer, guess)):
        if a == g:
            res[i] = "g"
        else:
            remain[a] += 1
    for i, g in enumerate(guess):
        if res[i] == "b" and remain[g] > 0:
            res[i] = "y"
            remain[g] -= 1
    return res


class WordleGame:
    def __init__(self, answer: str):
        self.answer = answer.lower()
        self.history: list[tuple[str, list[str]]] = []
        self.gave_up = False

    @property
    def status(self) -> str:
        if self.history and self.history[-1][0] == self.answer:
            return "won"
        if self.gave_up or len(self.history) >= MAX_TRIES:
            return "lost"
        return "playing"

    def normalize(self, text: str) -> Optional[str]:
        t = (text or "").strip().lower()
        return t if re.fullmatch(r"[a-z]{%d}" % WORD_LEN, t) else None

    def guess(self, text: str) -> str:
        """คืน invalid / dup / ok"""
        w = self.normalize(text)
        if w is None:
            return "invalid"
        if any(w == h for h, _ in self.history):
            return "dup"
        self.history.append((w, score_guess(self.answer, w)))
        return "ok"

    def keyboard(self) -> dict[str, str]:
        """สถานะดีที่สุดของแต่ละตัวอักษรที่เคยทาย: g > y > b"""
        rank = {"b": 0, "y": 1, "g": 2}
        best: dict[str, str] = {}
        for w, marks in self.history:
            for ch, m in zip(w, marks):
                if ch not in best or rank[m] > rank[best[ch]]:
                    best[ch] = m
        return best

    def candidates(self, pool: Optional[list[str]] = None) -> list[str]:
        """คำที่ยังเข้ากับใบ้ทุกครั้งที่ผ่านมา (ถ้าคำนั้นเป็นคำลับ ใบ้ต้องออกมาเหมือนเดิมเป๊ะ)"""
        pool = ANSWERS if pool is None else pool
        return [c for c in pool if all(score_guess(c, w) == m for w, m in self.history)]

    def bot_guess(self, pool: Optional[list[str]] = None, rng: Optional[random.Random] = None) -> Optional[str]:
        rng = rng or random
        if not self.history:
            return OPENER
        cands = [c for c in self.candidates(pool) if all(c != h for h, _ in self.history)]
        return rng.choice(cands) if cands else None

    # ----- แสดงผล
    def board(self) -> str:
        rows = [f"{''.join(SQUARE[m] for m in marks)}  `{w.upper()}`" for w, marks in self.history]
        rows += ["⬜" * WORD_LEN] * (MAX_TRIES - len(self.history))
        return "\n".join(rows)

    def keyboard_text(self) -> str:
        kb = self.keyboard()
        parts = []
        for m, label in (("g", "🟩 ถูกที่"), ("y", "🟨 ผิดที่"), ("b", "⬛ ไม่มี")):
            letters = " ".join(sorted(c.upper() for c, v in kb.items() if v == m))
            if letters:
                parts.append(f"{label}: {letters}")
        return "  ·  ".join(parts)


def new_game(rng: Optional[random.Random] = None) -> WordleGame:
    return WordleGame((rng or random).choice(ANSWERS))


# ---------------------------------------------------------------- Discord
_active: dict[int, "WordleView"] = {}


def get_active(channel_id: int) -> Optional["WordleView"]:
    return _active.get(channel_id)


class _GuessModal(discord.ui.Modal):
    def __init__(self, wv: "WordleView"):
        super().__init__(title="ทายคำ 5 ตัวอักษร", timeout=120)
        self.wv = wv
        self.box = discord.ui.TextInput(label="พิมพ์คำภาษาอังกฤษ 5 ตัว", min_length=WORD_LEN, max_length=WORD_LEN,
                                        required=True)
        self.add_item(self.box)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.wv.do_guess(interaction, str(self.box.value))


class WordleView(discord.ui.View):
    def __init__(self, game: WordleGame, host, channel_id: int):
        super().__init__(timeout=IDLE_TIMEOUT)
        self.game, self.host, self.channel_id = game, host, channel_id
        self.message: Optional[discord.Message] = None
        self.names: dict[int, str] = {}
        self.credit: list[str] = []                 # ชื่อคนที่ทายแต่ละครั้งตามลำดับ
        self.build()

    def render(self, note: str = "") -> str:
        g = self.game
        lines = [f"🔤 **ทายคำ (Wordle)** · คำอังกฤษ {WORD_LEN} ตัว · ทายแล้ว {len(g.history)}/{MAX_TRIES}",
                 g.board()]
        kb = g.keyboard_text()
        if kb:
            lines.append(kb)
        if note:
            lines.append(note)
        if g.status == "won":
            lines.append(f"🏆 **ถูกต้อง!** คำคือ **{g.answer.upper()}** ใช้ {len(g.history)} ครั้ง — "
                         f"คนทายตามลำดับ: {' → '.join(self.credit)}")
        elif g.status == "lost":
            lines.append(f"💀 **หมดโอกาส** คำคือ **{g.answer.upper()}** — เอาใหม่ไหมครับ?")
        return "\n".join(lines)

    def build(self) -> None:
        self.clear_items()
        if self.game.status != "playing":
            return
        for label, emoji, style, cb in (
            ("ทายคำ", "✏️", discord.ButtonStyle.primary, self._guess_btn),
            ("ให้แบ็คลี่ช่วยเดา", "🤖", discord.ButtonStyle.secondary, self._bot_btn),
            ("จบเกม", "🛑", discord.ButtonStyle.danger, self._end_btn),
        ):
            b = discord.ui.Button(label=label, emoji=emoji, style=style, row=0)
            b.callback = cb
            self.add_item(b)

    def _finish(self) -> None:
        _active.pop(self.channel_id, None)
        self.clear_items()
        self.stop()

    async def _update(self, interaction, note: str = "") -> None:
        if self.game.status != "playing":
            self._finish()
        else:
            self.build()
        await interaction.response.edit_message(content=self.render(note), view=self)

    async def _closed(self, interaction) -> bool:
        if self.game.status != "playing":
            await interaction.response.send_message("เกมนี้จบแล้วครับ", ephemeral=True)
            return True
        return False

    def _react(self) -> str:
        """คำพูดตอบโต้หลังทายล่าสุด: ตัวเลขที่ได้ + ใกล้จบ/ชนะเร็วช้า"""
        g = self.game
        marks = g.history[-1][1]
        greens, tries = marks.count("g"), len(g.history)
        if g.status == "won":
            ev = "win_fast" if tries <= 2 else "win_mid" if tries <= 4 else "win_slow"
            return banter.tag(banter.say("wordle", ev))
        if g.status == "lost":
            return ""
        if tries == MAX_TRIES - 1:
            return banter.tag(banter.say("wordle", "last_try"))
        if marks.count("b") == WORD_LEN:
            return banter.tag(banter.say("wordle", "all_gray", chance=0.8))
        if greens >= 3:
            return banter.tag(banter.say("wordle", "close", chance=0.8))
        return banter.tag(banter.say("wordle", "mid", chance=0.2))

    async def do_guess(self, interaction, text: str) -> None:
        if await self._closed(interaction):
            return
        res = self.game.guess(text)
        if res == "invalid":
            return await interaction.response.send_message(f"ต้องเป็นตัวอักษร a–z {WORD_LEN} ตัวเท่านั้นครับ", ephemeral=True)
        if res == "dup":
            return await interaction.response.send_message("คำนี้ถูกทายไปแล้วครับ", ephemeral=True)
        self.names[interaction.user.id] = interaction.user.display_name
        self.credit.append(interaction.user.display_name)
        await self._update(interaction, self._react().lstrip("\n"))

    async def _guess_btn(self, interaction):
        if not await self._closed(interaction):
            await interaction.response.send_modal(_GuessModal(self))

    async def _bot_btn(self, interaction):
        if await self._closed(interaction):
            return
        w = self.game.bot_guess()
        if w is None or self.game.guess(w) != "ok":
            return await interaction.response.send_message("ผมคิดไม่ออกเลยครับ 😅 ลองทายเองดูนะ", ephemeral=True)
        self.credit.append(BOT_NAME)
        await self._update(interaction, f"🤖 {BOT_NAME} ช่วยทาย **{w.upper()}**")

    async def _end_btn(self, interaction):
        perms = getattr(interaction.user, "guild_permissions", None)
        if interaction.user.id != self.host.id and not (perms and perms.manage_messages):
            return await interaction.response.send_message("❌ เฉพาะคนเปิดเกมหรือแอดมินที่จบเกมได้ครับ", ephemeral=True)
        self.game.gave_up = True
        await self._update(interaction, f"🛑 {interaction.user.display_name} จบเกม")

    async def on_timeout(self) -> None:
        _active.pop(self.channel_id, None)
        if self.game.status == "playing" and self.message is not None:
            self.clear_items()
            try:
                await self.message.edit(content=self.render(
                    f"⌛ หมดเวลาแล้วครับ คำคือ **{self.game.answer.upper()}**"), view=self)
            except Exception:
                pass


async def start_wordle(send: Callable[..., Awaitable[discord.Message]], channel_id: int, host) -> Optional[WordleView]:
    """เปิดเกมทายคำในช่อง (หนึ่งช่องต่อหนึ่งเกม) — คืน None ถ้าช่องนี้มีเกมค้างอยู่"""
    if channel_id in _active:
        await send("ช่องนี้มีเกมทายคำเล่นอยู่แล้วครับ เล่นให้จบก่อน หรือกด 🛑 จบเกม")
        return None
    view = WordleView(new_game(), host, channel_id)
    _active[channel_id] = view
    try:
        view.message = await send(content=view.render(
            "ทุกคนช่วยกันทายได้เลยครับ กด ✏️ ทายคำ!" + banter.tag(banter.say("wordle", "start"))), view=view)
    except Exception:
        _active.pop(channel_id, None)
        raise
    return view


async def force_end(channel_id: int, by_name: str = "") -> bool:
    """จบเกมที่ค้างในช่องทันที (ใช้กับ /wordle_end) — คืน False ถ้าช่องนี้ไม่มีเกมเปิดอยู่"""
    view = _active.get(channel_id)
    if view is None:
        return False
    view.game.gave_up = True
    view._finish()
    if view.message is not None:
        try:
            await view.message.edit(content=view.render(f"🛑 {by_name} จบเกม".strip()), view=view)
        except Exception:
            pass
    return True
