"""bagley/commands/listen.py — ให้แบ็คลี่ "ฟังเสียงในห้อง Discord โดยตรง" (ไม่ต้องใช้แอพ ใช้ได้บนมือถือ)

ลำดับ: รับเสียง -> ถอดรหัส DAVE -> ตัดประโยคต่อคน -> Google STT -> จับชื่อเรียก/คำสั่งที่ "คนนั้น" สอนไว้
  - พูดชื่อ (เช่น "แบ็คลี่") -> แบ็คลี่ขานรับ "ครับ/ค้าบ/ครับผม" (สุ่ม) -> พูดคำสั่งต่อภายใน 8 วินาที  หรือพูดต่อกันเลย "แบ็คลี่ เปิดเพลง ..."
  - คำที่สอนไว้ตรง -> สั่งคำสั่งนั้นทันที (รองรับ "ชื่อต่อท้าย" เช่น /kick ชื่อ, /play ชื่อเพลง)
  - ไม่ตรงคำที่สอน -> ส่งเข้าสมอง/ระบบคำสั่งเดิมของบอทเหมือนพิมพ์ในแชท (เปิดเพลง ฯลฯ ใช้ได้ทันที)

คำสั่ง (ผู้ใช้ที่อยู่ในรายชื่ออนุญาตเท่านั้น):
  /listen on|off|status|debug      เปิด/ปิดการฟัง, ดูสถานะ, เปิด-ปิดการโชว์ข้อความที่ได้ยิน
  /voice_teach command:/tts has_arg   สอนคำเรียกคำสั่ง (พูด 5 ครั้ง -> ติ๊กเลือกคำที่ถูก -> บันทึก)
  /voice_teach_wake                   สอนวิธีเรียกชื่อแบ็คลี่ของตัวเอง (พูดชื่อ 5 ครั้ง)
  /voice_list                          ดูรายการที่สอนไว้ของตัวเอง + เลือกลบ
เสียงของคนที่ไม่อยู่ในรายชื่ออนุญาตจะถูกทิ้งก่อนถอดรหัสทันที
"""
from __future__ import annotations

import asyncio
import importlib.metadata as _md
import io
import logging
import time

import discord
from discord.ext import commands

from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.voice import ack, allowlist, matching, teach_store
from bagley.voice.client import BagleyVoiceClient, connect_voice
from bagley.voice.mixer import get_mixer
from bagley.voice.segmenter import Segmenter, Utterance, make_beep_pcm

try:
    from discord.ext import voice_recv
    HAVE_RECV = True
except Exception:   # ยังไม่ได้ติดตั้ง discord-ext-voice-recv
    voice_recv = None
    HAVE_RECV = False

class _QuietRtcp(logging.Filter):
    """ซ่อนข้อความ INFO "Received unexpected rtcp packet" (SenderReport ที่ Discord ส่งมาเป็นระยะ ไม่ใช่ error)
    ที่ทำให้หน้าต่าง command prompt รกจนมองไม่เห็นข้อความสำคัญ — ข้อความอื่นของไลบรารีนี้ยังแสดงตามปกติ"""
    def filter(self, record: logging.LogRecord) -> bool:
        return "unexpected rtcp packet" not in record.getMessage()


logging.getLogger("discord.ext.voice_recv.reader").addFilter(_QuietRtcp())


STT_LANGUAGE = "th-TH"
TEACH_ROUNDS = 5
TEACH_IDLE_SEC = 90          # เงียบเกินนี้ระหว่างสอน = ยกเลิก
ARMED_SEC = 8                # พูดชื่อแล้วต้องพูดคำสั่งต่อภายในกี่วินาที
OPUS_SILENCE = b"\xf8\xff\xfe"
DAVE_MARKER = b"\xfa\xfa"          # เฟรมที่ถูกเข้ารหัส DAVE จะลงท้ายด้วย 0xFAFA
_BEEP_PCM = make_beep_pcm()

_sessions: dict[int, "_Session"] = {}


def _ver(pkg: str) -> str:
    try:
        return _md.version(pkg)
    except Exception:
        return "ไม่พบ"


def _get_dave_session(vc):
    """discord.py 2.7+ เก็บ DAVE session ไว้ที่ voice_client._connection.dave_session"""
    return getattr(getattr(vc, "_connection", None), "dave_session", None)


def _dave_decrypt(vc, user_id: int, frame: bytes):
    """คืน (opus_ที่ถอดแล้ว, สถานะ) สถานะ: plain=ไม่ได้เข้ารหัส / dave=ถอดสำเร็จ / fail=ถอดไม่ได้"""
    if not frame.endswith(DAVE_MARKER):
        return frame, "plain"
    sess = _get_dave_session(vc)
    if sess is None:
        return None, "fail"
    try:
        import davey
        return sess.decrypt(user_id, davey.MediaType.audio, frame), "dave"
    except Exception:
        return None, "fail"


