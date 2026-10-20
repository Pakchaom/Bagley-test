"""bagley/features/games/hangman.py — เกม Hangman (ทายคำ) เล่นรวมกันทั้งช่อง ภาษาอังกฤษ/ไทย

วิธีเล่น: แบ็คลี่สุ่มคำลับ (บอกหมวดให้) ทุกคนในช่องช่วยกันทายทีละตัวอักษร หรือทายทั้งคำ ผิดได้ 6 ครั้งก่อนแพ้
  • อังกฤษ: เลือกตัวอักษรจากเมนู A–M / N–Z      • ไทย: กดปุ่มแล้วพิมพ์พยัญชนะ 1 ตัว (สระ/วรรณยุกต์โชว์ให้เลย)
  • 💡 ใบ้ = เปิดตัวอักษรให้ 1 ตัว แต่เสียหัวใจ 1 ดวง   • 🤖 ให้แบ็คลี่เดา 1 ตัว (เดาจากความถี่ในคลังคำ)

ส่วนตรรกะ (HangmanGame) ไม่ผูกกับ Discord เทสต์ได้ตรงๆ — ห้องเกมเก็บในแรมเท่านั้น หนึ่งช่องต่อหนึ่งเกม
"""
from __future__ import annotations

import random
import re
from collections import Counter
from typing import Awaitable, Callable, Optional

import discord

from bagley.features.games import banter

BOT_NAME = "แบ็คลี่"
MAX_WRONG = 6
IDLE_TIMEOUT = 300

# ---------------------------------------------------------------- คลังคำ
WORDS: dict[str, dict[str, list[str]]] = {
    "en": {
        "สัตว์": ["elephant", "giraffe", "penguin", "dolphin", "kangaroo", "monkey", "tiger", "rabbit",
                  "turtle", "octopus", "crocodile", "butterfly"],
        "ผลไม้": ["banana", "orange", "mango", "pineapple", "strawberry", "watermelon", "coconut", "papaya",
                  "lychee", "grape", "cherry"],
        "เทคโนโลยี": ["keyboard", "internet", "python", "discord", "server", "battery", "monitor", "database",
                      "browser", "algorithm", "wireless"],
        "สถานที่": ["airport", "library", "hospital", "stadium", "museum", "beach", "mountain", "temple",
                    "market", "bridge"],
        "อาหาร": ["noodles", "sandwich", "chocolate", "pizza", "dumpling", "omelette", "burger", "pancake",
                  "salad", "sushi"],
    },
    "th": {
        "สัตว์": ["ช้าง", "แมว", "สุนัข", "ม้าลาย", "กระต่าย", "จระเข้", "ยีราฟ", "นกแก้ว", "ปลาโลมา", "เต่า",
                  "หมีแพนด้า", "ลิง"],
        "ผลไม้": ["กล้วย", "มะม่วง", "สับปะรด", "ทุเรียน", "มังคุด", "แตงโม", "ลำไย", "เงาะ", "ส้มโอ", "ฝรั่ง",
                  "มะละกอ"],
        "อาหาร": ["ต้มยำกุ้ง", "ผัดไทย", "ส้มตำ", "ข้าวผัด", "ไก่ทอด", "ลาบหมู", "แกงเขียวหวาน", "ขนมครก",
                  "ข้าวเหนียวมะม่วง", "หมูกรอบ"],
        "สถานที่": ["โรงเรียน", "โรงพยาบาล", "สนามบิน", "ห้องสมุด", "ตลาดนัด", "วัดพระแก้ว", "ภูเขา", "ทะเล",
                    "สวนสาธารณะ", "พิพิธภัณฑ์"],
    },
}
LANG_NAME = {"en": "อังกฤษ", "th": "ไทย"}
_LANG_ALIASES = {"en": "en", "eng": "en", "english": "en", "อังกฤษ": "en", "อิ้ง": "en",
                 "th": "th", "thai": "th", "ไทย": "th"}

EN_FREQ = "etaoinshrdlucmfwypvbgkjqxz"
TH_FREQ = "นรมกวทยลคงบพสดจตหอขปชฟซฎ"

_TH_CONSONANTS = {chr(c) for c in range(0x0E01, 0x0E2F)}          # ก–ฮ
_TH_MARKS = set("ัิีึืุูํ็่้๊๋์ฺ")                                    # สระบน/ล่าง + วรรณยุกต์ (ติดกับพยัญชนะตัวหน้า)

