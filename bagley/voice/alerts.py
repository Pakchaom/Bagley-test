"""bagley/voice/alerts.py — แจ้งเตือนด้วยเสียง: วาร์ปเข้าห้องไปพูด (hijack), โควต้าคำสั่งเสียง"""
import asyncio
from datetime import datetime

from bagley.ai import persona
from bagley.core import state
from bagley.core.app import client
from bagley.core.logutil import print
from bagley.phrases import say
from bagley.voice.client import connect_voice
from bagley.voice.tts import bagley_speak, bagley_speak_wait, start_sfx


async def bagley_speak_reminder_direct(guild, content):
    """พูดแจ้งเตือนตรงๆ ในห้องเสียงที่ผู้ใช้อยู่ด้วยอยู่แล้ว (ไม่ต้องวาร์ปห้อง ไม่มีเสียงโดรน ไม่ทักทายว่าไฮแจ็ค) แล้วพูดย้ำอีก 1 รอบ
    ซ้อนบนเพลงที่กำลังเล่นอยู่ได้ (ไม่ตัดเพลง)"""
    alert_text = await _gen_alert_line(
        "คุณกำลังพูดแจ้งเตือนเรื่องสำคัญให้คุณที่อยู่ในห้องเสียงเดียวกันฟัง", content)
    for i in range(2):
        text_to_say = f"ย้ำอีกครั้งครับ! {alert_text}" if i == 1 else alert_text
        await bagley_speak_wait(guild, text_to_say, filename=f"inroom_alert_{i}")
        if i == 0:
            await asyncio.sleep(0.8)


