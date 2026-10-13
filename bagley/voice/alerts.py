"""bagley/voice/alerts.py — แจ้งเตือนด้วยเสียง: วาร์ปเข้าห้องไปพูด (hijack), โควต้าคำสั่งเสียง"""
import asyncio
import discord
from datetime import datetime

from bagley.ai import persona
from bagley.core import state
from bagley.core.app import client
from bagley.core.logutil import print
from bagley.phrases import say
from bagley.voice.tts import FFMPEG_PATH, bagley_speak, bagley_speak_wait


async def bagley_speak_reminder_direct(guild, content):
    """พูดแจ้งเตือนตรงๆ ในห้องเสียงที่ผู้ใช้อยู่ด้วยอยู่แล้ว (ไม่ต้องวาร์ปห้อง ไม่มีเสียงโดรน ไม่ทักทายว่าไฮแจ็ค) แล้วพูดย้ำอีก 1 รอบ"""
    try:
        prompt = f"""
        {persona.BRIEF}
สถานการณ์: คุณกำลังพูดแจ้งเตือนเรื่องสำคัญให้คุณที่อยู่ในห้องเสียงเดียวกันฟัง
        หน้าที่: เจนประโยคแจ้งเตือนสั้นๆ เป็นธรรมชาติ 1 ประโยค โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

        [เนื้อหาที่ต้องแจ้งเตือน]: {content}

        กฎ: พูดแบบเป็นกันเอง ลงท้ายประโยคด้วย "ครับ" เฉยๆ ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น
        """
        response = await client.aio.models.generate_content(model="chat", contents=prompt)
        alert_text = (response.text or "").strip()
        if not alert_text:
            raise ValueError("AI ตอบข้อความว่างเปล่า")
    except Exception as ai_err:
        print(f"❌ AI เจนคำแจ้งเตือนในห้อง (ไม่ hijack) พัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
        alert_text = f"แจ้งเตือนเรื่อง {content} ครับ"

    for i in range(2):
        text_to_say = f"ย้ำอีกครั้งครับ! {alert_text}" if i == 1 else alert_text
        await bagley_speak_wait(guild, text_to_say, filename=f"inroom_alert_{i}")
        if i == 0:
            await asyncio.sleep(0.8)


async def bagley_hijack_alert(voice_channel, message_text):
    vc = None
    guild = voice_channel.guild
    old_channel = None
    
    try:
        # --- 🧠 1. ส่วนจำห้องเดิมของ Bagley ---
        # ถ้าบอทอยู่ในห้องเสียงสักห้องของเซิร์ฟเวอร์นี้ ให้จำห้องนั้นไว้ก่อนวาร์ป
        if guild.voice_client and guild.voice_client.channel:
            old_channel = guild.voice_client.channel

        # --- 🚀 2. ส่วนการเชื่อมต่อ/ย้ายห้องเสียงแบบปลอดภัย ---
        if guild.voice_client:
            # ถ้าบอทอยู่ในห้องเสียงอยู่แล้ว (เช่น นั่งอยู่กับคุณ) ให้ใช้สั่งย้ายห้องแทน
            await guild.voice_client.move_to(voice_channel)
            vc = guild.voice_client
        else:
            # ถ้าบอทยังไม่ได้เข้าห้องไหนเลย ค่อยกด Connect ใหม่
            vc = await voice_channel.connect()
            
        await asyncio.sleep(1.2)
        
        # --- 🔊 3. ส่วนเสียง online (เฟดออกก่อนพูด) ---
        hijack_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_online.mp3', executable=FFMPEG_PATH)
        )
        hijack_source.volume = 0.6
        vc.play(hijack_source)

        await asyncio.sleep(3.5) 
        
        steps = 15
        fade_duration = 1.5
        for _ in range(steps):
            if hijack_source:
                hijack_source.volume = max(0, hijack_source.volume - (0.6 / steps))
                await asyncio.sleep(fade_duration / steps)
        
        if vc.is_playing(): vc.stop()

        # --- 💬 4. ส่วนทักทาย ---
        greeting = "ไฮแจ๊คสำเร็จ สวัสดีครับ ผมแบ็คลี่นะครับ"
        await bagley_speak_wait(guild, greeting, filename="greeting")
        await asyncio.sleep(0.5)

        # --- 📢 5. ส่วนแจ้งเตือนย้ำ 2 รอบ ---
        try:
            hijack_prompt = f"""
            {persona.BRIEF}
สถานการณ์: คุณกำลังไฮแจ็คห้องเสียงเพื่อมาแจ้งเตือนเรื่องสำคัญให้คุณฟัง
            หน้าที่: เจนประโยคแจ้งเตือนสั้นๆ เป็นธรรมชาติ 1 ประโยค โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

            [เนื้อหาที่ต้องแจ้งเตือน]: {message_text}

            กฎ: พูดแบบเป็นกันเอง ลงท้ายประโยคด้วย "ครับ" เฉยๆ ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น
            """
            hijack_response = await client.aio.models.generate_content(model="chat", contents=hijack_prompt)
            repeat_text = (hijack_response.text or "").strip()
            if not repeat_text:
                raise ValueError("AI ตอบข้อความว่างเปล่า")
        except Exception as ai_err:
            print(f"❌ AI เจนคำแจ้งเตือน Hijack พัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
            repeat_text = f"แจ้งเตือนเรื่อง {message_text} ครับ"

        for i in range(2):
            text_to_say = f"ย้ำอีกครั้งครับ! {repeat_text}" if i == 1 else repeat_text
            await bagley_speak_wait(guild, text_to_say, filename=f"alert_{i}") 
            await asyncio.sleep(0.8) 
            
        # --- 🔊 6. เสียง Drone hijack (เฟดออกก่อนจบ) ---
        online_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=FFMPEG_PATH)
        )
        online_source.volume = 0.5
        vc.play(online_source)
        
        await asyncio.sleep(1.5)

        for _ in range(10):
            if online_source:
                online_source.volume = max(0, online_source.volume - (0.5 / 10))
                await asyncio.sleep(0.1)

        if vc.is_playing(): vc.stop()
        await asyncio.sleep(0.5)
        
        # --- 🔄 7. ส่วนการวาร์ปกลับห้องเดิม (หรือวางสายถ้าไม่มีห้องเก่า) ---
        # ถ้ามีห้องเก่าเก็บไว้ และห้องเก่าไม่ใช่ห้องที่เราเพิ่งวาร์ปมาเตือน ให้บอทย้ายกลับไปหา
        if old_channel and old_channel != voice_channel:
            await vc.move_to(old_channel)
        else:
            # แต่ถ้าก่อนหน้านี้บอทไม่ได้อยู่ห้องไหนเลย ก็สั่งตัดการเชื่อมต่อ (Disconnect) ตามปกติ
            await vc.disconnect()
        
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการ Hijack: {e}")
        # ถ้าเกิด Error และบอทไม่ได้จำห้องเก่าไว้ ค่อยตัดการเชื่อมต่อเพื่อความปลอดภัย
        if vc and not old_channel: 
            await vc.disconnect()


