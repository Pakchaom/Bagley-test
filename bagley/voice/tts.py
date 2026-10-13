"""
bagley/voice/tts.py — ระบบพูดของแบ็คลี่ (เร็วกว่าเดิมชัดเจน)

ของเดิมช้าเพราะ
  1) หน่วงเวลาตายตัว 0.5 + 0.5 วินาทีต่อประโยค + วนเช็คทุก 0.1 วิ
  2) สร้างไฟล์เสียงเฉพาะ "หลัง" รอคิวพูดเสร็จ (เรียงต่อกัน ไม่ซ้อนกัน)
  3) สร้างไฟล์ใหม่ทุกครั้งแม้ประโยคเดิมเป๊ะ แล้วลบทิ้ง

ของใหม่
  - สังเคราะห์เสียง "ล่วงหน้า" ระหว่างที่ประโยคก่อนหน้ายังเล่นอยู่ (ซ้อนกัน) พอถึงคิวก็เล่นได้ทันที
  - แคชไฟล์เสียงตามข้อความ+เสียง+ความเร็ว (ประโยคเดิมซ้ำ = ไม่มีเวลาสร้างเลย) พร้อมล้างแคชเก่าอัตโนมัติ
  - รอเสียงจบด้วย callback (asyncio.Event) แทนการวนเช็ค ไม่มีการหน่วงตายตัว
  - เตรียมแคชประโยคตายตัว (ที่ไม่มีชื่อคน) ไว้ตอนบอทเริ่มทำงาน
  - ทำความสะอาดข้อความ (อีโมจิ/markdown/ลิงก์/mention) ก่อนส่งเข้า TTS ให้ฟังเนียนและแคชโดนบ่อยขึ้น
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
from typing import Optional

import discord

from bagley.core import state

TTS_VOICE = os.getenv("TTS_VOICE", "th-TH-NiwatNeural")
CACHE_DIR = os.getenv("TTS_CACHE_DIR", "tts_cache")
CACHE_MAX_FILES = int(os.getenv("TTS_CACHE_MAX_FILES", "300"))


def _find_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    win = r"C:\ffmpeg\bin\ffmpeg.exe"
    if os.path.exists(win):
        return win
    return shutil.which("ffmpeg") or "ffmpeg"


FFMPEG_PATH = _find_ffmpeg()

os.makedirs(CACHE_DIR, exist_ok=True)

# ----------------------------------------------------------------------------
# ล็อกต่อกิลด์ (กันพูดทับกัน)
# ----------------------------------------------------------------------------
def get_voice_speak_lock(guild_id) -> asyncio.Lock:
    if guild_id not in state.voice_speak_locks:
        state.voice_speak_locks[guild_id] = asyncio.Lock()
    return state.voice_speak_locks[guild_id]


# ----------------------------------------------------------------------------
# ทำความสะอาดข้อความก่อนพูด
# ----------------------------------------------------------------------------
_URL = re.compile(r"https?://\S+")
_MENTION = re.compile(r"<[@#!&]+\d+>|<a?:\w+:\d+>")
_MD = re.compile(r"[*_`~|>#]+")
_NOT_SPEAKABLE = re.compile(r"[^\u0e00-\u0e7fa-zA-Z0-9\s\.\,\!\?\-\:\+\%\/\(\)']")
_SPACES = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    t = _URL.sub(" ", text or "")
    t = _MENTION.sub(" ", t)
    t = _MD.sub(" ", t)
    t = _NOT_SPEAKABLE.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


# ----------------------------------------------------------------------------
# สังเคราะห์เสียง + แคช
# ----------------------------------------------------------------------------
_inflight: dict = {}


def _cache_path(text: str, voice: str, rate: str) -> str:
    h = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:20]
    return os.path.join(CACHE_DIR, f"{h}.mp3")


async def synth(text: str, voice: Optional[str] = None, rate: str = "+0%") -> str:
    """คืน path ไฟล์ mp3 (จากแคชถ้ามี) — เรียกซ้อนกันด้วยข้อความเดียวกันจะรอผลเดียวกัน"""
    voice = voice or TTS_VOICE
    path = _cache_path(text, voice, rate)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            os.utime(path, None)  # ใช้ล่าสุด (สำหรับล้างแคช LRU)
        except OSError:
            pass
        return path
    fut = _inflight.get(path)
    if fut is not None:
        return await asyncio.shield(fut)

    async def _make() -> str:
        import edge_tts
        tmp = f"{path}.{os.getpid()}.tmp"
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                await edge_tts.Communicate(text, voice, rate=rate).save(tmp)
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    os.replace(tmp, path)
                    return path
            except Exception as e:  # noqa: BLE001
                last_err = e
                await asyncio.sleep(0.3)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise RuntimeError(f"สร้างเสียงไม่สำเร็จ: {last_err}")

    task = asyncio.ensure_future(_make())
    _inflight[path] = task
    try:
        return await asyncio.shield(task)
    finally:
        _inflight.pop(path, None)


def prune_cache(max_files: int = CACHE_MAX_FILES):
    try:
        files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if f.endswith(".mp3")]
        if len(files) <= max_files:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[: len(files) - max_files]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


# ----------------------------------------------------------------------------
# เล่นไฟล์เสียงแล้วรอจนจบ (ใช้ callback ไม่ต้องวนเช็ค)
# ----------------------------------------------------------------------------
async def play_and_wait(vc, source_path: str, *, timeout: float = 180.0, volume: Optional[float] = None) -> None:
    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    src = discord.FFmpegPCMAudio(source_path, executable=FFMPEG_PATH)
    if volume is not None:
        src = discord.PCMVolumeTransformer(src, volume=volume)

    def _after(err):
        if err:
            print(f"⚠️ [TTS] เล่นเสียงมีปัญหา: {err}")
        loop.call_soon_threadsafe(done.set)

    try:
        vc.play(src, after=_after)
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            vc.stop()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            src.cleanup()
        except Exception:  # noqa: BLE001
            pass


async def _wait_until_idle(vc, poll: float = 0.05, limit: float = 300.0):
    t0 = time.monotonic()
    while vc.is_playing() and time.monotonic() - t0 < limit:
        await asyncio.sleep(poll)


# ----------------------------------------------------------------------------
# ฟังก์ชันพูดหลัก (ชื่อ/พารามิเตอร์เดิม เพื่อให้โค้ดที่เรียกอยู่ใช้ต่อได้ทันที)
# ----------------------------------------------------------------------------
async def bagley_speak_wait(guild, text, filename=None, rate="+0%"):
    """พูดเป็นคิวต่อกิลด์ รอเสียงก่อนหน้าจบก่อนแล้วค่อยพูด (ไม่ทิ้งข้อความ)
    rate: ความเร็วเสียง เช่น '-20%' ช้าลง (ใช้ตอนเล่าเรื่องยาว), '+0%' ปกติ
    ( filename เก็บไว้เพื่อความเข้ากันได้กับโค้ดเดิม — ไม่ได้ใช้แล้ว )"""
    if not guild:
        return
    vc = guild.voice_client
    if not (vc and vc.is_connected()):
        return
    speech = clean_for_speech(text)
    if not speech:
        return

    state.pending_speak_count[guild.id] = state.pending_speak_count.get(guild.id, 0) + 1
    # เริ่มสร้างเสียงทันที (ซ้อนกับเสียงที่กำลังเล่นอยู่) ไม่ต้องรอคิว
    synth_task = asyncio.ensure_future(synth(speech, rate=rate))
    try:
        async with get_voice_speak_lock(guild.id):
            try:
                path = await synth_task
            except Exception as e:  # noqa: BLE001
                print(f"Error ในการสร้างเสียงพูด: {e}")
                return
            vc = guild.voice_client  # อาจเปลี่ยนระหว่างรอ
            if not (vc and vc.is_connected()):
                return
            await _wait_until_idle(vc)
            try:
                await play_and_wait(vc, path)
            except Exception as e:  # noqa: BLE001
                print(f"Error ในการพูดด้วยเสียง: {e}")
    finally:
        if not synth_task.done():
            synth_task.cancel()
        remaining = state.pending_speak_count.get(guild.id, 1) - 1
        if remaining <= 0:
            state.pending_speak_count.pop(guild.id, None)
        else:
            state.pending_speak_count[guild.id] = remaining


async def bagley_speak(guild, text, rate="+0%"):
    """ฟังก์ชันกลางสั่งให้แบ็คลี่พูดในห้องเสียงที่บอทอยู่ (เข้าคิว ไม่ดรอปข้อความ)"""
    if not guild:
        return
    vc = guild.voice_client
    if not (vc and vc.is_connected()):
        return
    if not clean_for_speech(text):
        return
    try:
        await bagley_speak_wait(guild, text, rate=rate)
    except Exception as e:  # noqa: BLE001
        print(f"Bagley Voice Error: {e}")


# ----------------------------------------------------------------------------
# อุ่นแคชประโยคตายตัว (ไม่มี {ตัวแปร}) ตอนบอทเริ่ม — เบื้องหลัง ไม่บล็อกการเริ่มงาน
# ----------------------------------------------------------------------------
_WARM_KEYS = (
    "music_stopped", "music_skipped", "music_queue_end", "music_queue_empty", "music_stop_nothing",
    "mute_done", "unmute_done", "deaf_done", "undeaf_done", "welcome_back_short", "memory_cleared",
    "cleanup_done", "alarm_stopped", "image_analyzing", "image_ready", "back_from_teams",
    "need_voice", "bot_need_voice", "no_power",
)


async def warm_cache(limit: int = 90, gap: float = 0.4):
    if os.getenv("TTS_WARM", "1") == "0":
        return
    from bagley import phrases
    texts = []
    for key in _WARM_KEYS:
        texts += [t for t in phrases.POOLS.get(key, []) if "{" not in t]
    for lst in (phrases.VOICE_REPORT_ON_SPEECH, phrases.VOICE_REPORT_OFF_SPEECH, phrases.VOICE_GUARD_STAY_MESSAGES,
                phrases.REPORT_PERMISSION_PHRASES):
        texts += [t for t in lst if "{" not in t]
    done = 0
    for t in texts:
        if done >= limit:
            break
        speech = clean_for_speech(t)
        if not speech:
            continue
        path = _cache_path(speech, TTS_VOICE, "+0%")
        if os.path.exists(path):
            continue
        try:
            await synth(speech)
            done += 1
        except Exception:  # noqa: BLE001
            break  # ถ้าบริการ TTS ติดปัญหา เลิกอุ่นแคช ไม่รบกวน
        await asyncio.sleep(gap)
    prune_cache()
    if done:
        print(f"🔊 [TTS] อุ่นแคชเสียงไว้ล่วงหน้า {done} ประโยค")