class _Session:
    def __init__(self, guild_id: int, text_channel, vc):
        self.guild_id = guild_id
        self.text_channel = text_channel
        self.vc = vc
        self.segmenter = Segmenter()
        self.stats = {"packets": 0, "plain": 0, "dave": 0, "fail": 0, "opus_err": 0,
                      "dropped_other": 0, "utterances": 0, "stt_empty": 0, "stt_error": 0}
        self.started = time.monotonic()
        self.last_audio = 0.0
        self.pump_task: asyncio.Task | None = None
        self.sink = None
        self.debug = False                       # โชว์ข้อความที่ได้ยินทุกประโยคในแชท
        self.restarts = 0                        # จำนวนครั้งที่ตัวฟังหลุดแล้วถูกต่อใหม่อัตโนมัติ
        self.warned_plain = False                # เตือนเรื่อง client ที่ฟังไม่ได้ไปแล้วหรือยัง
        self.armed: dict[int, float] = {}        # uid -> เวลาหมดอายุหลังพูดชื่อ (รอรับคำสั่งถัดไป)
        self.teaching: dict[int, "_Teach"] = {}  # uid -> สถานะกำลังสอน


class _Teach:
    def __init__(self, kind: str, send: str = "", has_arg: bool = False):
        self.kind = kind            # "wake" | "cmd"
        self.send = send
        self.has_arg = has_arg
        self.rounds: list[list[str]] = []
        self.deadline = time.monotonic() + TEACH_IDLE_SEC


if HAVE_RECV:
    class _ListenSink(voice_recv.AudioSink):
        """รับ opus ดิบ (wants_opus) -> ถอด DAVE เอง -> ถอดรหัส opus เอง -> ส่งให้ตัวตัดประโยค
        (ทำแบบนี้เพราะ discord-ext-voice-recv ยังไม่ถอด DAVE ให้ — ไม่ต้องแก้/แพตช์ตัวไลบรารี)"""

        def __init__(self, session: _Session):
            super().__init__()
            self.s = session
            self._decoders: dict[int, discord.opus.Decoder] = {}

        def wants_opus(self) -> bool:
            return True

        def write(self, user, data):
            s = self.s
            if user is None or getattr(user, "bot", False):
                return
            if not allowlist.is_allowed(user.id):      # คนนอกรายชื่อทิ้งทันที ไม่ถอดรหัส ไม่ส่งไป STT (รายชื่อเพิ่ม/ลบได้ด้วย /voice_user_add|remove)
                s.stats["dropped_other"] += 1
                return
            frame = getattr(data, "opus", None)
            if not frame or frame == OPUS_SILENCE:
                return
            s.stats["packets"] += 1
            payload, kind = _dave_decrypt(s.vc, user.id, bytes(frame))
            s.stats[kind] += 1
            if payload is None or payload == OPUS_SILENCE:
                return
            dec = self._decoders.get(user.id)
            if dec is None:
                dec = self._decoders[user.id] = discord.opus.Decoder()
            try:
                pcm = dec.decode(payload, fec=False)
            except Exception:
                s.stats["opus_err"] += 1
                return
            s.last_audio = time.monotonic()
            s.segmenter.feed(user.id, pcm)

        def cleanup(self):
            self._decoders.clear()


def _stt_sync(pcm16k: bytes):
    """Google STT แบบเดียวกับแอพ คืน (รายการคำที่ฟังได้เรียงตามความมั่นใจ, ข้อความ error หรือ None)"""
    try:
        import speech_recognition as sr
    except Exception as e:
        return [], f"ไม่พบ SpeechRecognition ({e})"
    try:
        r = sr.Recognizer()
        res = r.recognize_google(sr.AudioData(pcm16k, 16000, 2), language=STT_LANGUAGE, show_all=True)
        alts = []
        if isinstance(res, dict):
            alts = [a.get("transcript", "").strip() for a in res.get("alternative", []) if a.get("transcript")]
        return alts, None
    except Exception as e:   # sr.UnknownValueError / RequestError ฯลฯ
        name = type(e).__name__
        return [], (None if name == "UnknownValueError" else f"{name}: {e}")


async def _play_pcm(vc, pcm: bytes) -> bool:
    """เล่น PCM 48kHz สเตอริโอเข้าห้อง คืน True ถ้าเล่นได้ (ถ้ากำลังเล่นเสียงเดี่ยวอยู่ จะเล่นซ้อนไม่ได้ -> คืน False)"""
    try:
        if vc is not None and vc.is_connected():
            mixer = get_mixer(vc)
            if mixer is not None:                       # กำลังเปิดเพลง -> เล่นซ้อนบนเพลง (หรี่เพลงชั่วคราว)
                mixer.add_overlay(discord.PCMAudio(io.BytesIO(pcm)))
                return True
            if not vc.is_playing():
                vc.play(discord.PCMAudio(io.BytesIO(pcm)))
                return True
    except Exception as e:
        print(f"⚠️ [Listen] เล่นเสียงไม่ได้: {e}")
    return False


