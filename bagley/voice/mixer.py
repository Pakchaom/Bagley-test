"""bagley/voice/mixer.py — ผสมเสียงพูด/เสียงติ๊ด "ซ้อน" บนเพลงที่กำลังเล่น (หรี่เพลงลงชั่วคราว)

discord.py เล่นได้ทีละ source เดียวต่อ voice client เดิมเลยต้องรอเพลงจบก่อนบอทถึงจะพูด/ติ๊ดได้
ตัวนี้ครอบเพลงไว้ทีละเฟรม 20ms: ถ้ามีเสียงซ้อน (overlay) ก็หรี่เพลงลงแล้วรวมเสียงเข้าด้วยกัน
พูดจบแล้วเพลงค่อยๆ ดังกลับ — ไม่ตัดเพลง ไม่ต้องรอ

ปรับได้ใน .env:  MUSIC_DUCK_LEVEL=0.30 (เพลงเหลือกี่เท่าตอนมีเสียงพูด 0=เงียบสนิท 1=ไม่หรี่)
                  MUSIC_DUCK_HOLD_MS=500 (ค้างระดับเบาไว้หลังพูดจบกี่ ms กันเพลงดังสวิงระหว่างประโยค)
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Callable, Optional

import discord
import numpy as np

FRAME_BYTES = 3840                         # 20ms, 48kHz, สเตอริโอ, int16
DUCK_LEVEL = min(1.0, max(0.0, float(os.getenv("MUSIC_DUCK_LEVEL", "0.30"))))
HOLD_FRAMES = max(0, int(int(os.getenv("MUSIC_DUCK_HOLD_MS", "500")) / 20))
DOWN_FRAMES = 4                            # หรี่เสียงลงใน ~80ms
UP_FRAMES = 20                             # ดังกลับใน ~400ms


_NOT_READY = object()                      # ยังอ่านเฟรมจาก ffmpeg ไม่ทัน (ไม่ใช่จบ) -> ข้ามเฟรมนี้ ไม่หรี่เพลง
PREFETCH_FRAMES = 60                       # อ่านล่วงหน้าได้สูงสุด ~1.2 วินาที


class _Overlay:
    """ห่อเสียงซ้อนด้วยเธรดอ่านล่วงหน้า: ffmpeg เพิ่งสตาร์ท/ดิสก์ช้าจะไม่ทำให้ลูปส่งเสียงของเพลงสะดุด
    (เดิม mixer.read() อ่าน ffmpeg ของเสียงซ้อนตรงๆ ในเธรดเดียวกับเพลง ถ้า ffmpeg ยังไม่พร้อมเพลงจะกระตุกทุกครั้งที่บอทพูด)"""
    __slots__ = ("raw", "on_done", "_buf", "_end", "_stop", "_thread")

    def __init__(self, src: discord.AudioSource, on_done: Optional[Callable[[], None]]):
        self.raw = src
        self.on_done = on_done
        self._buf: deque = deque()
        self._end = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._fill, name="bagley-overlay-prefetch", daemon=True)
        self._thread.start()

    def _fill(self) -> None:
        try:
            while not self._stop.is_set():
                if len(self._buf) >= PREFETCH_FRAMES:
                    time.sleep(0.01)
                    continue
                f = self.raw.read()
                if not f:
                    break
                self._buf.append(f)
        except Exception:
            pass
        finally:
            self._end = True

    def read(self):
        """คืน bytes เฟรมถัดไป / b"" เมื่อจบจริง / _NOT_READY เมื่อยังไม่มีเฟรม"""
        try:
            return self._buf.popleft()
        except IndexError:
            if self._end and not self._buf:
                return b""
            return _NOT_READY

    def close(self) -> None:
        self._stop.set()
        try:
            self.raw.cleanup()
        except Exception:
            pass


def _to_arr(buf: bytes) -> np.ndarray:
    a = np.frombuffer(buf, dtype="<i2").astype(np.float32)
    if a.size < FRAME_BYTES // 2:
        a = np.pad(a, (0, FRAME_BYTES // 2 - a.size))
    return a[: FRAME_BYTES // 2]


class DuckingMixer(discord.AudioSource):
    """ครอบเพลง (source PCM 48k สเตอริโอ) แล้วรับเสียงซ้อนผ่าน add_overlay()"""

    def __init__(self, music: discord.AudioSource):
        self.music = music
        self._lock = threading.Lock()
        self._overlays: list[_Overlay] = []
        self._gain = 1.0
        self._hold = 0

    # ---- ให้โค้ดเดิมที่เฟดเสียงผ่าน vc.source.volume (alerts.fade_out_source) ยังใช้ได้ ----
    @property
    def volume(self) -> float:
        return getattr(self.music, "volume", 1.0)

    @volume.setter
    def volume(self, v: float) -> None:
        if hasattr(self.music, "volume"):
            self.music.volume = v

    @property
    def has_overlay(self) -> bool:
        with self._lock:
            return bool(self._overlays)

    def add_overlay(self, src: discord.AudioSource, on_done: Optional[Callable[[], None]] = None) -> None:
        """เพิ่มเสียงที่จะซ้อนบนเพลง (ต้องเป็น PCM 48k สเตอริโอ) on_done เรียกจากเธรดเล่นเสียงเมื่อจบ/ถูกตัด"""
        with self._lock:
            self._overlays.append(_Overlay(src, on_done))

    def remove_overlay(self, src: discord.AudioSource) -> bool:
        """ตัดเฉพาะเสียงซ้อนตัวนี้ (เพลงเล่นต่อ) คืน True ถ้าเจอและตัดแล้ว"""
        with self._lock:
            hit = [o for o in self._overlays if o.raw is src]
            if hit:
                self._overlays = [o for o in self._overlays if o.raw is not src]
        for ov in hit:
            self._finish(ov)
        return bool(hit)

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        m = self.music.read()
        if not m:                                   # เพลงจบ -> จบทั้งหมด (cleanup จะเคลียร์เสียงซ้อนที่ค้าง)
            return b""
        with self._lock:
            ovs = list(self._overlays)
        mixed = None
        finished: list[_Overlay] = []
        for ov in ovs:
            try:
                f = ov.read()
            except Exception:
                f = b""
            if f is _NOT_READY:
                continue
            if not f:
                finished.append(ov)
                continue
            a = _to_arr(f)
            mixed = a if mixed is None else mixed + a
        if finished:
            with self._lock:
                self._overlays = [o for o in self._overlays if o not in finished]
            for ov in finished:
                self._finish(ov)

        if mixed is not None:
            self._hold = HOLD_FRAMES
            target = DUCK_LEVEL
        elif self._hold > 0 and self._gain < 1.0:
            self._hold -= 1
            target = DUCK_LEVEL
        else:
            target = 1.0
        if self._gain > target:
            self._gain = max(target, self._gain - (1.0 - DUCK_LEVEL) / DOWN_FRAMES)
        elif self._gain < target:
            self._gain = min(target, self._gain + (1.0 - DUCK_LEVEL) / UP_FRAMES)

        out = _to_arr(m) * self._gain
        if mixed is not None:
            out = out + mixed
        return np.clip(out, -32768, 32767).astype("<i2").tobytes()

    @staticmethod
    def _finish(ov: _Overlay) -> None:
        ov.close()
        if ov.on_done:
            try:
                ov.on_done()
            except Exception:
                pass

    def cleanup(self) -> None:
        try:
            self.music.cleanup()
        finally:
            with self._lock:
                ovs, self._overlays = self._overlays, []
            for ov in ovs:                           # เพลงถูกตัด/จบ -> ปล่อยคนที่รอเสียงซ้อนอยู่ ไม่ให้ค้าง
                self._finish(ov)


def get_mixer(vc) -> Optional[DuckingMixer]:
    """ถ้าตอนนี้กำลังเล่นเพลงผ่านตัวผสม (และไม่ได้พักเพลง) คืนตัวผสม ไม่งั้น None"""
    try:
        src = vc.source if vc else None
        if isinstance(src, DuckingMixer) and vc.is_playing() and not vc.is_paused():
            return src
    except Exception:
        pass
    return None
