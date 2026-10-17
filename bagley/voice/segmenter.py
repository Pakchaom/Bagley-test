"""bagley/voice/segmenter.py — ตัดเสียงที่รับจากห้องเสียง Discord ให้เป็น "ประโยค" ต่อคน

Discord ส่งเสียงมาเป็นแพ็กเก็ต 20ms (PCM 48kHz สเตอริโอ) ตอนที่คนพูดเท่านั้น
ตัวนี้เก็บสะสมต่อคน แล้วตัดเป็นประโยคเมื่อเงียบเกิน END_SILENCE (หรือยาวเกิน MAX_SEC)
แปลงเป็น mono 16kHz พร้อมส่งเข้า STT  (ไม่พึ่ง discord เลย ทดสอบแยกได้)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

SRC_RATE = 48000
OUT_RATE = 16000


@dataclass
class Utterance:
    user_id: int
    pcm16k: bytes      # mono, 16kHz, int16 little-endian
    duration: float    # วินาที
    rms: float         # ความดังเฉลี่ย (ไว้กรองเสียงลมหายใจ/เสียงรบกวน)


def to_mono16k(pcm48_stereo: bytes) -> np.ndarray:
    """PCM 48kHz สเตอริโอ -> mono 16kHz (เฉลี่ยซ้าย/ขวา แล้วเฉลี่ยทีละ 3 ตัวอย่างกัน alias)"""
    a = np.frombuffer(pcm48_stereo, dtype="<i2")
    if a.size % 2:
        a = a[:-1]
    if a.size == 0:
        return np.zeros(0, dtype=np.int16)
    mono = a.reshape(-1, 2).astype(np.int32).mean(axis=1)
    n = (mono.size // 3) * 3
    if n == 0:
        return np.zeros(0, dtype=np.int16)
    return mono[:n].reshape(-1, 3).mean(axis=1).astype(np.int16)


class Segmenter:
    def __init__(self, end_silence: float = 0.8, max_sec: float = 15.0,
                 min_sec: float = 0.4, min_rms: float = 250.0):
        self.end_silence = end_silence
        self.max_sec = max_sec
        self.min_sec = min_sec
        self.min_rms = min_rms
        self._buf: dict[int, dict] = {}
        self._lock = threading.Lock()

    def feed(self, user_id: int, pcm48_stereo: bytes, now: float | None = None) -> None:
        """เรียกจากเธรดรับเสียง (ทุกแพ็กเก็ต)"""
        now = time.monotonic() if now is None else now
        m = to_mono16k(pcm48_stereo)
        if m.size == 0:
            return
        with self._lock:
            b = self._buf.get(user_id)
            if b is None:
                b = self._buf[user_id] = {"chunks": [], "n": 0, "last": now}
            b["chunks"].append(m)
            b["n"] += m.size
            b["last"] = now

    def flush_due(self, now: float | None = None, force: bool = False) -> list[Utterance]:
        """เรียกวนเป็นระยะ คืนประโยคที่จบแล้ว"""
        now = time.monotonic() if now is None else now
        out: list[Utterance] = []
        with self._lock:
            for uid in list(self._buf):
                b = self._buf[uid]
                dur = b["n"] / OUT_RATE
                if force or (now - b["last"]) >= self.end_silence or dur >= self.max_sec:
                    del self._buf[uid]
                    utt = self._finish(uid, b)
                    if utt:
                        out.append(utt)
        return out

    def _finish(self, uid: int, b: dict) -> Utterance | None:
        data = np.concatenate(b["chunks"])
        dur = data.size / OUT_RATE
        if dur < self.min_sec:
            return None
        rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
        if rms < self.min_rms:
            return None
        return Utterance(uid, data.tobytes(), dur, rms)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


def make_beep_pcm(freq: float = 880.0, beeps: int = 2, beep_ms: int = 110,
                  gap_ms: int = 70, volume: float = 0.22) -> bytes:
    """เสียง 'ติ๊ดๆ' ตอนได้ยินชื่อแบ็คลี่ (PCM 48kHz สเตอริโอ ให้ discord.PCMAudio เล่นได้เลย)"""
    parts = []
    n = int(SRC_RATE * beep_ms / 1000)
    t = np.arange(n) / SRC_RATE
    tone = np.sin(2 * np.pi * freq * t)
    fade = np.minimum(1.0, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (SRC_RATE * 0.008))
    tone = tone * fade * volume
    gap = np.zeros(int(SRC_RATE * gap_ms / 1000))
    for i in range(beeps):
        parts.append(tone)
        if i < beeps - 1:
            parts.append(gap)
    mono = np.concatenate(parts)
    frame = 960                                  # 20ms ต่อเฟรม
    pad = (-mono.size) % frame
    mono = np.concatenate([mono, np.zeros(pad)])
    pcm = (mono * 32767).astype("<i2")
    return np.repeat(pcm, 2).tobytes()            # ซ้าย=ขวา