async def _play_beep(vc) -> bool:
    """เล่นเสียงติ๊ดๆ (ใช้ตอนสอนคำ / สำรองตอนไฟล์เสียงขานรับยังไม่พร้อม)"""
    return await _play_pcm(vc, _BEEP_PCM)


async def _play_ack(vc) -> bool:
    """ขานรับตอนได้ยินชื่อ: สุ่ม ครับ/ค้าบ/ครับผม จากไฟล์ถาวรที่โหลดค้างไว้แล้ว (ถ้ายังไม่พร้อม -> ติ๊ดแทนแล้วโหลดเบื้องหลัง)"""
    pcm = ack.pick_pcm()
    if pcm is None:
        asyncio.create_task(ack.ensure_loaded())
        return await _play_beep(vc)
    return await _play_pcm(vc, pcm)


async def _ack_wake(s: "_Session", text: str | None) -> None:
    """ตอบรับว่าได้ยินชื่อแล้ว: พูด ครับ/ค้าบ/ครับผม ถ้าเล่นเสียงไม่ได้ (เช่นกำลังพูดอยู่) ให้ส่งข้อความสั้นๆ แทน"""
    if await _play_ack(s.vc) or not text:
        return
    try:
        await s.text_channel.send(text, delete_after=8)
    except Exception:
        pass


def _fake_message(s: _Session, member: discord.Member, text: str):
    from bagley.services.voice_relay import VoiceRelayMessage   # import ตอนใช้ กัน import วนกัน
    return VoiceRelayMessage(content=text, author=member, guild=member.guild, channel=s.text_channel)


async def _run_natural(s: _Session, member: discord.Member, text: str) -> None:
    """ส่งเข้าระบบเดิมของบอทเหมือนพิมพ์ในแชท (voice_keywords / AI router / คุยเล่น)"""
    from bagley.events.message import on_message
    try:
        await on_message(_fake_message(s, member, text))
    except Exception as e:
        print(f"⚠️ [Listen] ส่งเข้า on_message ไม่สำเร็จ: {e}")


async def _run_taught(s: _Session, member: discord.Member, text: str) -> None:
    """รันคำสั่งที่สอนไว้ เช่น '/kick สมชาย' -> เรียก hybrid command ตรงๆ (แกะ/หาตัวสมาชิกแบบเดียวกับ AI router)"""
    from bagley.ai.router import _PARAM_RESOLVERS
    from bagley.features.members import find_member_by_name
    name, _, rest = text.lstrip("/!").partition(" ")
    rest = rest.strip()
    cmd = bot.get_command(name.strip())
    msg = _fake_message(s, member, text)
    if cmd is None:
        await s.text_channel.send(f"❌ ไม่พบคำสั่ง `/{name}` ในบอทครับ (ลบแล้วสอนใหม่ได้ที่ /voice_list)")
        return
    params = list(cmd.clean_params.items())
    raw: dict[str, str] = {}
    if params and rest:
        if len(params) == 1:
            raw[params[0][0]] = rest
        else:
            for (pname, _p), val in zip(params, rest.split(None, len(params) - 1)):
                raw[pname] = val
    kwargs = {}
    for pname, param in params:
        if pname not in raw:
            if param.default is param.empty:
                await s.text_channel.send(f"❌ `/{cmd.name}` ต้องมีข้อมูลต่อท้ายด้วยครับ (พูดชื่อ/ค่าต่อจากคำสั่ง)")
                return
            continue
        resolver = _PARAM_RESOLVERS.get(param.annotation)
        if resolver:
            resolved = await resolver(msg, raw[pname], find_member_by_name)
            if resolved is None and param.default is param.empty:
                await s.text_channel.send(f"❌ แบ็คลี่หา '{raw[pname]}' ไม่เจอเลยครับ")
                return
            kwargs[pname] = resolved
        else:
            kwargs[pname] = raw[pname]
    try:
        ctx = await bot.get_context(msg)
        if not await cmd.can_run(ctx):            # ตรวจสิทธิ์/เช็กของคำสั่งก่อนเสมอ (ctx.invoke ข้ามเช็กเอง)
            await s.text_channel.send(f"🚫 {member.display_name} ไม่มีสิทธิ์ใช้ `/{cmd.name}` ครับ")
            return
        print(f"🎙️ [Listen] {member.display_name} -> /{cmd.name} {kwargs}")
        await ctx.invoke(cmd, **kwargs)
    except Exception as e:
        print(f"⚠️ [Listen] /{cmd.name} ทำงานผิดพลาด: {e}")
        await s.text_channel.send(f"⚠️ /{cmd.name} ทำงานไม่สำเร็จ: {type(e).__name__}")


