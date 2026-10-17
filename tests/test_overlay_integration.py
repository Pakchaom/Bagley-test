"""ทดสอบรวม: เล่นเพลง (จำลอง) ผ่าน DuckingMixer บน voice client จำลองที่ดึงเฟรมทุก 20ms เหมือน AudioPlayer จริง
แล้วยิงเสียงแจ้งเตือนจริง (mp3 ผ่าน ffmpeg) ซ้อน — เพลงต้องไม่ถูกตัด/ไม่สะดุด และ stop เฉพาะเสียงแจ้งเตือน
ต้องมี ffmpeg ในเครื่อง   รัน: PYTHONPATH=. python3 tests/test_overlay_integration.py"""
import asyncio
import os
import shutil
import sys
import threading
import time

import discord
import numpy as np

os.environ.setdefault("DISCORD_TOKEN", "x")
if not shutil.which("ffmpeg"):
    print("SKIP: ไม่มี ffmpeg")
    sys.exit(0)

from bagley.voice import mixer as mx  # noqa: E402
from bagley.voice import tts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX = os.path.join(ROOT, "drone_hijack.mp3")
bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


class Music(discord.AudioSource):
    def __init__(self, frames=100000):
        self.n = frames
        self.cleaned = False

    def read(self):
        if self.n <= 0:
            return b""
        self.n -= 1
        return np.full(mx.FRAME_BYTES // 2, 10000, dtype="<i2").tobytes()

    def cleanup(self):
        self.cleaned = True


class FakeVC:
    """จำลอง VoiceClient: เธรดเล่นเสียงดึง source.read() ทุก 20ms (ถ้า source เป็น mixer ก็ผ่านมันตลอด)"""
    def __init__(self):
        self.source = None
        self._thr = None
        self._run = False
        self.frames = []          # (เวลา, ระดับเสียงเฟรมนั้น)
        self.stopped_whole = False

    channel = None
    moves = None

    def is_connected(self): return True
    def is_playing(self): return self._run
    def is_paused(self): return False

    async def move_to(self, ch):
        self.moves = (self.moves or []) + [ch]
        self.channel = ch

    async def disconnect(self):
        self._run = False

    def play(self, source, after=None):
        if self._run:
            raise RuntimeError("Already playing audio.")
        self.source, self._run = source, True
        def loop():
            while self._run:
                b = source.read()
                if not b:
                    break
                self.frames.append((time.time(), int(np.frombuffer(b, dtype="<i2")[0])))
                time.sleep(0.02)
            self._run = False
            try:
                source.cleanup()
            finally:
                if after:
                    after(None)
        self._thr = threading.Thread(target=loop, daemon=True)
        self._thr.start()

    def stop(self):
        self.stopped_whole = True
        self._run = False


async def main():
    vc = FakeVC()
    music = Music()
    mixer = mx.DuckingMixer(music)
    vc.play(mixer)
    await asyncio.sleep(0.2)

    # 1) เสียงแจ้งเตือนซ้อนบนเพลง
    h = await tts.start_sfx(vc, SFX, volume=0.5)
    check("start_sfx returns a handle while music plays", h is not None)
    check("music NOT stopped by start_sfx", not vc.stopped_whole and vc.is_playing())
    await asyncio.sleep(0.6)
    lv = [v for _, v in vc.frames[-20:]]
    check("music ducked while alert plays", min(lv) < 10000, f"min={min(lv)}")

    # 2) stop เฉพาะเสียงแจ้งเตือน
    h.stop()
    check("handle.stop() ends only the alert", h.done.is_set() or await _wait(h))
    await asyncio.sleep(0.3)
    check("music still playing after alert stopped", vc.is_playing() and not vc.stopped_whole)
    await asyncio.sleep(0.8)
    check("music back to full volume afterwards", vc.frames[-1][1] == 10000, str(vc.frames[-1][1]))

    # 3) ไม่มีช่วงเงียบ/กระตุกของเพลง: ช่วงห่างระหว่างเฟรมต้องไม่เกิน ~120ms ตลอดช่วงที่เสียงแจ้งเตือนเล่น (เสียงซ้อนเริ่ม ffmpeg ใหม่)
    gaps = [b[0] - a[0] for a, b in zip(vc.frames, vc.frames[1:])]
    check("no music stall when overlay starts (max gap < 120ms)", max(gaps) < 0.12, f"max gap={max(gaps) * 1000:.0f}ms")

    # 4) พูดซ้อนด้วย play_and_wait (ทางเดียวกับ bagley_speak_wait) แล้วเพลงต้องไม่ถูกตัด
    t0 = time.time()
    await tts.play_and_wait(vc, SFX)
    check("play_and_wait over music returns after speech ends", 0.1 < time.time() - t0 < 10, f"{time.time() - t0:.2f}s")
    check("music not cut by play_and_wait", vc.is_playing() and not vc.stopped_whole)

    # 5) stop_speech_only ไม่แตะเพลง
    tts.stop_speech_only(vc)
    check("stop_speech_only leaves music alone", vc.is_playing() and not vc.stopped_whole)

    # 6) ไม่มีเพลง: start_sfx เล่นเดี่ยวและจบเอง
    vc.stop(); await asyncio.sleep(0.2); vc.stopped_whole = False
    vc2 = FakeVC()
    h2 = await tts.start_sfx(vc2, SFX, volume=0.5)
    check("start_sfx works with no music", h2 is not None)
    await h2.wait(timeout=10)
    check("standalone sfx finishes by itself", h2.done.is_set())
    check("missing file -> None (ไม่ล้ม)", await tts.start_sfx(vc2, "no_such.mp3") is None)


class Chan:
    def __init__(self, cid, guild): self.id, self.guild = cid, guild


class Guild:
    def __init__(self): self.id, self.voice_client = 1, None


async def alert_flow():
    """ทดสอบทางแจ้งเตือนจริงของบอท (_deliver_voice_reminder): ทั้งห้องเดียวกัน (พูดตรง) และต่างห้อง (วาร์ป) ต้องไม่ตัดเพลง"""
    from bagley.voice import alerts
    spoken = []

    async def fake_speak_wait(guild, text, filename=None, rate="+0%"):
        spoken.append(text)
        await tts.play_and_wait(guild.voice_client, SFX)     # พูดผ่านทางซ้อนเหมือนของจริง

    async def fake_line(situation, content):
        return f"เตือน {content} ครับ"

    alerts.bagley_speak_wait = fake_speak_wait
    alerts._gen_alert_line = fake_line

    for label, same_room in (("same room", True), ("other room (hijack)", False)):
        g = Guild()
        home, away = Chan(10, g), Chan(20, g)
        vc = FakeVC(); vc.channel = home
        g.voice_client = vc
        vc.play(mx.DuckingMixer(Music()))
        await asyncio.sleep(0.2)
        from bagley.core import state
        state.is_playing_music = True
        await alerts._deliver_voice_reminder(g, home if same_room else away, "ประชุม")
        check(f"[{label}] alert spoken (greeting+2 rounds)" if not same_room else f"[{label}] alert spoken twice",
              len(spoken) >= 2, str(len(spoken)))
        check(f"[{label}] music never stopped", vc.is_playing() and not vc.stopped_whole)
        if not same_room:
            check(f"[{label}] bot went to alert room then returned home", vc.moves == [away, home], str([m.id for m in vc.moves or []]))
        spoken.clear()
        vc._run = False
        await asyncio.sleep(0.1)


async def _wait(h):
    await h.wait(timeout=2)
    return h.done.is_set()

asyncio.run(main())
asyncio.run(alert_flow())
print("FAILED:", bad)
sys.exit(1 if bad else 0)
