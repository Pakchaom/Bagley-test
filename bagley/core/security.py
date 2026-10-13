"""bagley/core/security.py — สิทธิ์ผู้ใช้ / ระบบแบนชั่วคราว / ตรวจคำหยาบ / โหมดสตรีม"""
import discord
from datetime import datetime, timedelta
from discord.ext import commands

from bagley.core import state
from bagley.core.app import bot
from bagley.core.config import ALLOWED_TEACH_USERS, OWNER_DISCORD_ID, bangkok_tz
from bagley.core.logutil import print
from bagley.features import autonomy as bagley_autonomy


# ============================================================
# 🎥 [โหมดสตรีม] ตัวช่วยเช็คสิทธิ์: ตอนเปิดโหมดสตรีมอยู่ ใครสั่งแบ็คลี่ได้บ้าง
# ============================================================
def is_stream_mode_on(guild_id) -> bool:
    """เช็คว่ากิลด์นี้เปิด 'โหมดสตรีม' อยู่หรือไม่ (ค่าเริ่มต้นคือปิด)"""
    if guild_id is None:
        return False
    return state.stream_mode_status.get(guild_id, False)


def is_stream_authorized(user, guild) -> bool:
    """เช็คว่า user คนนี้มีสิทธิ์สั่งแบ็คลี่ได้ระหว่างเปิดโหมดสตรีมอยู่หรือไม่
    เงื่อนไข: เป็นเจ้าของบอท/ผู้พัฒนา (ALLOWED_TEACH_USERS/OWNER_DISCORD_ID) หรือ
    เป็น 'คนที่กำลังสตรีมอยู่' (เปิด Go Live ในห้องเสียง หรือมีสถานะ Streaming เช่นสตรีมผ่าน Twitch)"""
    if user is None:
        return False
    if user.id == OWNER_DISCORD_ID or user.id in ALLOWED_TEACH_USERS:
        return True
    if guild is None:
        return False
    member = guild.get_member(user.id) if hasattr(guild, "get_member") else None
    if member is None:
        return False
    voice_state = getattr(member, "voice", None)
    if voice_state is not None and getattr(voice_state, "self_stream", False):
        return True  # กำลังกด Go Live (แชร์หน้าจอสตรีม) อยู่ในห้องเสียง
    for activity in (getattr(member, "activities", None) or []):
        if getattr(activity, "type", None) == discord.ActivityType.streaming:
            return True  # มีสถานะ "กำลังสตรีม" (เช่น เชื่อม Twitch ไว้กับ Discord)
    return False


# คำหยาบขั้นต้นไว้กรองก่อนยิงไปให้ AI ช่วยตัดสิน (ลดการเรียก AI โดยไม่จำเป็น)
RUDE_WORD_PATTERNS = [
    "เหี้ย", "สัส", "สัตว์", "ควย", "เย็ด", "แม่ง", "แม่มึง", "พ่อมึง", "ห่า", "ไอ้สัส",
    "ไอ้เหี้ย", "ไอ้ควย", "มึงโง่", "ตอแหล", "ชิบหาย", "อีดอก", "อีสัส", "กระหรี่",
    "fuck", "shit", "bitch", "asshole", "stupid bot", "dumb bot", "retard"
]


def _bagley_get_next_midnight_bkk():
    now = datetime.now(bangkok_tz)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def is_user_blocked(user_id: str) -> bool:
    """เช็กว่า user_id นี้โดนแบนคำสั่งของแบ็คลี่อยู่หรือไม่ (ปลดอัตโนมัติเมื่อพ้นเที่ยงคืน)"""
    block_until = state.blocked_users.get(user_id)
    if block_until is None:
        return False
    if datetime.now(bangkok_tz) >= block_until:
        del state.blocked_users[user_id]
        return False
    return True


def block_user_for_today(user_id: str):
    """แบนคำสั่ง/การตอบกลับของ user_id นี้ไปจนถึงเที่ยงคืน (เวลาไทย)"""
    state.blocked_users[user_id] = _bagley_get_next_midnight_bkk()


def unblock_user(user_id: str):
    """ปลดแบนคำสั่งของ user_id นี้ทันที (ใช้ตอนขอโทษ/ง้อสำเร็จ ไม่ต้องรอเที่ยงคืน)"""
    state.blocked_users.pop(user_id, None)


def is_message_addressed_to_bagley(lower_text: str) -> bool:
    """เช็กว่าข้อความนี้เอ่ยถึง/เรียกแบ็คลี่ตรงๆ หรือไม่"""
    mention_tag = f"<@{bot.user.id}>" if bot.user else None
    return (
        "แบ็คลี่" in lower_text
        or "bagley" in lower_text
        or (mention_tag is not None and mention_tag in lower_text)
    )


async def is_reply_to_bagley_message(message) -> bool:
    """เช็คว่าข้อความนี้เป็นการ 'ตอบกลับ (reply)' ข้อความใดๆ ที่แบ็คลี่เป็นคนพูด/พิมพ์ไว้ก่อนหน้าหรือไม่
    ครอบคลุมทั้งข้อความที่แบ็คลี่ทักขึ้นเอง (autonomy) และข้อความที่แบ็คลี่ตอบกลับคำสั่ง/คำถามของใครก็ตามมาก่อน
    ถ้าใช่ ให้ถือว่า 'เรียกแบ็คลี่แล้ว' เหมือนพิมพ์ชื่อ 'แบ็คลี่' ตรงๆ โดยไม่จำเป็นต้องพิมพ์ชื่อในข้อความที่ reply มาเลย
    (พฤติกรรมเดียวกับใน DM ที่ไม่ต้องพิมพ์ชื่อแบ็คลี่ก็คุยได้)
    """
    # ⚡ เช็คทางลัดที่เร็วที่สุดก่อน (ไม่ต้องยิง network) — ข้อความที่แบ็คลี่ทักขึ้นเอง
    if bagley_autonomy.is_reply_to_autonomous_message(message):
        return True

    ref = getattr(message, "reference", None)
    if ref is None or getattr(ref, "message_id", None) is None:
        return False
    if bot.user is None:
        return False

    resolved = getattr(ref, "resolved", None)
    try:
        if resolved is not None and hasattr(resolved, "author"):
            return resolved.author.id == bot.user.id
        # 🔄 Discord ไม่ได้แนบ resolved มาให้ (เช่น cache หมดอายุ) ต้องไปดึงข้อความจริงมาดูเองว่าใครเป็นคนพูด
        fetched = await message.channel.fetch_message(ref.message_id)
        return fetched.author.id == bot.user.id
    except Exception as e:
        print(f"⚠️ [Reply Detect] เช็คว่า reply ถึงข้อความของแบ็คลี่พลาด: {e}")
        return False


def has_potential_profanity(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in RUDE_WORD_PATTERNS)


def is_developer():
    # 🔧 [แก้ไข] เปลี่ยนจาก app_commands.check (ใช้ได้เฉพาะ interaction) เป็น commands.check
    # เพื่อให้ทำงานได้ทั้งตอนสั่งผ่าน /slash และตอนสั่งผ่าน hybrid_command (รวมถึง AI Router)
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.id in ALLOWED_TEACH_USERS
    return commands.check(predicate)