STAGES = [
    "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========",
]

WIN_LINES = ["เก่งมากครับ! ช่วยกันได้ครบเลย 👏", "ยอดเยี่ยมครับ ผมสู้ไม่ได้เลย 🙇", "รอดแล้ว! ทีมเวิร์กดีมากครับ 🎉"]
LOSE_LINES = ["แพ้แล้วครับ 😈 เอาใหม่ไหม?", "คราวนี้ผมชนะ 😎 แต่คำนี้ก็ไม่ง่ายนะครับ", "เกือบแล้วๆ ลองอีกตาไหมครับ?"]


def norm_lang(text: Optional[str]) -> str:
    return _LANG_ALIASES.get((text or "").strip().lower(), "en")


def word_pool(lang: str) -> list[str]:
    return [w for ws in WORDS[lang].values() for w in ws]


def thai_units(word: str) -> list[tuple[str, str, bool]]:
    """แตกคำไทยเป็นหน่วย (ฐาน, เครื่องหมายที่ติดมา, เป็นพยัญชนะไหม) เพื่อซ่อนเฉพาะพยัญชนะและโชว์สระ/วรรณยุกต์เลย"""
    units: list[list] = []
    for ch in word:
        if ch in _TH_CONSONANTS:
            units.append([ch, "", True])
        elif ch in _TH_MARKS and units and units[-1][2]:
            units[-1][1] += ch
        else:
            units.append([ch, "", False])
    return [(a, b, c) for a, b, c in units]


def _pattern(word: str, guessed: set[str], lang: str) -> tuple:
    """สถานะที่ผู้เล่นมองเห็น: ตัวที่เปิดแล้ว/ไม่ต้องซ่อน = ตัวอักษร, ที่ยังซ่อน = None"""
    if lang == "th":
        return tuple(ch if (ch not in _TH_CONSONANTS or ch in guessed) else None for ch in word)
    return tuple(ch if ch in guessed else None for ch in word)


def _targets(word: str, lang: str) -> set[str]:
    if lang == "th":
        return {c for c in word if c in _TH_CONSONANTS}
    return {c for c in word if c.isalpha()}


