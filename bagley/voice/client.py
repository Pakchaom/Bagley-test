"""bagley/voice/client.py — voice client ตัวเดียวของบอท (เล่นเสียงได้ + รับเสียงได้)

ทำไมต้องมีไฟล์นี้:
  VoiceRecvClient ของ discord-ext-voice-recv ทำให้ vc.stop() = "หยุดเล่น + หยุดฟัง" พร้อมกัน
  ดังนั้นทุกครั้งที่บอทสั่ง vc.stop() (/skip, /stop, เปลี่ยนเพลง, ตัดเสียงแจ้งเตือน, TTS timeout ...)
  ระบบฟังจะดับเงียบๆ โดยที่ session ใน listen.py ยังนึกว่าฟังอยู่  -> บอท "หูหนวก" จนกว่าจะ /listen on ใหม่
  ตัวนี้แก้ให้ stop() หยุดแค่การเล่น ส่วนการหยุดฟังต้องเรียก stop_listening() เองเท่านั้น

อีกอย่าง: ทุกที่ที่บอทเข้าห้องเสียง (เปิดเพลง / ตามเจ้านาย / แจ้งเตือน / ชวนตี้) ต้องใช้ connect_voice()
เพื่อให้ได้ client ชนิดที่รับเสียงได้เสมอ (เดิมใช้ channel.connect() เฉยๆ ได้ client ธรรมดา ฟังไม่ได้)
"""
from __future__ import annotations

import discord

try:
    from discord.ext import voice_recv
    HAVE_RECV = True

    class BagleyVoiceClient(voice_recv.VoiceRecvClient):
        def stop(self) -> None:                      # หยุดแค่การเล่น (ไม่แตะการฟัง)
            self.stop_playing()

        def cleanup(self) -> None:                   # ตอนตัดการเชื่อมต่อ ปิดทั้งการฟังและการเล่น
            try:
                self.stop_listening()
            except Exception:
                pass
            super().cleanup()
except Exception:                                    # ยังไม่ได้ติดตั้ง discord-ext-voice-recv
    voice_recv = None
    HAVE_RECV = False
    BagleyVoiceClient = discord.VoiceClient          # type: ignore[misc,assignment]


async def connect_voice(channel: discord.abc.Connectable, **kwargs) -> discord.VoiceClient:
    """เข้าห้องเสียงด้วย client ที่รับเสียงได้ (ใช้แทน channel.connect() ทุกที่)"""
    return await channel.connect(cls=BagleyVoiceClient, **kwargs)
