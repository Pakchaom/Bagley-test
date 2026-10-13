# ============================================================
# 🏷️🔒 ระบบเปลี่ยนชื่อห้องชั่วคราว + ล็อกห้องเป็นห้องส่วนตัว
# ============================================================
# วางไฟล์นี้ไว้ข้าง bot.py แล้ว `import bagley_rooms`
#
# มีอะไรบ้าง:
#   1. rename_room_temp(channel, new_name, actor) -> เปลี่ยนชื่อห้องเสียง
#      (จำชื่อเดิมไว้อัตโนมัติ ถ้ายังไม่เคยเปลี่ยนมาก่อน)
#   2. lock_room_private(channel, actor) -> ล็อกห้องเป็นห้องส่วนตัว
#      (บันทึก permission overwrites เดิมไว้ทั้งหมดก่อนแก้)
#   3. unlock_room_private(channel, reason) -> ปลดล็อกคืนสภาพเดิม
#   4. watch_voice_state(member, before, after) -> ผูกกับ event
#      on_voice_state_update ของ discord.py (ใช้ bot.add_listener(...))
#      พอห้องที่ถูกเปลี่ยนชื่อ/ล็อกไว้ "ไม่มีคนจริงเหลืออยู่แล้ว" (นับเฉพาะ
#      สมาชิกที่ไม่ใช่บอท) จะรีเซ็ตชื่อ/ปลดล็อกกลับเป็นค่าเดิมให้อัตโนมัติทันที
#
# หมายเหตุ: ทั้งสองระบบนี้ตั้งใจให้ AI Command Router ของ bot.py เรียกได้เองด้วย
# (ผ่าน hybrid_command ที่ bot.py เป็นคนประกาศ ไฟล์นี้แค่เก็บ state + ลอจิกจริง)
# ============================================================

import discord

# channel_id -> ชื่อห้องเดิมก่อนถูกเปลี่ยน (ยังไม่ได้เปลี่ยนกลับ)
renamed_voice_rooms: dict[int, str] = {}

# channel_id -> {"original_overwrites": {...}, "locked_by": user_id}
locked_voice_rooms: dict[int, dict] = {}


# ------------------------------------------------------------
# 🏷️ เปลี่ยนชื่อห้องชั่วคราว
# ------------------------------------------------------------
async def rename_room_temp(channel: discord.VoiceChannel, new_name: str, actor: discord.Member) -> str:
    """เปลี่ยนชื่อห้องเสียงชั่วคราว คืนค่าชื่อห้อง 'เดิม' ที่จำไว้ (เผื่อเอาไปพูด/แจ้งผู้ใช้)"""
    if channel.id not in renamed_voice_rooms:
        renamed_voice_rooms[channel.id] = channel.name

    original_name = renamed_voice_rooms[channel.id]

    await channel.edit(name=new_name, reason=f"เปลี่ยนชื่อห้องชั่วคราวโดย {actor.display_name}")
    return original_name


async def revert_room_name_if_needed(channel: discord.VoiceChannel) -> bool:
    """เปลี่ยนชื่อห้องกลับเป็นชื่อเดิม (เรียกตอนห้องว่างแล้ว) คืนค่า True ถ้าทำสำเร็จ"""
    original_name = renamed_voice_rooms.pop(channel.id, None)
    if not original_name:
        return False
    try:
        await channel.edit(name=original_name, reason="ห้องว่างแล้ว - เปลี่ยนชื่อกลับอัตโนมัติ")
        return True
    except Exception as e:
        print(f"❌ [bagley_rooms] เปลี่ยนชื่อห้อง '{channel.name}' กลับเป็น '{original_name}' ไม่สำเร็จ: {e}")
        return False