# ---------------------------------------------------------------- ตรรกะล้วนๆ
class HangmanGame:
    def __init__(self, word: str, lang: str = "en", category: str = ""):
        self.lang = lang if lang in WORDS else "en"
        self.word = word.lower() if self.lang == "en" else word
        self.category = category
        self.targets = _targets(self.word, self.lang)
        self.guessed: set[str] = set()
        self.wrong_letters: list[str] = []
        self.wrong_words: list[str] = []
        self.hints_used = 0
        self.solved = False
        self.gave_up = False

    # ----- สถานะ
    @property
    def lives_left(self) -> int:
        if self.gave_up:
            return 0
        return MAX_WRONG - len(self.wrong_letters) - len(self.wrong_words) - self.hints_used

    @property
    def status(self) -> str:
        if self.solved or self.targets <= self.guessed:
            return "won"
        return "lost" if self.lives_left <= 0 else "playing"

    @property
    def lives_lost(self) -> int:
        return max(0, min(MAX_WRONG, MAX_WRONG - self.lives_left))

    # ----- การทาย
    def normalize_letter(self, text: str) -> Optional[str]:
        t = (text or "").strip()
        if len(t) != 1:
            return None
        if self.lang == "th":
            return t if t in _TH_CONSONANTS else None
        t = t.lower()
        return t if re.fullmatch(r"[a-z]", t) else None

    def guess_letter(self, text: str) -> str:
        """คืน invalid / dup / hit / miss"""
        ch = self.normalize_letter(text)
        if ch is None:
            return "invalid"
        if ch in self.guessed:
            return "dup"
        self.guessed.add(ch)
        if ch in self.targets:
            return "hit"
        self.wrong_letters.append(ch)
        return "miss"

    def guess_word(self, text: str) -> Optional[bool]:
        """ทายทั้งคำ: ถูก -> True (ชนะทันที) / ผิด -> False (เสียหัวใจ 1 ดวง) / ว่างเปล่า -> None"""
        t = re.sub(r"\s+", "", text or "")
        if not t:
            return None
        if self.lang == "en":
            t = t.lower()
        if t == self.word:
            self.solved = True
            self.guessed |= self.targets
            return True
        if t not in self.wrong_words:
            self.wrong_words.append(t)
        return False

    def can_hint(self) -> tuple[bool, str]:
        if self.status != "playing":
            return False, "เกมจบแล้วครับ"
        if self.lives_left <= 1:
            return False, "เหลือหัวใจดวงสุดท้ายแล้ว ขอใบ้ไม่ได้ครับ"
        if len(self.targets - self.guessed) <= 1:
            return False, "เหลือตัวเดียวแล้ว ลองเดาเองเลยครับ"
        return True, ""

    def hint(self, rng: Optional[random.Random] = None) -> Optional[str]:
        ok, _ = self.can_hint()
        if not ok:
            return None
        rng = rng or random
        ch = rng.choice(sorted(self.targets - self.guessed))
        self.guessed.add(ch)
        self.hints_used += 1
        return ch

    # ----- สมองแบ็คลี่: เลือกตัวที่เจอบ่อยสุดในคำที่ยังเป็นไปได้
    def bot_guess(self, pool: Optional[list[str]] = None) -> Optional[str]:
        left = [c for c in (TH_FREQ if self.lang == "th" else EN_FREQ) if c not in self.guessed]
        pool = pool if pool is not None else word_pool(self.lang)
        cur = _pattern(self.word, self.guessed, self.lang)          # สิ่งที่ผู้เล่นเห็น (ไม่แอบดูตัวที่ยังซ่อน)
        cands = [w for w in pool if _pattern(w.lower() if self.lang == "en" else w, self.guessed, self.lang) == cur]
        cnt: Counter = Counter()
        for w in cands:
            w = w.lower() if self.lang == "en" else w
            cnt.update(_targets(w, self.lang) - self.guessed)
        if cnt:
            best = max(cnt.values())
            top = {c for c, n in cnt.items() if n == best}
            for c in left:                                          # เสมอกัน -> ตามลำดับความถี่ภาษา
                if c in top:
                    return c
            return sorted(top)[0]
        return left[0] if left else None

    # ----- แสดงผล
    def display(self) -> str:
        if self.lang == "th":
            parts = []
            for base, marks, is_con in thai_units(self.word):
                parts.append((base if base in self.guessed else "▢") + marks if is_con else base)
            return "\u2009".join(parts)
        return " ".join(c.upper() if c in self.guessed else "_" for c in self.word)

    def reveal(self) -> str:
        return self.word.upper() if self.lang == "en" else self.word


def new_game(lang: str = "en", category: Optional[str] = None, rng: Optional[random.Random] = None) -> HangmanGame:
    rng = rng or random
    lang = norm_lang(lang)
    cats = WORDS[lang]
    if category not in cats:
        category = rng.choice(sorted(cats))
    return HangmanGame(rng.choice(cats[category]), lang, category)


# ---------------------------------------------------------------- Discord
_active: dict[int, "HangmanView"] = {}


def get_active(channel_id: int) -> Optional["HangmanView"]:
    return _active.get(channel_id)


class _GuessModal(discord.ui.Modal):
    def __init__(self, hv: "HangmanView", kind: str):
        super().__init__(title="ทายพยัญชนะ" if kind == "letter" else "ทายทั้งคำ", timeout=120)
        self.hv, self.kind = hv, kind
        self.box = discord.ui.TextInput(
            label="พิมพ์พยัญชนะไทย 1 ตัว" if kind == "letter" else "พิมพ์คำที่คิดว่าใช่",
            min_length=1, max_length=1 if kind == "letter" else 40, required=True)
        self.add_item(self.box)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = str(self.box.value)
        if self.kind == "letter":
            await self.hv.do_letter(interaction, text)
        else:
            await self.hv.do_word(interaction, text)


