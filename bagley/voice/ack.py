"""bagley/voice/ack.py — เสียงขานรับตอนแบ็คลี่ได้ยินชื่อตัวเอง ("ครับ" / "ค้าบ" / "ครับผม" สุ่มเอา 1 ใน 3)

ทำไมถึงตอบสนองไว
  - ไฟล์เสียงทั้ง 3 คำ "บันทึกถาวร" ไว้ในโฟลเดอร์ voice_ack/ (ไม่ใช่ tts_cache ที่โดนล้างอัตโนมัติ)
    สร้างครั้งเดียวตอนบอทเริ่มครั้งแรก หลังจากนั้นเปิดบอทกี่ครั้งก็ไม่ต้องสร้างใหม่
  - ตอนบอทเริ่มจะ "ถอดรหัสไฟล์เป็น PCM ค้างไว้ในหน่วยความจำ" ล่วงหน้า (ตัดช่วงเงียบหัวไฟล์ด้วย)
    พอได้ยินชื่อก็ส่ง PCM เข้าห้องทันที ไม่ต้องเปิด ffmpeg ใหม่ทุกครั้ง (เหมือนเสียงติ๊ดเดิม)

อยากเปลี่ยนเสียง/คำ:
  - ลบไฟล์ใน voice_ack/ แล้วเปิดบอทใหม่ -> สร้างใหม่ให้เอง
  - หรือเอาไฟล์อัดเสียงจริงมาวางทับชื่อเดิมได้เลย (บอทไม่เขียนทับไฟล์ที่มีอยู่แล้ว)
  - เปลี่ยน TTS_VOICE ใน .env -> สร้างชุดใหม่ของเสียงนั้นให้อัตโนมัติ (ชื่อไฟล์มีชื่อเสียงต่อท้าย)

ปรับได้ใน .env:  VOICE_ACK_DIR=voice_ack   VOICE_ACK_RATE=+0%   VOICE_ACK_VOLUME=1.0
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import shutil
import subprocess
from typing import Optional

import numpy as np

from bagley.core.logutil import print
from bagley.voice import tts

ACK_DIR = os.getenv("VOICE_ACK_DIR", "voice_ack")
ACK_RATE = os.getenv("VOICE_ACK_RATE", "+0%")
try:
    ACK_VOLUME = min(2.0, max(0.1, float(os.getenv("VOICE_ACK_VOLUME", "1.0"))))
except ValueError:
    ACK_VOLUME = 1.0

# key (ใช้ตั้งชื่อไฟล์) -> คำที่พูด
ACK_WORDS: dict[str, str] = {
    "krub": "ครับ",
    "khaap": "ค้าบ",
    "krubphom": "ครับผม",
}

_pcm: dict[str, bytes] = {}          # key -> PCM 48kHz สเตอริโอ int16 พร้อมเล่น
_load_lock: Optional[asyncio.Lock] = None


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "voice"


def ack_path(key: str, voice: Optional[str] = None) -> str:
    return os.path.join(ACK_DIR, f"ack_{key}_{_slug(voice or tts.TTS_VOICE)}.mp3")


def _decode_to_pcm(path: str) -> bytes:
    """mp3 -> PCM 48kHz สเตอริโอ (ตัดเงียบหัวไฟล์ให้ขานรับทันที) ใช้ ffmpeg ตัวเดียวกับระบบพูด"""
    cmd = [
        tts.FFMPEG_PATH, "-v", "error", "-i", path,
        "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02",
        "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1",
    ]
    out = subprocess.run(cmd, capture_output=True, timeout=20, check=True).stdout
    arr = np.frombuffer(out, dtype="<i2")
    if ACK_VOLUME != 1.0:
        arr = np.clip(arr.astype(np.float32) * ACK_VOLUME, -32768, 32767).astype("<i2")
    frame = 3840 // 2                                    # 20ms ต่อเฟรม (discord.PCMAudio ต้องการเฟรมเต็ม)
    pad = (-arr.size) % frame
    if pad:
        arr = np.concatenate([arr, np.zeros(pad, dtype="<i2")])
    return arr.tobytes()


async def _ensure_file(key: str, word: str) -> Optional[str]:
    """คืน path ไฟล์ถาวรของคำนี้ (ถ้ายังไม่มีจะสร้างครั้งแรกครั้งเดียวแล้วเก็บถาวร)"""
    path = ack_path(key)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        os.makedirs(ACK_DIR, exist_ok=True)
        src = await tts.synth(word, rate=ACK_RATE)       # ใช้ edge-tts เดิมของบอท
        tmp = f"{path}.tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, path)
        print(f"🔊 [Ack] สร้างเสียงขานรับ “{word}” เก็บถาวรที่ {path}")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ [Ack] สร้างเสียง “{word}” ไม่สำเร็จ: {type(e).__name__}: {e}")
        return None


async def ensure_loaded() -> int:
    """เตรียมไฟล์ (สร้างถ้ายังไม่มี) + ถอดรหัสเข้าหน่วยความจำ คืนจำนวนคำที่พร้อมใช้ (เรียกซ้ำได้ ไม่ทำงานซ้ำ)"""
    global _load_lock
    if _load_lock is None:
        _load_lock = asyncio.Lock()
    async with _load_lock:
        for key, word in ACK_WORDS.items():
            if key in _pcm:
                continue
            path = await _ensure_file(key, word)
            if not path:
                continue
            try:
                data = await asyncio.to_thread(_decode_to_pcm, path)
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ [Ack] ถอดรหัส {path} ไม่ได้: {type(e).__name__}: {e}")
                continue
            if data:
                _pcm[key] = data
            else:
                print(f"⚠️ [Ack] {path} ไม่มีเสียง (ไฟล์เสีย/เงียบทั้งไฟล์?) ลบไฟล์นี้แล้วเปิดบอทใหม่เพื่อสร้างใหม่ได้")
        return len(_pcm)


def pick_pcm() -> Optional[bytes]:
    """สุ่มเสียงขานรับ 1 ใน 3 คำ (คืน None ถ้ายังไม่มีไฟล์ที่พร้อมใช้ -> ผู้เรียกใช้เสียงติ๊ดแทน)"""
    if not _pcm:
        return None
    return _pcm[random.choice(list(_pcm))]