# ------------------------------------------------------------
# 🔒 ล็อกห้องเป็นห้องส่วนตัว
# ------------------------------------------------------------
async def lock_room_private(channel: discord.VoiceChannel, actor: discord.Member):
    """ล็อกห้องเสียง: ปิดสิทธิ์เข้าห้อง (connect) ของ @everyone แต่เปิดให้เฉพาะคนที่อยู่ในห้อง
    ตอนสั่งล็อก (รวมถึงตัวบอทเองด้วย กันบอทเข้าห้องที่ตัวเองล็อกไว้ไม่ได้) เก็บ overwrites
    เดิมทั้งหมดไว้ก่อน เพื่อเอาไปคืนสภาพตอนปลดล็อก"""
    original_overwrites = dict(channel.overwrites)

    new_overwrites = dict(original_overwrites)

    everyone_role = channel.guild.default_role
    everyone_ow = channel.overwrites_for(everyone_role)
    everyone_ow.connect = False
    new_overwrites[everyone_role] = everyone_ow

    allowed_targets = list(channel.members)  # คนที่อยู่ในห้อง ณ ตอนล็อก (รวมทั้งคนและบอทที่อยู่ในห้อง)
    for target in allowed_targets:
        target_ow = channel.overwrites_for(target)
        target_ow.connect = True
        new_overwrites[target] = target_ow

    # กันเผื่อบอทเองไม่ได้อยู่ในห้องตอนถูกสั่งล็อก ก็ยังต้องเข้าห้องนี้ได้เสมอ
    me = channel.guild.me
    if me not in allowed_targets:
        me_ow = channel.overwrites_for(me)
        me_ow.connect = True
        new_overwrites[me] = me_ow

    await channel.edit(overwrites=new_overwrites, reason=f"ล็อกห้องส่วนตัวโดย {actor.display_name}")

    locked_voice_rooms[channel.id] = {
        "original_overwrites": original_overwrites,
        "locked_by": actor.id,
    }


async def unlock_room_private(channel: discord.VoiceChannel, reason: str = "ปลดล็อกห้อง") -> bool:
    """คืนสิทธิ์ห้องกลับไปเป็นแบบก่อนล็อกทุกอย่าง คืนค่า True ถ้าทำสำเร็จ (False ถ้าห้องนี้ไม่ได้ถูกล็อกอยู่)"""
    data = locked_voice_rooms.pop(channel.id, None)
    if not data:
        return False
    try:
        await channel.edit(overwrites=data["original_overwrites"], reason=reason)
        return True
    except Exception as e:
        print(f"❌ [bagley_rooms] ปลดล็อกห้อง '{channel.name}' ไม่สำเร็จ: {e}")
        return False


# ------------------------------------------------------------
# 👀 เฝ้าห้องที่เปลี่ยนชื่อ/ล็อกไว้ พอห้องว่างจากคนจริงแล้ว รีเซ็ตให้อัตโนมัติ
# ------------------------------------------------------------
async def watch_voice_state(member, before, after):
    """ผูกกับ on_voice_state_update ผ่าน bot.add_listener(...) (ไม่แทนที่ event หลักของ bot.py)
    เช็คเฉพาะห้อง 'ที่มีคนเพิ่งออกไป' (before.channel) ว่าเป็นห้องที่อยู่ในทะเบียนเปลี่ยนชื่อ/ล็อกไว้
    หรือไม่ ถ้าใช่และตอนนี้ไม่มีสมาชิกจริง (ไม่นับบอท) เหลืออยู่แล้ว ให้รีเซ็ตกลับเป็นค่าเดิมทันที"""
    if before.channel is None or before.channel == after.channel:
        return

    channel = before.channel
    if channel.id not in renamed_voice_rooms and channel.id not in locked_voice_rooms:
        return

    remaining_humans = len([m for m in channel.members if not m.bot])
    if remaining_humans > 0:
        return

    if channel.id in renamed_voice_rooms:
        reverted = await revert_room_name_if_needed(channel)
        if reverted:
            print(f"🔄 [bagley_rooms] ห้อง '{channel.name}' ว่างแล้ว เปลี่ยนชื่อกลับเป็นค่าเดิมอัตโนมัติเรียบร้อยครับ")

    if channel.id in locked_voice_rooms:
        unlocked = await unlock_room_private(channel, reason="ห้องว่างแล้ว - ปลดล็อกอัตโนมัติ")
        if unlocked:
            print(f"🔓 [bagley_rooms] ห้อง '{channel.name}' ว่างแล้ว ปลดล็อกกลับเป็นห้องปกติอัตโนมัติเรียบร้อยครับ")