class HangmanView(discord.ui.View):
    def __init__(self, game: HangmanGame, host, channel_id: int):
        super().__init__(timeout=IDLE_TIMEOUT)
        self.game, self.host, self.channel_id = game, host, channel_id
        self.message: Optional[discord.Message] = None
        self.credit: Counter = Counter()           # user_id -> จำนวนตัวที่ทายถูก/ใบ้ (ไว้ชมตอนจบ)
        self.names: dict[int, str] = {}
        self.build()

    # ----- ข้อความ
    def render(self, note: str = "") -> str:
        g = self.game
        hearts = "❤️" * max(g.lives_left, 0) + "🖤" * (MAX_WRONG - max(g.lives_left, 0))
        word = f"`{g.display()}`" if g.lang == "en" else f"**{g.display()}**"
        lines = [f"🪢 **Hangman** · หมวด: **{g.category}** · ภาษา{LANG_NAME[g.lang]}",
                 f"```\n{STAGES[g.lives_lost]}\n```", f"คำลับ: {word}" + (f"  ({len(g.word)} ตัว)" if g.lang == "en" else ""),
                 f"หัวใจ: {hearts}"]
        wrong = list(g.wrong_letters) + [f"“{w}”" for w in g.wrong_words]
        if wrong:
            lines.append("❌ ทายผิด: " + ", ".join(x.upper() if g.lang == "en" else x for x in wrong))
        if note:
            lines.append(note)
        if g.status == "won":
            helpers = ", ".join(f"{self.names[u]} ({n})" for u, n in self.credit.most_common()) or "-"
            lines.append(f"🏆 **ชนะ!** คำคือ **{g.reveal()}** — {random.choice(WIN_LINES)}\nผู้ช่วยกันทาย: {helpers}")
        elif g.status == "lost":
            lines.append(f"💀 **แพ้แล้ว** คำคือ **{g.reveal()}** — {random.choice(LOSE_LINES)}")
        return "\n".join(lines)

    # ----- ปุ่ม/เมนู (สร้างใหม่ทุกครั้งที่สถานะเปลี่ยน เพื่อตัดตัวอักษรที่ทายไปแล้วออกจากเมนู)
    def build(self) -> None:
        self.clear_items()
        g = self.game
        if g.status != "playing":
            return
        if g.lang == "en":
            halves = ((("abcdefghijklm", "เลือกตัวอักษร A–M"), 0), (("nopqrstuvwxyz", "เลือกตัวอักษร N–Z"), 1))
            for (letters, ph), row in halves:
                opts = [c for c in letters if c not in g.guessed]
                if not opts:
                    continue
                sel = discord.ui.Select(placeholder=ph, row=row,
                                        options=[discord.SelectOption(label=c.upper(), value=c) for c in opts])
                sel.callback = self._select_cb(sel)
                self.add_item(sel)
        else:
            self._button("ทายพยัญชนะ", "🔤", discord.ButtonStyle.primary, 0, self._letter_btn)
        self._button("ทายทั้งคำ", "💬", discord.ButtonStyle.success, 2, self._word_btn)
        self._button("ใบ้ (-1 หัวใจ)", "💡", discord.ButtonStyle.secondary, 2, self._hint_btn)
        self._button("ให้แบ็คลี่เดา", "🤖", discord.ButtonStyle.secondary, 2, self._bot_btn)
        self._button("จบเกม", "🛑", discord.ButtonStyle.danger, 2, self._end_btn)

    def _button(self, label, emoji, style, row, cb) -> None:
        b = discord.ui.Button(label=label, emoji=emoji, style=style, row=row)
        b.callback = cb
        self.add_item(b)

    def _select_cb(self, sel):
        async def cb(interaction: discord.Interaction):
            await self.do_letter(interaction, sel.values[0])
        return cb

    # ----- ตัวช่วย
    def _q(self, event: str, chance: float = 1.0, **fmt) -> str:
        return banter.tag(banter.say("hangman", event, chance=chance, **fmt))

    def _who(self, user) -> str:
        self.names[user.id] = user.display_name
        return user.display_name

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

    # ----- การกระทำ
    async def do_letter(self, interaction, text: str) -> None:
        if await self._closed(interaction):
            return
        res = self.game.guess_letter(text)
        if res == "invalid":
            hint = "พิมพ์พยัญชนะไทย 1 ตัว (ก–ฮ)" if self.game.lang == "th" else "เลือกตัวอักษร a–z"
            return await interaction.response.send_message(f"ใช้ไม่ได้ครับ {hint}", ephemeral=True)
        if res == "dup":
            return await interaction.response.send_message("ตัวนี้ถูกทายไปแล้วครับ", ephemeral=True)
        who, ch = self._who(interaction.user), text.strip().upper() if self.game.lang == "en" else text.strip()
        if res == "hit":
            self.credit[interaction.user.id] += 1
            note = f"✅ {who} ทาย **{ch}** ถูก!" + self._q("hit", 0.5, name=who)
        else:
            note = f"❌ {who} ทาย **{ch}** ไม่มีในคำนี้" + (
                self._q("low") if self.game.lives_left == 1 else self._q("miss", 0.6, name=who))
        await self._update(interaction, note)

    async def do_word(self, interaction, text: str) -> None:
        if await self._closed(interaction):
            return
        res = self.game.guess_word(text)
        if res is None:
            return await interaction.response.send_message("ยังไม่ได้พิมพ์คำเลยครับ", ephemeral=True)
        who = self._who(interaction.user)
        if res:
            self.credit[interaction.user.id] += 1
            return await self._update(interaction, f"🎯 {who} ทายทั้งคำถูก!")
        await self._update(interaction, f"❌ {who} ทายว่า “{text.strip()}” ไม่ใช่ครับ (เสียหัวใจ 1 ดวง)"
                           + (self._q("low") if self.game.lives_left == 1 else self._q("wrong_word", 0.7, name=who)))

    async def _letter_btn(self, interaction):
        if not await self._closed(interaction):
            await interaction.response.send_modal(_GuessModal(self, "letter"))

    async def _word_btn(self, interaction):
        if not await self._closed(interaction):
            await interaction.response.send_modal(_GuessModal(self, "word"))

    async def _hint_btn(self, interaction):
        if await self._closed(interaction):
            return
        ok, why = self.game.can_hint()
        if not ok:
            return await interaction.response.send_message(why, ephemeral=True)
        ch = self.game.hint()
        who = self._who(interaction.user)
        self.credit[interaction.user.id] += 1
        await self._update(interaction, f"💡 {who} ขอใบ้ → เปิด **{ch.upper() if self.game.lang == 'en' else ch}** ให้ (เสียหัวใจ 1 ดวง)" + self._q("hint", 0.7, name=who))

    async def _bot_btn(self, interaction):
        if await self._closed(interaction):
            return
        ch = self.game.bot_guess()
        if ch is None:
            return await interaction.response.send_message("ผมคิดไม่ออกเลยครับ 😅", ephemeral=True)
        res = self.game.guess_letter(ch)
        shown = ch.upper() if self.game.lang == "en" else ch
        note = (f"🤖 {BOT_NAME} เดา **{shown}** → ถูก! 😎" if res == "hit"
                else f"🤖 {BOT_NAME} เดา **{shown}** → พลาดครับ 🙈")
        await self._update(interaction, note)

    async def _end_btn(self, interaction):
        perms = getattr(interaction.user, "guild_permissions", None)
        if interaction.user.id != self.host.id and not (perms and perms.manage_messages):
            return await interaction.response.send_message("❌ เฉพาะคนเปิดเกมหรือแอดมินที่จบเกมได้ครับ", ephemeral=True)
        self.game.gave_up = True                                                  # หัวใจเป็น 0 -> สถานะ lost + เฉลยคำ
        await self._update(interaction, f"🛑 {interaction.user.display_name} จบเกม")

    async def on_timeout(self) -> None:
        _active.pop(self.channel_id, None)
        if self.game.status == "playing" and self.message is not None:
            self.clear_items()
            try:
                await self.message.edit(
                    content=self.render(f"⌛ หมดเวลาแล้วครับ (เงียบนานเกิน {IDLE_TIMEOUT // 60} นาที) คำคือ **{self.game.reveal()}**"),
                    view=self)
            except Exception:
                pass


async def start_hangman(send: Callable[..., Awaitable[discord.Message]], channel_id: int, host,
                        lang: str = "en", category: Optional[str] = None) -> Optional[HangmanView]:
    """เปิดเกม Hangman ในช่อง (หนึ่งช่องต่อหนึ่งเกม) — คืน None ถ้าช่องนี้มีเกมค้างอยู่"""
    if channel_id in _active:
        await send("ช่องนี้มี Hangman เล่นอยู่แล้วครับ เล่นให้จบก่อน หรือกด 🛑 จบเกม")
        return None
    view = HangmanView(new_game(lang, category), host, channel_id)
    _active[channel_id] = view
    try:
        view.message = await send(content=view.render(
            "ทุกคนในช่องช่วยกันทายได้เลยครับ!" + view._q("start", category=view.game.category)), view=view)
    except Exception:
        _active.pop(channel_id, None)
        raise
    return view


async def force_end(channel_id: int, by_name: str = "") -> bool:
    """จบเกมที่ค้างในช่องทันที (ใช้กับ /hangman_end) — คืน False ถ้าช่องนี้ไม่มีเกมเปิดอยู่"""
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