async def _deliver_voice_reminder(guild, target_voice_channel, content):
    """เลือกวิธีแจ้งเตือนด้วยเสียงให้เหมาะกับสถานะปัจจุบันของบอท ใช้ร่วมกันทั้งระบบ
    เตือนตัวเอง/เพื่อน (reminders) และระบบตารางนัด (schedules):
    - ถ้าบอทอยู่ในห้องเสียงเดียวกับเป้าหมายอยู่แล้ว -> พูดตรงๆ เลย ไม่ต้องวาร์ป (เงียบกว่า ไม่รบกวนจังหวะ)
    - ถ้าบอทไม่ได้อยู่ห้องเดียวกัน (อยู่ห้องอื่นของกิลด์นี้ หรือไม่ได้เชื่อมต่อเสียงเลย) -> วาร์ปเข้าไปเตือน
      ผ่าน bagley_hijack_alert แล้ววาร์ปกลับห้องเดิมให้อัตโนมัติ (หรือออกจากห้องถ้าเดิมไม่ได้อยู่ไหนเลย)"""
    if not target_voice_channel:
        return

    # 🚨 [ใหม่] แจ้งเตือนสำคัญกว่าเพลงเสมอ: ถ้าบอทกำลังเปิดเพลง/พูดอะไรอยู่ตอนถึงเวลาต้องแจ้งเตือน
    # ให้ตัดจบเสียง/เพลงที่เล่นอยู่ทันที ไม่ต้องรอให้จบก่อนเหมือนเดิม (เดิม bagley_speak_wait จะรอ
    # vc.is_playing() จนกว่าเพลงจะจบเองก่อนถึงจะพูดแจ้งเตือน ทำให้แจ้งเตือนล่าช้าได้)
    interrupted_search = None
    vc_now = guild.voice_client if guild else None
    if vc_now and vc_now.is_connected() and vc_now.is_playing():
        state.priority_alert_active_guilds.add(guild.id)
        # เอาเพลงกลับมาเข้าคิวใหม่เฉพาะตอนที่สิ่งที่กำลังเล่นอยู่คือ "เพลง" จริงๆ (is_playing_music)
        # เท่านั้น กันเคสตัดจบทับเสียงพูด TTS ธรรมดา (ทักทาย/ตอบแชท) แล้วดันเอาเพลงเก่าที่จบไปนานแล้ว
        # กลับมาเล่นซ้ำแบบผิดๆ
        if state.is_playing_music:
            interrupted_search = state.current_playing_search.get(guild.id)
        try:
            vc_now.stop()  # ตัดจบเพลง/เสียงที่กำลังเล่นอยู่ทันที
            print(f"⏹️ [Priority Alert] ตัดจบเพลง/เสียงในกิลด์ {guild.id} เพื่อวาร์ปไปแจ้งเตือนก่อนครับ")
        except Exception as e:
            print(f"⚠️ [Priority Alert] ตัดจบเพลงไม่สำเร็จ: {e}")
        # เผื่อเวลาเล็กน้อยให้ callback ของเพลงเดิม (after_playing/_after) เคลียร์ตัวเองให้เสร็จก่อน
        await asyncio.sleep(0.3)

    try:
        vc = guild.voice_client
        if vc and vc.is_connected() and vc.channel and vc.channel.id == target_voice_channel.id:
            await bagley_speak_reminder_direct(guild, content)
        else:
            await bagley_hijack_alert(target_voice_channel, content)
    finally:
        if interrupted_search:
            # 🎵 แจ้งเตือนเสร็จแล้ว เอาเพลงที่โดนตัดจบไปกลางคันกลับมาเข้าคิวไว้อันดับแรก
            # ฟังก์ชัน check_queue ที่ถูกคิวไว้อัตโนมัติตอนสั่ง vc.stop() ด้านบน (ผ่าน after=_after
            # ของ play_song) จะรอ priority_alert_active_guilds เคลียร์อยู่แล้ว พอเคลียร์ปุ๊บก็จะ
            # หยิบเพลงนี้ขึ้นมาเล่นต่อ(เริ่มใหม่)ให้คุณเองอัตโนมัติ ไม่ต้องสั่งเล่นซ้ำเองตรงนี้อีกรอบ
            state.song_queue.insert(0, interrupted_search)
        if guild:
            state.priority_alert_active_guilds.discard(guild.id)


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
