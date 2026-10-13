"""bagley/services/voice_relay.py — Voice Relay: รับคำสั่งเสียงจาก mic_to_discord.py ผ่าน HTTP ในเครื่อง"""
import time
from aiohttp import web
from datetime import datetime, timezone

from bagley.core.app import bot
from bagley.core.config import VOICE_RELAY_ALLOWED_OWNER_IDS, VOICE_RELAY_HOST, VOICE_RELAY_PORT
from bagley.core.logutil import print
from bagley.events.message import on_message


class VoiceRelayMessage:
    """ตัวปลอมแทน discord.Message สำหรับส่งคำสั่งเสียงตรงเข้า on_message
    เพื่อให้ระบบเดิม (voice_keywords, ระบบสิทธิ์ ฯลฯ) ทำงานได้เหมือนเดิม
    ทุกอย่าง โดยไม่ต้องพึ่ง Discord Webhook อีกต่อไป"""

    def __init__(self, content, author, guild, channel):
        self.content = content
        self.clean_content = content
        self.author = author
        self.guild = guild
        self.channel = channel
        self.mentions = []
        self.mention_everyone = False
        self.attachments = []
        self.embeds = []
        # 🔧 [แก้บั๊ก] discord.py ภายใน (เช่น ctx.send() ที่ใช้กับคำสั่งที่เรียก
        # ผ่าน bot.get_command()+ctx.invoke() อย่าง leave/move/mute) ต้องพึ่ง
        # message._state (ConnectionState) เพื่อไปอ่าน .allowed_mentions ฯลฯ
        # ถ้าไม่มีจะพังด้วย "'NoneType' object has no attribute 'allowed_mentions'"
        # ยืมมาจาก guild._state ได้เลยเพราะเป็น ConnectionState ตัวเดียวกัน
        self._state = guild._state
        # ✅ ใช้ตัวบอกสถานะของตัวเองแทนการสวมรอยเป็น Webhook ID จริง เพื่อไม่ให้
        # ปนกับ Discord Webhook จริงจากภายนอก (ที่ปิดใช้งานไปแล้วด้านล่างใน on_message)
        self.is_voice_relay_command = True
        self.webhook_id = None
        self.id = int(time.time() * 1000)
        self.created_at = datetime.now(timezone.utc)

    async def reply(self, content=None, **kwargs):
        return await self.channel.send(content, **kwargs)

    async def delete(self, *args, **kwargs):
        pass  # ข้อความนี้ไม่มีตัวตนจริงบน Discord จึงไม่มีอะไรให้ลบ

    def __getattr__(self, name):
        # กัน AttributeError หลุดสำหรับแอตทริบิวต์ปลีกย่อยที่ไม่เกี่ยวกับ
        # คำสั่งเสียง (เช่น message.reference, message.flags ฯลฯ)
        return None


async def handle_voice_command(request: "web.Request"):
    try:
        data = await request.json()
        text = (data.get("text") or "").strip()
        owner_id_raw = data.get("owner_id")
        owner_id = int(owner_id_raw) if owner_id_raw is not None else None
    except Exception:
        return web.json_response({"status": "error", "message": "invalid json"}, status=400)

    if not text:
        return web.json_response({"status": "error", "message": "empty text"}, status=400)

    if owner_id not in VOICE_RELAY_ALLOWED_OWNER_IDS:
        print(f"🔒 [Voice Relay] มีคนพยายามส่งคำสั่งเสียงด้วย owner_id ที่ไม่ได้รับอนุญาต: {owner_id_raw}")
        return web.json_response({"status": "error", "message": "unauthorized owner_id"}, status=403)

    # หาว่าคนที่พูด (owner_id) อยู่ในห้องเสียงของเซิร์ฟเวอร์ไหนอยู่ตอนนี้ (auto-detect
    # ทำให้ไม่ต้องตั้งค่า guild/channel ล่วงหน้า ใช้ได้ทุกเซิร์ฟเวอร์ทันที)
    target_channel = None
    target_guild = None
    for guild in bot.guilds:
        member = guild.get_member(owner_id)
        if member and member.voice and member.voice.channel:
            target_channel = member.voice.channel
            target_guild = guild
            break

    if target_channel is None:
        print(f"🎙️ [Voice Relay] ไม่พบว่าเจ้าของไอดี {owner_id} อยู่ในห้องเสียงของเซิร์ฟเวอร์ไหนเลยตอนนี้")
        return web.json_response({"status": "no_voice_channel"}, status=404)

    member_author = target_guild.get_member(owner_id)
    fake_message = VoiceRelayMessage(
        content=text,
        author=member_author,
        guild=target_guild,
        channel=target_channel,
    )

    try:
        await on_message(fake_message)
    except Exception as e:
        print(f"🎙️ [Voice Relay] เกิดข้อผิดพลาดระหว่างประมวลผล: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

    return web.json_response({"status": "ok"})


async def start_voice_relay_server():
    app = web.Application()
    app.router.add_post("/voice_command", handle_voice_command)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, VOICE_RELAY_HOST, VOICE_RELAY_PORT)
    await site.start()
    print(f"🎙️ [Voice Relay] พร้อมรับคำสั่งเสียงที่ http://{VOICE_RELAY_HOST}:{VOICE_RELAY_PORT}/voice_command")
