"""ทดสอบเสียงขานรับ (ครับ/ค้าบ/ครับผม): สร้างไฟล์ถาวรครั้งเดียว, ไม่สร้างซ้ำ, โหลดเป็น PCM เฟรมเต็ม, สุ่มได้ทั้ง 3 คำ
ไม่ต้องใช้เน็ต/discord (จำลอง tts.synth ด้วยเสียงโทนจาก ffmpeg)   รัน: PYTHONPATH=. python3 tests/test_ack.py"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import types

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


tmp = tempfile.mkdtemp()
os.environ["VOICE_ACK_DIR"] = os.path.join(tmp, "voice_ack")

calls = []
fake = types.ModuleType("bagley.voice.tts")
fake.TTS_VOICE = "th-TH-NiwatNeural"
fake.FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"


async def fake_synth(text, voice=None, rate="+0%"):
    calls.append(text)
    p = os.path.join(tmp, f"src_{len(calls)}.mp3")
    subprocess.run([fake.FFMPEG_PATH, "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.15",
                    "-f", "lavfi", "-i", "sine=f=440:d=0.4", "-filter_complex", "[0][1]concat=n=2:v=0:a=1",
                    "-y", p], check=True)   # เงียบนำหน้าแล้วตามด้วยโทน เพื่อเช็กการตัดเงียบ
    return p


fake.synth = fake_synth
sys.modules["bagley.voice.tts"] = fake

from bagley.voice import ack  # noqa: E402

n = asyncio.run(ack.ensure_loaded())
check("โหลดครบ 3 คำ", n == 3, f"n={n}")
check("สร้างไฟล์ 3 ครั้ง", len(calls) == 3, str(calls))
files = sorted(os.listdir(ack.ACK_DIR))
check("มีไฟล์ถาวร 3 ไฟล์", len(files) == 3 and all(f.endswith(".mp3") for f in files), str(files))

ack._pcm.clear()                                  # จำลองเปิดบอทใหม่
n2 = asyncio.run(ack.ensure_loaded())
check("เปิดใหม่ไม่สร้างไฟล์ซ้ำ", n2 == 3 and len(calls) == 3, f"calls={len(calls)}")
check("PCM เป็นเฟรม 20ms เต็ม", all(len(b) % 3840 == 0 and len(b) > 0 for b in ack._pcm.values()))
check("ตัดเงียบหัวไฟล์แล้ว (สั้นกว่า 0.55 วิ)", all(len(b) < 48000 * 4 * 0.55 for b in ack._pcm.values()),
      str({k: round(len(b) / 192000, 2) for k, b in ack._pcm.items()}))

seen = {id(ack.pick_pcm()) for _ in range(200)}
check("สุ่มได้ทั้ง 3 เสียง", len(seen) == 3, f"seen={len(seen)}")

ack._pcm.clear()
check("ยังไม่โหลด -> pick_pcm เป็น None (ใช้ติ๊ดสำรอง)", ack.pick_pcm() is None)

shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