async def _gen_alert_line(situation: str, content: str) -> str:
    """ให้ AI เรียบเรียงประโยคแจ้งเตือน 1 ประโยค (พังหรือว่าง -> ใช้ประโยคสำรอง)"""
    try:
        prompt = f"""
        {persona.BRIEF}
สถานการณ์: {situation}
        หน้าที่: เจนประโยคแจ้งเตือนสั้นๆ เป็นธรรมชาติ 1 ประโยค โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

        [เนื้อหาที่ต้องแจ้งเตือน]: {content}

        กฎ: พูดแบบเป็นกันเอง ลงท้ายประโยคด้วย "ครับ" เฉยๆ ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น
        """
        response = await client.aio.models.generate_content(model="chat", contents=prompt)
        text = (response.text or "").strip()
        if text:
            return text
        raise ValueError("AI ตอบข้อความว่างเปล่า")
    except Exception as ai_err:
        print(f"❌ AI เจนคำแจ้งเตือนพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
        return f"แจ้งเตือนเรื่อง {content} ครับ"


async def bagley_hijack_alert(voice_channel, message_text):
    """วาร์ปไปห้องของเป้าหมาย -> ทักทาย -> แจ้งเตือนย้ำ 2 รอบ -> วาร์ปกลับห้องเดิม

    เพลงที่เล่นอยู่ "ไม่ถูกตัด": เสียงโดรน/เสียงพูดทั้งหมดซ้อนบนเพลง (เพลงหรี่ลงชั่วคราว)
    และเพลงจะตามบอทไปห้องเป้าหมายแล้วตามกลับมาห้องเดิมด้วย (วาร์ปด้วย voice client ตัวเดิม)
    """
    vc = None
    guild = voice_channel.guild
    old_channel = None
    moved = False

    try:
        # --- 🧠 1. จำห้องเดิมของ Bagley ---
        if guild.voice_client and guild.voice_client.channel:
            old_channel = guild.voice_client.channel

        # --- 🚀 2. เชื่อมต่อ/ย้ายห้อง ---
        if guild.voice_client:
            await guild.voice_client.move_to(voice_channel)
            vc = guild.voice_client
        else:
            vc = await connect_voice(voice_channel)
        moved = True

        await asyncio.sleep(1.2)

        # --- 🔊 3. เสียงโดรน online (ซ้อนบนเพลงได้) แล้วเฟดออกก่อนพูด ---
        sfx = await start_sfx(vc, 'drone_online.mp3', volume=0.6)
        if sfx:
            await asyncio.sleep(3.5)
            await sfx.fade_out(1.5, 15)
            sfx.stop()

        # --- 💬 4. ทักทาย ---
        await bagley_speak_wait(guild, "ไฮแจ๊คสำเร็จ สวัสดีครับ ผมแบ็คลี่นะครับ", filename="greeting")
        await asyncio.sleep(0.5)

        # --- 📢 5. แจ้งเตือนย้ำ 2 รอบ ---
        repeat_text = await _gen_alert_line(
            "คุณกำลังไฮแจ็คห้องเสียงเพื่อมาแจ้งเตือนเรื่องสำคัญให้คุณฟัง", message_text)
        for i in range(2):
            text_to_say = f"ย้ำอีกครั้งครับ! {repeat_text}" if i == 1 else repeat_text
            await bagley_speak_wait(guild, text_to_say, filename=f"alert_{i}")
            await asyncio.sleep(0.8)

        # --- 🔊 6. เสียงโดรน hijack ปิดท้าย (เฟดออก) ---
        sfx = await start_sfx(vc, 'drone_hijack.mp3', volume=0.5)
        if sfx:
            await asyncio.sleep(1.5)
            await sfx.fade_out(1.0, 10)
            sfx.stop()
        await asyncio.sleep(0.5)

    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการ Hijack: {e}")
    finally:
        # --- 🔄 7. วาร์ปกลับห้องเดิม (หรือวางสายถ้าก่อนหน้านี้ไม่ได้อยู่ห้องไหน) ---
        # ทำใน finally เสมอ: เดิมถ้าพังกลางทางหลังย้ายห้องไปแล้ว บอทจะค้างอยู่ห้องเป้าหมาย
        # (เดิมเช็คแค่ "ไม่มีห้องเก่า -> ตัดสาย" แต่ถ้ามีห้องเก่าจะไม่ถูกพากลับ)
        try:
            vc = guild.voice_client or vc
            if vc is not None and vc.is_connected() and moved:
                if old_channel and old_channel != voice_channel:
                    await vc.move_to(old_channel)
                elif not old_channel:
                    await vc.disconnect()
        except Exception as back_err:
            print(f"⚠️ [Hijack] วาร์ปกลับห้องเดิมไม่สำเร็จ: {back_err}")


async def _deliver_voice_reminder(guild, target_voice_channel, content):
    """เลือกวิธีแจ้งเตือนด้วยเสียงให้เหมาะกับสถานะปัจจุบันของบอท ใช้ร่วมกันทั้งระบบ
    เตือนตัวเอง/เพื่อน (reminders) และระบบตารางนัด (schedules):
    - บอทอยู่ห้องเดียวกับเป้าหมายแล้ว -> พูดตรงๆ ไม่ต้องวาร์ป
    - ไม่ได้อยู่ห้องเดียวกัน -> วาร์ปไปเตือนผ่าน bagley_hijack_alert แล้ววาร์ปกลับให้อัตโนมัติ

    🎵 แจ้งเตือน "ซ้อนบนเพลง" ไม่ตัดเพลงอีกต่อไป: เพลงหรี่ลงตอนพูดแล้วดังกลับเอง
    (เดิมสั่ง vc.stop() ตัดเพลงทิ้งแล้วเอาเพลงกลับมาเริ่มใหม่ตั้งแต่ต้น)
    ส่วนเสียงพูดอื่นๆ (ไม่ใช่เพลง) ยังต่อคิวพูดต่อกันตามเดิมผ่าน bagley_speak_wait ไม่ตัดกลางประโยค
    """
    if not target_voice_channel:
        return

    vc = guild.voice_client if guild else None
    if vc and vc.is_connected() and vc.channel and vc.channel.id == target_voice_channel.id:
        await bagley_speak_reminder_direct(guild, content)
    else:
        await bagley_hijack_alert(target_voice_channel, content)


async def check_shared_voice_quota(user_id, guild):
    now = datetime.now()
    # ดึงข้อมูลโควตาของ user นั้นมา
    user_times = state.voice_action_cooldowns.get(user_id, [])
    
    # กรองเอาเฉพาะที่ใช้ไปใน 60 วินาทีล่าสุด
    user_times = [t for t in user_times if (now - t).total_seconds() < 60]
    
    if len(user_times) >= 3:
        remaining = 60 - (now - user_times[0]).total_seconds()
        await bagley_speak(guild, say("voice_spam_wait", sec=int(remaining)))
        return False, int(remaining)

    # ถ้ายังไม่เกิน เพิ่มเวลาครั้งนี้เข้าไป
    user_times.append(now)
    state.voice_action_cooldowns[user_id] = user_times
    return True, 0


async def fade_out_source(vc, duration=1.5, steps=15):
    """ ค่อยๆ ลดเสียงลงจนเงียบแล้วหยุดเล่น """
    if vc and vc.source and hasattr(vc.source, 'volume'):
        initial_volume = vc.source.volume
        wait_time = duration / steps
        volume_step = initial_volume / steps

        for _ in range(steps):
            if vc and vc.source:
                new_vol = max(0, vc.source.volume - volume_step)
                vc.source.volume = new_vol
                await asyncio.sleep(wait_time)
            else:
                break
        if vc.is_playing():
            vc.stop()