async def _dispatch(s: _Session, member: discord.Member, cmd_alts: list) -> None:
    """ข้อความหลังเรียกชื่อแล้ว: ลองจับคำที่คนนี้สอนไว้ก่อน ไม่ตรงค่อยส่งเข้าระบบเดิม"""
    user = teach_store.get_user(member.id)
    hit = matching.match_command(cmd_alts, user["commands"])
    if hit:
        if s.debug:
            await s.text_channel.send(f"🎯 ตรงคำที่สอน “{hit['phrase']}” ({hit['score']:.2f}) -> `{hit['text']}`")
        await _run_taught(s, member, hit["text"])
    else:
        await _run_natural(s, member, cmd_alts[0])


async def _teach_feed(s: _Session, member: discord.Member, t: _Teach, alts: list, err) -> None:
    t.deadline = time.monotonic() + TEACH_IDLE_SEC
    if err or not alts:
        await s.text_channel.send(f"🎙️ {member.display_name}: ฟังไม่ออก ลองพูดใหม่อีกครั้งนะครับ")
        return
    t.rounds.append(alts)
    n = len(t.rounds)
    if n < TEACH_ROUNDS:
        await s.text_channel.send(f"✅ รอบ {n}/{TEACH_ROUNDS} ได้ยินเป็น: **{alts[0]}**  (พูดอีกครั้งได้เลย)")
        await _play_beep(s.vc)
        return
    s.teaching.pop(member.id, None)
    # รวมคำที่ได้ยินทั้งหมด เรียงตามจำนวนครั้งที่เจอ  ติ๊กไว้ให้ก่อนเฉพาะคำอันดับ 1 ของแต่ละรอบ
    from collections import Counter
    cnt = Counter(a for r in t.rounds for a in r)
    first_seen: dict[str, int] = {}
    for r in t.rounds:
        for a in r:
            first_seen.setdefault(a, len(first_seen))
    options = sorted(cnt, key=lambda a: (-cnt[a], first_seen[a]))[:25]
    top1 = {r[0] for r in t.rounds}
    default_idx = {i for i, a in enumerate(options) if a in top1}
    label = "ชื่อเรียกแบ็คลี่" if t.kind == "wake" else f"คำสั่ง {t.send}"
    view = _PickView(member.id, t, options, default_idx)
    await s.text_channel.send(
        f"📝 ครบ {TEACH_ROUNDS} รอบแล้ว! เลือก **เฉพาะคำที่ถูกต้อง** สำหรับ {label} แล้วกด “บันทึก”\n"
        f"(ติ๊กไว้ให้แล้วคือคำที่ได้ยินเป็นอันดับ 1 ในแต่ละรอบ — เอาคำที่ไม่ใช่ออกได้ครับ)", view=view)


