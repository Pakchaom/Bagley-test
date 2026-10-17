"""
Bagley (แบ็คลี่) — Discord bot  |  จุดเริ่มต้นของโปรแกรม (ถาด/ start_hidden.bat เรียกไฟล์นี้เหมือนเดิม)

โครงสร้างโค้ดอยู่ในโฟลเดอร์ bagley/ แยกเป็นหมวด:
  core/      ค่าตั้งต้น, สถานะขณะรัน (state), บอทหลัก (app), สิทธิ์/ความปลอดภัย, log, http
  ai/        provider (ต่อ AI ฟรีตระกูล GPT + สลับสำรอง), persona (บุคลิกแบ็คลี่), gate (ด่านกรองเร็ว), router, classifiers
  voice/     tts (พูดเร็ว + แคชเสียง), alerts (วาร์ปเข้าห้องไปแจ้งเตือน)
  music/     player, spotify
  services/  youtube, youtube_live_chat, images, voice_relay
  features/  party, teams, stories, reminders, memory, members, rooms, rules, trust, learning, autonomy ...
  ui/        ปุ่ม/เมนู/ฟอร์ม
  tasks/     งานวนลูปเบื้องหลัง
  events/    on_message, on_voice_state_update, on_ready ...
  commands/  คำสั่งทั้งหมด แยกตามหมวด
  data/      อ่าน/เขียนไฟล์ JSON     db.py = SQLite     phrases.py = คลังคำพูด
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)                      # ไฟล์ข้อมูล (json/db/mp3) อ้างอิงโฟลเดอร์นี้เสมอ ไม่ว่าจะรันจากที่ไหน
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from bagley.core import config           # โหลด .env ก่อนอย่างอื่นทั้งหมด  # noqa: E402
from bagley.core.logutil import print    # noqa: E402,A004
from bagley.core.app import bot          # noqa: E402

# นำเข้าเพื่อให้คำสั่ง/อีเวนต์/ปุ่มลงทะเบียนกับบอท (ลำดับไม่สำคัญ)
from bagley.events import checks, lifecycle, message, voice_state    # noqa: E402,F401
from bagley.commands import admin, fun, listen, memory, music, reminders, voice, voice_access, youtube    # noqa: E402,F401
from bagley.ui import views              # noqa: E402,F401


def _install_clean_shutdown():
    from bagley.ai.provider import ai
    from bagley.core import http
    _orig_close = bot.close

    async def _close():
        for closer in (ai.close, http.close):
            try:
                await closer()
            except Exception:
                pass
        await _orig_close()

    bot.close = _close


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        print("❌ ไม่พบ DISCORD_TOKEN ในไฟล์ .env")
        sys.exit(1)
    _install_clean_shutdown()
    bot.run(config.DISCORD_TOKEN)
