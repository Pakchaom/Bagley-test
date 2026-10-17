"""ทดสอบตัวผสมเสียง (DuckingMixer): เสียงซ้อนต้องไม่ตัดเพลง, remove_overlay ตัดเฉพาะเสียงซ้อน, ไม่บล็อกถ้าเสียงซ้อนยังไม่พร้อม
รัน: PYTHONPATH=. python3 tests/test_mixer.py"""
import sys
import threading
import time

import discord
import numpy as np

from bagley.voice import mixer as mx

F = mx.FRAME_BYTES
bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


def frame(v):
    return np.full(F // 2, v, dtype="<i2").tobytes()


def level(buf):
    return int(np.frombuffer(buf, dtype="<i2")[0])


class Const(discord.AudioSource):
    """ส่งเฟรมค่าคงที่ n เฟรม แล้วจบ"""
    def __init__(self, v, n):
        self.v, self.n, self.cleaned = v, n, False

    def read(self):
        if self.n <= 0:
            return b""
        self.n -= 1
        return frame(self.v)

    def cleanup(self):
        self.cleaned = True


class Slow(discord.AudioSource):
    """จำลอง ffmpeg ที่เพิ่งสตาร์ท: read() บล็อก 0.5 วิ ก่อนจะให้เฟรมแรก"""
    def __init__(self, v, n):
        self.v, self.n, self.first = v, n, True

    def read(self):
        if self.first:
            self.first = False
            time.sleep(0.5)
        if self.n <= 0:
            return b""
        self.n -= 1
        return frame(self.v)


def wait_for(pred, t=2.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


# 1) ไม่มีเสียงซ้อน = เพลงผ่านเต็มเสียง
m = mx.DuckingMixer(Const(10000, 5000))
check("no overlay -> full volume", level(m.read()) == 10000)

# 2) มีเสียงซ้อน: เพลงต้องเบาลง, เสียงซ้อนต้องมาผสม และเพลงต้อง "ไม่จบ"
done = threading.Event()
m = mx.DuckingMixer(Const(10000, 5000))
m.add_overlay(Const(2000, 60), on_done=done.set)
wait_for(lambda: len(m._overlays[0]._buf) > 5)
levels = [level(m.read()) for _ in range(40)]
check("music ducked under overlay", min(levels) < 10000 * 0.5 + 2000 + 50, f"min={min(levels)}")
check("overlay mixed in (louder than ducked music alone)", max(levels) >= 2000)
check("music not cut while overlay plays", all(l != 0 for l in levels))

# 3) เสียงซ้อนจบ -> on_done ถูกเรียก, เพลงกลับมาดังเต็ม, เพลงยังเล่นต่อ
# อ่านทีละเฟรมแบบเรียลไทม์เล็กน้อยเหมือนตัวส่งเสียงจริง (ทุก 20ms) — อ่านรัวเร็วกว่าจริงมากเธรดอ่านล่วงหน้าจะตามไม่ทัน
t0 = time.time()
while not done.is_set() and time.time() - t0 < 3:
    m.read()
    time.sleep(0.002)
check("on_done called when overlay ends", done.is_set())
for _ in range(80):
    m.read()
    time.sleep(0.001)
check("music recovers to full volume after overlay", level(m.read()) == 10000)

# 4) remove_overlay ตัดเฉพาะเสียงซ้อน เพลงไม่ถูกตัด
src = Const(3000, 100000)
done2 = threading.Event()
m = mx.DuckingMixer(Const(10000, 5000))
m.add_overlay(src, on_done=done2.set)
wait_for(lambda: len(m._overlays[0]._buf) > 5)
m.read()
check("remove_overlay returns True", m.remove_overlay(src) is True)
check("remove_overlay calls on_done", done2.is_set())
check("remove_overlay cleans up the source", src.cleaned)
check("music still playing after remove_overlay", len(m.read()) == F)
check("remove_overlay on unknown source = False", m.remove_overlay(Const(1, 1)) is False)

# 5) เสียงซ้อนที่ยังไม่พร้อม (ffmpeg ช้า) ต้องไม่ทำให้ read() ของเพลงบล็อก/ไม่หรี่เพลงก่อนมีเสียง
m = mx.DuckingMixer(Const(10000, 5000))
m.add_overlay(Slow(2000, 30))
t0 = time.time()
first = [level(m.read()) for _ in range(10)]
elapsed = time.time() - t0
check("read() does not block on slow overlay", elapsed < 0.2, f"{elapsed:.3f}s")
check("music not ducked before overlay has audio", all(l == 10000 for l in first), str(first[:3]))

# 6) เพลงจบ -> cleanup เคลียร์เสียงซ้อนที่ค้าง (ไม่ให้คนรอค้าง)
done3 = threading.Event()
m = mx.DuckingMixer(Const(10000, 1))
m.add_overlay(Const(2000, 100000), on_done=done3.set)
m.read()
check("music end -> read returns empty", m.read() == b"")
m.cleanup()
check("cleanup releases pending overlay waiters", done3.is_set())

print("FAILED:", bad)
sys.exit(1 if bad else 0)