class _PickView(discord.ui.View):
    def __init__(self, owner_id: int, t: _Teach, options: list, default_idx: set):
        super().__init__(timeout=300)
        self.owner_id, self.t, self.options = owner_id, t, options
        self.selected = set(default_idx)
        sel = discord.ui.Select(
            placeholder="เลือกคำที่ถูกต้อง", min_values=1, max_values=len(options),
            options=[discord.SelectOption(label=a[:100], value=str(i), default=(i in default_idx))
                     for i, a in enumerate(options)])
        sel.callback = self._on_select
        self._sel = sel
        self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("ปุ่มนี้ของคนที่กำลังสอนครับ", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        self.selected = {int(v) for v in self._sel.values}
        await interaction.response.defer()

    @discord.ui.button(label="บันทึก", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        phrases = [self.options[i] for i in sorted(self.selected)]
        if not phrases:
            await interaction.response.send_message("ต้องเลือกอย่างน้อย 1 คำครับ", ephemeral=True)
            return
        t = self.t
        added, skipped = await asyncio.get_running_loop().run_in_executor(
            None, lambda: teach_store.save_teach(self.owner_id, t.kind, phrases, t.send, t.has_arg))
        what = "ชื่อเรียกแบ็คลี่" if t.kind == "wake" else f"`{t.send}`" + (" (มีชื่อต่อท้าย)" if t.has_arg else "")
        msg = f"✅ บันทึก {what} แล้วครับ (เพิ่ม {added} วลี) — ใช้งานได้ทันที ดูรายการที่ /voice_list"
        if skipped:
            msg += "\nข้าม: " + ", ".join(skipped)
        self.stop()
        await interaction.response.edit_message(content=msg, view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="ยกเลิกการสอนแล้วครับ", view=None)


class _DeleteView(discord.ui.View):
    def __init__(self, owner_id: int, user: dict):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.selected: set[str] = set()
        opts = []
        if user["wake"]:
            opts.append(discord.SelectOption(label="ชื่อเรียกแบ็คลี่ (ทั้งหมด)", value="wake"))
        for i, c in enumerate(user["commands"][:24]):
            opts.append(discord.SelectOption(label=f"{i + 1}. {c['send']}"[:100], value=f"c{i}"))
        self._sel = discord.ui.Select(placeholder="เลือกรายการที่จะลบ", min_values=1,
                                      max_values=len(opts), options=opts)
        self._sel.callback = self._on_select
        self.add_item(self._sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("เมนูนี้ของเจ้าของรายการครับ", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        self.selected = set(self._sel.values)
        await interaction.response.defer()

    @discord.ui.button(label="ลบที่เลือก", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            await interaction.response.send_message("เลือกรายการก่อนครับ", ephemeral=True)
            return
        idx = [int(v[1:]) for v in self.selected if v.startswith("c")]
        removed = teach_store.delete_items(self.owner_id, idx, wake_all="wake" in self.selected)
        self.stop()
        await interaction.response.edit_message(
            content="🗑️ ลบแล้ว: " + (", ".join(removed) if removed else "(ไม่มีอะไรถูกลบ)"), view=None)


async def _handle_utterance(s: _Session, utt: Utterance) -> None:
    s.stats["utterances"] += 1
    loop = asyncio.get_running_loop()
    alts, err = await loop.run_in_executor(None, _stt_sync, utt.pcm16k)
    member = s.text_channel.guild.get_member(utt.user_id)
    if member is None or not allowlist.is_allowed(utt.user_id):   # เช็กซ้ำ: อาจถูกลบออกระหว่างรอ STT
        return
    now = time.monotonic()

    # ✏️ กำลังสอนอยู่ -> เก็บเป็นรอบสอน (ไม่เอาไปตีความเป็นคำสั่ง)
    t = s.teaching.get(member.id)
    if t:
        await _teach_feed(s, member, t, alts, err)
        return

    if err:
        s.stats["stt_error"] += 1
        if s.debug:
            await s.text_channel.send(f"⚠️ STT ผิดพลาด ({member.display_name}): {err}")
        return
    if not alts:
        s.stats["stt_empty"] += 1
        if s.debug:
            await s.text_channel.send(f"🎙️ {member.display_name} ({utt.duration:.1f}s): _(ฟังไม่ออก)_")
        return
    if s.debug:
        line = f"🎙️ **{member.display_name}** ({utt.duration:.1f}s): {alts[0]}"
        if len(alts) > 1:
            line += "\n└ ตัวเลือกอื่น: " + " | ".join(alts[1:4])
        await s.text_channel.send(line)

    user = teach_store.get_user(member.id)
    wake_phrases = list(matching.DEFAULT_WAKE) + user["wake"]

    if s.armed.pop(member.id, 0) > now:
        # พูดชื่อไปแล้วก่อนหน้านี้ -> ประโยคนี้คือคำสั่ง (ถ้าพูดชื่อซ้ำนำหน้าอีกก็ตัดทิ้ง)
        w = matching.check_wake(alts, wake_phrases)
        cmd_alts = w[1] if (w and w[0] == "with") else alts
        await _dispatch(s, member, cmd_alts)
        return

    w = matching.check_wake(alts, wake_phrases)
    if w is None:
        return                                    # ไม่ได้เรียกแบ็คลี่ -> เมิน (ไม่เก็บ ไม่ตอบ)
    kind, rems = w
    if kind == "alone":
        s.armed[member.id] = now + ARMED_SEC       # ติ๊ดๆ แล้วรอคำสั่งถัดไป
        await _ack_wake(s, f"👂 {member.display_name}: ได้ยินแล้วครับ (กำลังพูดอยู่เลยไม่ขานรับด้วยเสียง) — สั่งต่อได้เลยภายใน {ARMED_SEC} วิ")
    else:
        await _ack_wake(s, None)
        await _dispatch(s, member, rems)


async def _safe_handle(s: _Session, utt: Utterance) -> None:
    try:
        await _handle_utterance(s, utt)
    except Exception as e:                      # กันงานพังเงียบ (เดิมถ้า error ตรงนี้จะไม่มีร่องรอยเลย)
        print(f"⚠️ [Listen] ประมวลผลประโยคไม่สำเร็จ: {type(e).__name__}: {e}")


def _rebind(s: _Session) -> bool:
    """ผูกเซสชันกับ voice client ปัจจุบันของกิลด์ และ \"ต่อการฟังใหม่\" ถ้ามันหลุด คืน True ถ้าตอนนี้ฟังอยู่

    การฟังหลุดได้จาก: vc.stop() ของไลบรารีเก่า, บอทย้าย/ออก-เข้าห้อง, reader พังเอง, ถูกสร้าง client ใหม่
    (เซสชันเดิมจะยังนึกว่าฟังอยู่ทั้งที่หูดับ) -> ตรวจทุกไม่กี่วินาทีและตอนเริ่มสอน แล้วต่อให้ใหม่ทันที
    """
    vc = s.text_channel.guild.voice_client
    s.vc = vc
    if vc is None or not vc.is_connected():
        return False
    if not isinstance(vc, BagleyVoiceClient):
        return False                            # client ธรรมดารับเสียงไม่ได้ ต้องให้ /listen on เข้าใหม่
    try:
        if vc.is_listening() and vc.sink is s.sink:
            return True
        if vc.is_listening():
            vc.stop_listening()
        s.segmenter.clear()
        s.sink = _ListenSink(s)
        vc.listen(s.sink)
        s.restarts += 1
        print(f"🔁 [Listen] ตัวฟังหลุด -> ต่อการฟังใหม่ให้แล้ว (ครั้งที่ {s.restarts}) กิลด์ {s.guild_id}")
        return True
    except Exception as e:
        print(f"⚠️ [Listen] ต่อการฟังใหม่ไม่สำเร็จ: {type(e).__name__}: {e}")
        return False


async def _pump(s: _Session) -> None:
    tick = 0
    while True:
        await asyncio.sleep(0.15)
        tick += 1
        if tick % 14 == 0:                       # ~ทุก 2 วินาที: เช็กว่ายังฟังอยู่ไหม
            try:
                ok = _rebind(s)
                vc = s.vc
                if (not ok and vc is not None and vc.is_connected()
                        and not isinstance(vc, BagleyVoiceClient) and not s.warned_plain):
                    s.warned_plain = True
                    await s.text_channel.send(
                        "⚠️ ตอนนี้บอทอยู่ในห้องด้วยการเชื่อมต่อแบบที่ฟังเสียงไม่ได้ — พิมพ์ `/listen on` อีกครั้งเพื่อให้กลับมาฟัง "
                        "(เพลงที่เล่นอยู่จะสะดุดครั้งหนึ่ง)")
                elif ok:
                    s.warned_plain = False
            except Exception as e:
                print(f"⚠️ [Listen] watchdog error: {type(e).__name__}: {e}")
        for utt in s.segmenter.flush_due():
            asyncio.create_task(_safe_handle(s, utt))
        now = time.monotonic()
        for uid, t in list(s.teaching.items()):
            if now > t.deadline:
                s.teaching.pop(uid, None)
                asyncio.create_task(s.text_channel.send(f"⌛ <@{uid}> เงียบนานเกินไป ยกเลิกการสอนให้แล้วครับ"))


def _stop_session(guild_id: int) -> bool:
    s = _sessions.pop(guild_id, None)
    if not s:
        return False
    if s.pump_task:
        s.pump_task.cancel()
    try:
        if getattr(s.vc, "is_listening", lambda: False)():
            s.vc.stop_listening()
    except Exception:
        pass
    return True


async def _start_session(ctx: commands.Context) -> str | None:
    """คืนข้อความ error ถ้าเริ่มไม่ได้, None ถ้าสำเร็จ"""
    if not HAVE_RECV:
        return "ยังไม่ได้ติดตั้ง `discord-ext-voice-recv` ครับ (pip install -r requirements.txt)"
    if not ctx.author.voice or not ctx.author.voice.channel:
        return "เข้าห้องเสียงก่อนนะครับ แล้วค่อยสั่ง"
    channel = ctx.author.voice.channel
    guild = ctx.guild
    _stop_session(guild.id)

    vc = guild.voice_client
    if vc is not None and not isinstance(vc, BagleyVoiceClient):
        # ตัวที่เข้าห้องไว้เดิมรับเสียงไม่ได้ (หรือเป็นตัวเก่าที่ stop() แล้วหูดับ) ต้องตัดแล้วเข้าใหม่ (เพลงที่เล่นอยู่จะหยุด)
        await vc.disconnect(force=True)
        await asyncio.sleep(1.0)
        vc = None
    if vc is None:
        vc = await connect_voice(channel)
    elif vc.channel != channel:
        await vc.move_to(channel)

    s = _Session(guild.id, ctx.channel, vc)
    s.sink = _ListenSink(s)
    vc.listen(s.sink)
    s.pump_task = asyncio.create_task(_pump(s))
    _sessions[guild.id] = s
    return None


def _status_text(guild: discord.Guild) -> str:
    s = _sessions.get(guild.id)
    lines = [
        "📋 **สถานะระบบฟังเสียง (ทดสอบ)**",
        f"• discord.py {_ver('discord.py')} | voice-recv {_ver('discord-ext-voice-recv')} | "
        f"davey {_ver('davey')} | SpeechRecognition {_ver('SpeechRecognition')}",
    ]
    vc = guild.voice_client
    if vc is None:
        lines.append("• บอทยังไม่ได้อยู่ในห้องเสียง")
    else:
        lines.append(f"• DAVE session: {'พบ' if _get_dave_session(vc) is not None else 'ไม่พบ (ถ้าไม่ใช่ discord.py 2.7+ จะถอดเสียงไม่ได้)'}")
        lines.append(f"• ใช้ตัวรับเสียง: {'ใช่' if HAVE_RECV and isinstance(vc, BagleyVoiceClient) else 'ไม่ใช่ (สั่ง /listen on)'}")
        lines.append(f"• กำลังรับเสียงอยู่จริง: {'ใช่' if HAVE_RECV and isinstance(vc, BagleyVoiceClient) and vc.is_listening() else 'ไม่ (ระบบจะต่อให้ใหม่เองภายใน ~2 วิ ถ้าเปิดฟังไว้)'}")
        lines.append(f"• กำลังเล่นเสียง/เพลง: {'ใช่' if vc.is_playing() else 'ไม่'} (ฟังได้ปกติแม้กำลังเล่นเพลง)")
    if s:
        st = s.stats
        up = int(time.monotonic() - s.started)
        ago = f"{time.monotonic() - s.last_audio:.0f}s ที่แล้ว" if s.last_audio else "ยังไม่เคยได้เสียง"
        lines += [
            f"• เปิดฟังมา {up}s | เสียงล่าสุด: {ago} | ต่อการฟังใหม่อัตโนมัติ {s.restarts} ครั้ง",
            f"• แพ็กเก็ต {st['packets']} (ไม่เข้ารหัส {st['plain']} / DAVE ถอดได้ {st['dave']} / ถอดไม่ได้ {st['fail']} / opus เสีย {st['opus_err']})",
            f"• ประโยค {st['utterances']} (ฟังไม่ออก {st['stt_empty']} / STT พัง {st['stt_error']}) | ทิ้งเสียงคนอื่น {st['dropped_other']} แพ็กเก็ต",
        ]
        if s.teaching:
            lines.append(f"• กำลังสอน {len(s.teaching)} คน | โชว์ข้อความที่ได้ยิน: {'เปิด' if s.debug else 'ปิด'}")
        if st["fail"] > 20 and st["dave"] == 0:
            lines.append("⚠️ ถอด DAVE ไม่ได้เลย — ลองให้ทุกคนออก-เข้าห้องใหม่ หรือ /listen off แล้ว on อีกรอบ แล้วส่งบรรทัดนี้ให้ผู้พัฒนา")
    else:
        lines.append("• ยังไม่ได้เปิดฟัง (/listen on)")
    return "\n".join(lines)


def _check_allowed(ctx: commands.Context, dev_only: bool = False) -> str | None:
    """dev_only=True -> เฉพาะผู้พัฒนา (ใช้กับ /listen ที่กระทบทั้งห้อง)
    dev_only=False -> ผู้พัฒนา + คนที่อยู่ในรายชื่อฟังเสียง (ใช้กับ /voice_teach*, /voice_list ซึ่งแก้เฉพาะของตัวเอง)"""
    uid = ctx.author.id
    if dev_only:
        if not allowlist.is_developer(uid):
            return "คำสั่งนี้ใช้ได้เฉพาะผู้พัฒนาครับ 🙏"
    elif not allowlist.is_allowed(uid):
        return "คำสั่งนี้ใช้ได้เฉพาะผู้ที่ได้รับอนุญาตครับ 🙏"
    if ctx.guild is None:
        return "ใช้ได้ในเซิร์ฟเวอร์เท่านั้นครับ"
    return None


def forget_user(user_id: int) -> None:
    """ล้างสถานะค้างของคนที่เพิ่งถูกลบออกจากรายชื่อ (รอรับคำสั่ง/กำลังสอน) ในทุกเซสชัน — เสียงเขาถูกทิ้งที่ตัวรับเสียงอยู่แล้ว"""
    for sess in list(_sessions.values()):
        sess.armed.pop(user_id, None)
        sess.teaching.pop(user_id, None)


@bot.hybrid_command(name="listen", description="ให้แบ็คลี่ฟังเสียงในห้องเสียงโดยตรง (on / off / status / debug)")
async def listen(ctx: commands.Context, mode: str = "status"):
    denied = _check_allowed(ctx, dev_only=True)
    if denied:
        await ctx.send(denied)
        return
    if ctx.interaction:
        await ctx.defer()
    mode = (mode or "status").strip().lower()

    if mode in ("on", "เปิด", "start"):
        try:
            err = await _start_session(ctx)
        except Exception as e:
            err = f"เริ่มฟังไม่สำเร็จ: {type(e).__name__}: {e}"
        if err:
            await ctx.send(f"❌ {err}")
        else:
            await ctx.send("👂 เริ่มฟังแล้วครับ — เรียก “แบ็คลี่” (แบ็คลี่จะขานรับว่า ครับ/ค้าบ/ครับผม) แล้วสั่งต่อได้เลย หรือพูดต่อกัน "
                           "เช่น “แบ็คลี่ เปิดเพลง ...”\n"
                           "สอนคำเรียก/คำสั่งของตัวเอง: `/voice_teach_wake` และ `/voice_teach` | ดูรายการ `/voice_list` | "
                           "เปิดดูข้อความที่ผมได้ยิน `/listen debug`")
    elif mode in ("off", "ปิด", "stop"):
        await ctx.send("🙉 เลิกฟังแล้วครับ" if _stop_session(ctx.guild.id) else "ตอนนี้ยังไม่ได้ฟังอยู่ครับ")
    elif mode == "debug":
        s = _sessions.get(ctx.guild.id)
        if not s:
            await ctx.send("ยังไม่ได้เปิดฟังครับ (/listen on)")
        else:
            s.debug = not s.debug
            await ctx.send("🔍 โชว์ข้อความที่ได้ยินทุกประโยค: " + ("เปิด" if s.debug else "ปิด"))
    else:
        await ctx.send(_status_text(ctx.guild))


async def _begin_teach(ctx: commands.Context, t: _Teach, what: str) -> None:
    denied = _check_allowed(ctx)
    if denied:
        await ctx.send(denied)
        return
    if ctx.interaction:
        await ctx.defer()
    s = _sessions.get(ctx.guild.id)
    # เซสชันเก่าอาจ "หูดับ" ไปแล้วโดยไม่รู้ตัว (เช่นหลัง /skip /stop หรือบอทย้ายห้อง) -> เช็กและต่อใหม่ก่อน ถ้าต่อไม่ได้ค่อยเริ่มเซสชันใหม่
    if s is not None and not _rebind(s):
        s = None
    if s is None:
        try:
            err = await _start_session(ctx)
        except Exception as e:
            err = f"เริ่มฟังไม่สำเร็จ: {type(e).__name__}: {e}"
        if err:
            await ctx.send(f"❌ {err}")
            return
        s = _sessions[ctx.guild.id]
    elif not ctx.author.voice or ctx.author.voice.channel != s.vc.channel:
        await ctx.send("ต้องอยู่ในห้องเสียงเดียวกับแบ็คลี่ก่อนครับ")
        return
    s.text_channel = ctx.channel
    s.armed.pop(ctx.author.id, None)
    s.teaching[ctx.author.id] = t
    await ctx.send(f"🎓 สอน{what} — พูดคำที่อยากใช้ให้เหมือนกันทุกครั้ง **{TEACH_ROUNDS} ครั้ง** "
                   f"(ไม่ต้องเรียกชื่อแบ็คลี่นำหน้า) รอฟังเสียงติ๊ดทุกครั้งก่อนพูดรอบต่อไปนะครับ 🎙️")
    await _play_beep(s.vc)


@bot.hybrid_command(name="voice_teach", description="สอนคำพูดที่ใช้เรียกคำสั่ง เช่น /tts , /leave , /kick (พูด 5 ครั้ง)")
async def voice_teach(ctx: commands.Context, command: str, has_arg: bool = False):
    name = command.strip().lstrip("/!").split(" ")[0]
    if not name or bot.get_command(name) is None:
        await ctx.send(f"❌ ไม่มีคำสั่ง `/{name}` ในบอทครับ ลองพิมพ์ใหม่ เช่น `/tts` `/leave`")
        return
    send = "/" + command.strip().lstrip("/!")
    label = f"คำสั่ง `{send}`" + (" (มีชื่อ/ค่าต่อท้าย)" if has_arg else "")
    await _begin_teach(ctx, _Teach("cmd", send=send, has_arg=has_arg), label)


@bot.hybrid_command(name="voice_teach_wake", description="สอนวิธีเรียกชื่อ “แบ็คลี่” ของตัวเอง (พูดชื่อ 5 ครั้ง)")
async def voice_teach_wake(ctx: commands.Context):
    await _begin_teach(ctx, _Teach("wake"), "ชื่อเรียกแบ็คลี่ของคุณ")


@bot.hybrid_command(name="voice_list", description="ดูรายการเสียงที่สอนไว้ของตัวเอง และเลือกลบ")
async def voice_list(ctx: commands.Context):
    denied = _check_allowed(ctx)
    if denied:
        await ctx.send(denied)
        return
    user = teach_store.get_user(ctx.author.id)
    if not user["wake"] and not user["commands"]:
        await ctx.send("ยังไม่มีอะไรที่สอนไว้ครับ — เริ่มที่ `/voice_teach_wake` และ `/voice_teach`")
        return
    lines = [f"📚 **รายการเสียงของ {ctx.author.display_name}**"]
    lines.append("ชื่อเรียกแบ็คลี่: " + (", ".join(user["wake"]) if user["wake"] else "(ใช้คำมาตรฐาน)"))
    for i, c in enumerate(user["commands"], start=1):
        tail = " <ชื่อ>" if c.get("args") else ""
        lines.append(f"{i}. {c['send']}{tail}  ←  {', '.join(c['phrases'])}")
    await ctx.send("\n".join(lines), view=_DeleteView(ctx.author.id, user))


@bot.listen("on_voice_state_update")
async def _listen_cleanup(member, before, after):
    # บอทออกจากห้องเสียง: เก็บเซสชันไว้ (ล้างเสียงค้าง) พอบอทกลับเข้าห้องใหม่ watchdog จะต่อการฟังให้เอง
    # (เลิกฟังจริงๆ ใช้ /listen off)
    if bot.user and member.id == bot.user.id and after.channel is None:
        s = _sessions.get(member.guild.id)
        if s:
            s.segmenter.clear()
            s.armed.clear()
            s.vc = None
