"""bagley/commands/voice.py — คำสั่งห้องเสียง: เข้า/ออก/ย้าย/ปิดไมค์/ปาร์ตี้/เฝ้าห้อง/ตาม ฯลฯ"""
import asyncio
import discord
import random
import re as regex_lib
from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands
from typing import Optional

from bagley.ai import persona
from bagley.core import state
from bagley.core.app import bot, client
from bagley.core.config import ALLOWED_USERS, bangkok_tz
from bagley.core.logutil import print
from bagley.data.storage import get_realtime_name, load_user_data, load_voice_data
from bagley.features import rooms as bagley_rooms
from bagley.features.members import _format_greeting_names
from bagley.features.party import execute_dm_call, execute_warp_invite
from bagley.features.teams import _dm_self_kick_timer
from bagley.phrases import VOICE_REPORT_OFF_SPEECH, VOICE_REPORT_ON_SPEECH, pick as _pick_speech, say
from bagley.ui.views import CancelVoiceView, GroupMoveView, KickVoiceView, PartyCreateView, PullRoomView, RoleSelectView, StreamModeView
from bagley.voice.alerts import check_shared_voice_quota
from bagley.voice.tts import FFMPEG_PATH, bagley_speak, bagley_speak_wait


# --- [CORE COMMANDS] สั่งแล้วพูดด้วย ---
@bot.hybrid_command(name="move", description="ย้ายสมาชิกไปห้องเสียงอื่น")
async def move(ctx: commands.Context, member: discord.Member, channel: discord.VoiceChannel):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)
    user_id = ctx.author.id
    now = datetime.now()

    try:
        # 1. ทำการย้ายจริง
        await member.move_to(channel)
        
        msg = f"ย้ายคุณ {get_realtime_name(member.id, member.display_name)} ไปที่ห้อง {channel.name} เรียบร้อยครับ!"
        
        # 2. ตอบกลับ (ใช้ ctx.send เพื่อให้รองรับทั้ง Slash และข้อความปกติ)
        await ctx.send(msg)
        
        # 3. พูดในห้องเสียง
        if ctx.guild.voice_client:
            await bagley_speak(ctx.guild, msg)
            
    except Exception as e:
        # พิมพ์ Error ออกมาดูใน Terminal
        print(f"Move Error: {e}") 
        await ctx.send("ย้ายไม่ได้ครับ ผมอาจจะไม่มีสิทธิ์ หรือมีอะไรบางอย่างขัดข้อง!")


@bot.hybrid_command(name="join", description="สั่งให้ Bagley เข้ามาในห้องเสียง")
async def join(ctx: commands.Context):
    if ctx.interaction:
        await ctx.defer()

    if ctx.author.voice:
        channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
            vc = ctx.voice_client
        else:
            vc = await channel.connect()
        
        state.bot_follow_targets[ctx.guild.id] = None
        await asyncio.sleep(1.0)

        try:
            online_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio('drone_online.mp3', executable=FFMPEG_PATH)
            )
            online_source.volume = 0.5 
            vc.play(online_source)
            await asyncio.sleep(1.8) 

            steps = 10
            for _ in range(steps):
                if online_source:
                    online_source.volume = max(0, online_source.volume - (0.5 / steps))
                    await asyncio.sleep(1.0 / steps)

            if vc.is_playing():
                vc.stop()
            await asyncio.sleep(0.5) # 🌟 เพิ่มดีเลย์เพื่อให้ระบบ Discord เคลียร์ช่องสัญญาณเสียง
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดเสียง Drone ตอน Join: {e}")

        # ==========================================
        # ⏰ ระบบคัดกรองตารางงานของ "ทุกคน" ในห้องเสียง
        # ==========================================
        today_date = datetime.today().date()
        today_str = datetime.now(bangkok_tz).strftime("%Y-%m-%d")
        all_humans_in_room = [m for m in channel.members if not m.bot]
        human_ids = [m.id for m in all_humans_in_room]

        # 👋 รายชื่อคนในห้องตอนนี้ (ใช้ทักทายแบบเรียกชื่อถ้าคนไม่เกิน 4 คน)
        human_names = [get_realtime_name(m.id, m.display_name) for m in all_humans_in_room]
        greet_target_text = _format_greeting_names(human_names)

        today_schedules = []
        try:
            all_schedules = load_user_data().get("schedules", [])
            for sch in all_schedules:
                if sch.get("date") == today_str and sch.get("owner_id") in human_ids:
                    today_schedules.append(sch)
        except Exception as e:
            print(f"DEBUG: 📅 ดึงตารางงานตอน Join พลาด: {e}")

        pending_reminders = []
        for sch in today_schedules:
            remind_key = f"{sch.get('owner_id')}_{sch.get('event')}_{today_str}"
            if state.last_reminder_dates.get(remind_key) != today_date:
                pending_reminders.append(sch)

        reminder_fallback_text = ""
        reminder_context = ""
        if pending_reminders:
            reminder_context = "ตารางแจ้งเตือนด่วนของคนในห้องนี้วันนี้:\n"
            reminder_fallback_text = " อ้อ! แถมวันนี้มีตารางนัดหมายสำคัญด้วยนะครับ"
            for r in pending_reminders:
                owner_member = ctx.guild.get_member(r.get('owner_id'))
                owner_name = get_realtime_name(r.get('owner_id'), owner_member.display_name if owner_member else "ใครบางคน")
                reminder_context += f"- ของคุณ {owner_name}: งาน '{r.get('event')}' เวลา {r.get('time')}\n"
                reminder_fallback_text += f" มีงานของคุณ {owner_name} กิจกรรม {r.get('event')} เวลา {r.get('time')}"

        now_hour = datetime.now(bangkok_tz).hour
        time_period = "อรุณสวัสดิ์" if 0 <= now_hour < 13 else "สวัสดีตอนบ่าย" if 13 <= now_hour < 14 else "สวัสดีตอนเย็น" if 14 <= now_hour < 19 else "สวัสดีตอนกลางคืน"
        caller_name = get_realtime_name(ctx.author.id, ctx.author.display_name)

        msg = ""
        guild_key = ctx.guild.id

        # 💡 เช็กว่าเซิร์ฟเวอร์นี้ วันนี้เคยเรียก /join แล้วใช้ AI เจนคำพูดทักทายไปแล้วหรือยัง
        if state.join_greeted_today.get(guild_key) != today_date:
            try:
                prompt = f"""
                {persona.BRIEF}
สถานการณ์: คุณเพิ่งเข้ามาประจำการในห้องเสียงตามคำสั่งเรียกของคุณ (นี่คือการเจอหน้ากันครั้งแรกของวันนี้)
                หน้าที่: สร้างคำทักทายภาษาไทยแบบสั้นๆ กระชับ และพ่วงแจ้งเตือนตารางงาน (ถ้ามี)
                
                [บริบทปัจจุบัน]:
                - คนที่เรียกคุณเข้าห้องมา: คุณ {caller_name}
                - คนที่อยู่ในห้องเสียงตอนนี้ที่ต้องทักทาย: {greet_target_text}
                - ช่วงเวลาปัจจุบัน: {time_period}
                - ข้อมูลตารางงานที่ต้องเตือน: {reminder_context if reminder_context else 'ไม่มี'}
                
                กฎ: ทักทาย "{greet_target_text}" ตามที่กำหนดให้เป๊ะๆ (ถ้าเป็นชื่อคน ให้เอ่ยชื่อจริงๆ ถ้าเป็นคำว่า "ทุกคน" ให้พูดสวัสดีทุกคนแทนการไล่ชื่อ)
                ทักทายประชดขำๆ แทนตัวเองว่า 'แบ็คลี่' ตอบเฉพาะบทพูดไม่มีหัวข้อเด็ดขาด
                ห้ามพูดถึงเรื่องตารางงานเด็ดขาดถ้าไม่มีข้อมูลตารางงานที่ต้องเตือนด้านบน (อย่าพูดว่า "วันนี้ไม่มีนัดหมาย" หรือทำนองนั้นเป็นอันขาด ถ้าไม่มีให้ข้ามเรื่องตารางงานไปเลยเหมือนไม่มีเรื่องนี้อยู่)
                """
                response = await client.aio.models.generate_content(model="chat", contents=prompt)
                msg = (response.text or "").strip()
                print(f"DEBUG: 🤖 [Join AI] AI ตอบกลับมา (length={len(msg)}): {msg[:80] if msg else '(ว่างเปล่า!)'}")
                
                state.join_greeted_today[guild_key] = today_date
            except Exception as ai_err:
                print(f"❌ AI ทักทายตอน Join ครั้งแรกขัดข้อง: {ai_err}")

        # 🔒 ถ้าเคยเรียกใช้ไปแล้วในวันนี้ หรือ AI ทำงานพลาด -> ถอยกลับมาใช้คำพูดสำรอง (แต่บังคับให้พูดเสมอ)
        if not msg:
            print("DEBUG: 🔁 [Join] msg ว่างเปล่า (AI ไม่ได้พูดหรือเคยทักไปแล้ว) -> ใช้คำพูดฟิกซ์สำรอง")
            quotes = [
                "ผมเข้ามาสอดแนมในห้องเสียงแล้วครับ!",
                "เชื่อมต่อระบบ Neural Link เรียบร้อย พร้อมดูแลคุณแล้วครับ",
                "ผมมาในห้องเสียงแล้วครับ",
                "พร้อมทำงานเต็มรูปแบบคัปพ้ม!"
            ]
            msg = f"แบ็คลี่ ประจำการ! {time_period}ครับ {greet_target_text} {random.choice(quotes)}{reminder_fallback_text}"

        # 📤 ส่งข้อความแชท (สั้น ๆ ตายตัว) + พูดออกเสียงด้วยประโยคที่ AI เจนมาแบบเดิม
        chat_text = "รับทราบครับ! เข้ามาแล้วครับ"
        print(f"DEBUG: 📤 [Join] กำลังจะส่งข้อความ (สั้น) และพูด -> msg_length={len(msg)}, msg_preview={msg[:80]}")
        if ctx.interaction:
            await ctx.interaction.followup.send(chat_text)
        else:
            await ctx.send(chat_text)
            
        try:
            # 🌟 การันตีหยุดเสียงเก่าก่อนพูด และเรียกใช้ฟังก์ชันพูด
            if vc.is_playing():
                vc.stop()
            await asyncio.sleep(0.2)
            
            await bagley_speak_wait(ctx.guild, msg)
            for r in pending_reminders:
                remind_key = f"{r.get('owner_id')}_{r.get('event')}_{today_str}"
                state.last_reminder_dates[remind_key] = today_date
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนแบ็คลี่พูดในคำสั่ง Join: {e}")
        
    else:
        error_msg = "กรุณาเอาตัวเองเข้าไปในห้องเสียงก่อนสั่งผมครับ!"
        if ctx.interaction:
            await ctx.interaction.followup.send(error_msg)
        else:
            await ctx.send(error_msg)


# --- คำสั่ง Leave แบบ Hybrid (พิมพ์ได้ทั้ง /leave และ !leave) ---
@bot.hybrid_command(name="leave", description="ไล่ Bagley ออกจากห้องเสียง")
async def leave(ctx: commands.Context):
    vc = ctx.voice_client
    if vc:
        if vc.is_playing():
            vc.stop()
            
        if ctx.guild.id in state.active_alarms:
            state.active_alarms[ctx.guild.id] = False

        msg = "รับทราบครับ ไปแล้วนะครับ!"
        
        if ctx.interaction:
            await ctx.interaction.response.send_message(msg)
        else:
            await ctx.send(msg)
            
        try:
            await bagley_speak_wait(ctx.guild, msg)
        except Exception as tts_err:
            print(f"DEBUG: ล่าม TTS พูดก่อนออกจากห้องขัดข้อง: {tts_err}")

        try:
            leave_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio('drone_hijack.mp3', executable=FFMPEG_PATH)
            )
            leave_source.volume = 0.6
            vc.play(leave_source)

            await asyncio.sleep(2.5) 

            steps = 15
            fade_duration = 1.5
            for _ in range(steps):
                if ctx.voice_client and leave_source:
                    leave_source.volume = max(0, leave_source.volume - (0.6 / steps))
                    await asyncio.sleep(fade_duration / steps)
                else:
                    break
        except Exception as sound_err:
            print(f"🚨 เอฟเฟกต์เสียงขาดตอน หรือไม่พบไฟล์ drone_hijack.mp3: {sound_err}")

        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
            await asyncio.sleep(0.5)
            await ctx.voice_client.disconnect()
            print("DEBUG: เจ้า Bagley ย้ายร่างออกจากห้องเสียงสำเร็จเรียบร้อย!")
            
    else:
        no_vc_msg = "ผมยังไม่ได้เข้าห้องไหนเลยนะ ใจเย็นครับ!"
        if ctx.interaction:
            await ctx.interaction.response.send_message(no_vc_msg)
        else:
            await ctx.send(no_vc_msg)


@bot.hybrid_command(name="kick_voice", description="เตะสมาชิกออกจากห้องเสียง")
async def kick_voice(ctx, member: discord.Member):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)
    user_id = ctx.author.id
    now = datetime.now()

    if member.voice:
        await member.move_to(None) # เตะออก
        
        msg = f"รับทราบครับ! ผมจัดการเขี่ย {get_realtime_name(member.id, member.display_name)} ออกจากห้องเสียงให้แล้ว"
        
        # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
        await bagley_speak(ctx.guild, say("kick_done", name=get_realtime_name(member.id, member.display_name)))
            
        await ctx.send(msg)
    else:
        # ถ้าเขาไม่อยู่ในห้องเสียง ก็ส่งแค่ข้อความแชทปกติ
        await ctx.send(say("member_not_in_voice", name="คุณ " + get_realtime_name(member.id, member.display_name)))


# --- ส่วนคำสั่งหลัก gather ---
@bot.hybrid_command(name="gather", description="เรียกประชุมพร้อมปุ่มกดตอบรับ")
@commands.cooldown(1, 300, commands.BucketType.guild) # ย้ายคูลดาวน์มาไว้ตรงนี้
async def gather(ctx: commands.Context, topic: str, time: Optional[str] = "ตอนนี้"):
    # ใช้ View ตัวใหม่ที่รับ topic และ time
    view = RoleSelectView(ctx.author, topic, time)
    
    msg_text = f"📢 **ระบบ Gather ทำงาน!**\nหัวข้อ: **{topic}** | เวลา: **{time}**\nคุณเลือกกลุ่มที่จะแจ้งเตือนได้เลยครับ (เมนูด้านล่าง)"
    
    # 1. ส่งข้อความเมนูในแชท
    await ctx.send(msg_text, view=view)
    
    # 2. ให้ Bagley พูดออกเสียงตอนเปิดเมนู
    await bagley_speak(ctx.guild, f"กำลังเปิดระบบแจ้งเตือนภารกิจ {topic} ครับ เลือกกลุ่มที่ต้องการได้เลยครับ")


# --- ตัวจัดการ Error ---
@gather.error
async def gather_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        seconds = error.retry_after
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        
        msg = f"ใจเย็นครับ! พรรคพวกยังไม่หายเหนื่อยเลย รออีก {int(minutes)} นาที {int(remaining_seconds)} วินาทีนะครับ"
        
        await ctx.send(msg, ephemeral=True)
        await bagley_speak(ctx.guild, f"ระบบยังไม่พร้อมใช้งานครับ รออีกประมาณ {int(minutes)} นาที")
    else:
        print(f"Gather Error: {error}")


@bot.hybrid_command(name="tts", description="เปิดหรือปิดระบบล่าม (อ่านแชท)")
@app_commands.choices(mode=[
    app_commands.Choice(name="เปิดระบบ (On)", value="on"),
    app_commands.Choice(name="ปิดระบบ (Off)", value="off")
])
async def tts(ctx: commands.Context, mode: str = None):
    
    # 1. จัดการสถานะตามที่เลือก
    if mode is None:
        # ถ้าไม่ระบุ mode ให้สลับสถานะ (Toggle) แบบเดิม
        state.is_tts_enabled = not state.is_tts_enabled
    else:
        # ถ้าเลือกจากเมนู หรือพิมพ์ on/off
        if mode.lower() in ["on", "เปิด", "start"]:
            state.is_tts_enabled = True
        elif mode.lower() in ["off", "ปิด", "stop"]:
            state.is_tts_enabled = False

    # 2. เตรียมข้อความแจ้งเตือน
    if state.is_tts_enabled:
        msg = "ระบบล่ามเปิดใช้งานแล้วครับ!"
        icon = "🔊"
    else:
        msg = "ปิดระบบล่ามเรียบร้อยครับ"
        icon = "🔇"

    # 3. ส่งข้อความตอบกลับในแชท
    await ctx.send(f"{icon} **{msg}**")

    # 4. สั่งให้ Bagley พูดผ่าน Voice Channel (ถ้าไม่ได้เล่นเพลงอยู่)
    if ctx.voice_client and not state.is_playing_music:
        try:
            # ใช้ข้อความเสียงอันเดียวกับในแชท
            await bagley_speak(ctx.guild, msg) 
        except Exception as e:
            print(f"TTS Speech Error: {e}")


@bot.hybrid_command(name="same_game_alert", description="เปิดหรือปิดระบบแจ้งเตือนว่ามีใครเปิดเกมเดียวกันบ้าง (คล้าย /tts)")
@app_commands.choices(mode=[
    app_commands.Choice(name="เปิดระบบ (On)", value="on"),
    app_commands.Choice(name="ปิดระบบ (Off)", value="off")
])
async def same_game_alert(ctx: commands.Context, mode: str = None):
    """สลับเปิด/ปิดระบบ check_and_invite_party (แม่สื่อชวนตี้ที่คอยบอกว่าใครนอกห้องเสียง
    เพิ่งเปิดเกมตรงกับคนในห้อง) เฉพาะเซิร์ฟเวอร์นี้ — สถานะเก็บในแรม (party_matcher_disabled_guilds)
    รีเซ็ตกลับเป็นค่าเริ่มต้น (เปิด) ทุกครั้งที่บอทรีสตาร์ท เหมือนกับระบบ /follow"""
    guild_id = ctx.guild.id
    currently_disabled = guild_id in state.party_matcher_disabled_guilds

    # 1. จัดการสถานะตามที่เลือก
    if mode is None:
        # ถ้าไม่ระบุ mode ให้สลับสถานะ (Toggle) แบบเดิม
        should_enable = currently_disabled
    elif mode.lower() in ["on", "เปิด", "start"]:
        should_enable = True
    elif mode.lower() in ["off", "ปิด", "stop"]:
        should_enable = False
    else:
        should_enable = currently_disabled

    if should_enable:
        state.party_matcher_disabled_guilds.discard(guild_id)
        msg = "เปิดระบบบอกว่าใครเล่นเกมเดียวกันบ้างแล้วครับ!"
        icon = "🎮"
    else:
        state.party_matcher_disabled_guilds.add(guild_id)
        msg = "ปิดระบบบอกว่าใครเล่นเกมเดียวกันบ้างเรียบร้อยครับ"
        icon = "🔇"

    # 2. ส่งข้อความตอบกลับในแชท
    await ctx.send(f"{icon} **{msg}**")

    # 3. สั่งให้ Bagley พูดผ่าน Voice Channel (ถ้าไม่ได้เล่นเพลงอยู่)
    if ctx.voice_client and not state.is_playing_music:
        try:
            await bagley_speak(ctx.guild, msg)
        except Exception as e:
            print(f"Same Game Alert Speech Error: {e}")


@bot.hybrid_command(name="stream_mode", description="เปิด/ปิดโหมดสตรีมด้วยปุ่มเดียว (ปิดชวนตี้/แจ้งเวลา/ทักทาย + รับคำสั่งเฉพาะเจ้าของหรือคนสตรีม)")
async def stream_mode_panel(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("คำสั่งนี้จำเป็นต้องสั่งใช้งานภายในเซิร์ฟเวอร์เท่านั้นครับ")
        return

    is_on = state.stream_mode_status.get(ctx.guild.id, False)
    embed = discord.Embed(
        title="🎥 โหมดสตรีม",
        description=(
            f"สถานะตอนนี้: {'🔴 **เปิดอยู่**' if is_on else '🟢 **ปิดอยู่**'}\n\n"
            "กดปุ่มด้านล่างเพื่อสลับเปิด/ปิดโหมดสตรีม:\n"
            "1️⃣ ปิด/เปิดระบบชวนตี้ (หาคนเล่นเกมเดียวกัน)\n"
            "2️⃣ ปิด/เปิดแจ้งเตือนเที่ยงวัน/เที่ยงคืน\n"
            "3️⃣ รับคำสั่งเฉพาะเจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้น (เปิดโหมดสตรีมแล้วคนอื่นสั่งไม่ได้)\n"
            "4️⃣ ปิด/เปิดระบบพูดทักทายคนเข้า-ออกห้องเสียง\n\n"
            "*(ปุ่มนี้กดได้เฉพาะเจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้นนะครับ)*"
        ),
        color=0xff4d4d if is_on else 0x2ecc71,
    )
    view = StreamModeView(ctx.guild.id)
    await ctx.send(embed=embed, view=view)


@bot.hybrid_command(name="follow", description="สั่งให้แบ็คลี่ตามติดสมาชิกคนนี้ไปทุกห้องเสียงในเซิร์ฟนี้")
async def follow(ctx: commands.Context, member: discord.Member):
    """เพิ่มการตามติดแบบกำหนดเองผ่านคำสั่ง (แยกจากระบบตามผู้พัฒนาโดยอัตโนมัติ)
    เก็บสถานะในแรมเท่านั้น -> รีเซ็ตกลับเป็นค่าว่างทุกครั้งที่บอทรีสตาร์ทโดยอัตโนมัติ"""
    if ctx.interaction:
        await ctx.defer()

    if member.bot:
        error_msg = "ตามติดบอทตัวอื่นไม่ได้นะครับ เลือกสมาชิกจริงๆ มาให้ผมตามหน่อยครับ!"
        if ctx.interaction:
            await ctx.interaction.followup.send(error_msg)
        else:
            await ctx.send(error_msg)
        return

    state.command_follow_targets[ctx.guild.id] = member.id
    target_name = get_realtime_name(member.id, member.display_name)
    msg = f"รับทราบครับ! ตั้งแต่นี้ผมจะคอยตามติดคุณ {target_name} ไปทุกห้องเสียงในเซิร์ฟนี้เลยครับ 🕵️"

    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


@bot.hybrid_command(name="unfollow", description="ยกเลิกการตามติดที่ตั้งไว้ด้วยคำสั่ง /follow")
async def unfollow(ctx: commands.Context):
    if ctx.interaction:
        await ctx.defer()

    if state.command_follow_targets.get(ctx.guild.id):
        state.command_follow_targets.pop(ctx.guild.id, None)
        msg = "รับทราบครับ ยกเลิกการตามติดที่ตั้งไว้แล้วครับ กลับไปตามผู้พัฒนาแบบปกติเหมือนเดิม"
    else:
        msg = "ตอนนี้ไม่ได้ตั้งให้ผมตามใครเป็นพิเศษอยู่นะครับ"

    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


@bot.hybrid_command(name="mute_sleep", description="ปิดไมค์สมาชิก (กรณีหลับ/เสียงดัง) โดยไม่ตัดสาย")
@commands.cooldown(1, 60, commands.BucketType.user) # ติดคูลดาวน์ 1 นาทีต่อการใช้ 1 ครั้ง
async def mute_sleep(ctx, member: discord.Member):
    if member.voice:
        try:
            await member.edit(mute=True) # สั่ง Server Mute
            msg = f"ปิดไมค์คุณ {get_realtime_name(member.id, member.display_name)} เรียบร้อยครับ เห็นว่าหลับปุ๋ยเชียว!"
            await ctx.send(f"🔇 **{msg}**")
            
            # ส่งเสียง TTS บอกในห้อง
            if ctx.voice_client and not state.is_playing_music:
                await bagley_speak(ctx.guild, say("mute_done"))
        except Exception as e:
            await ctx.send(say("no_power"))
    else:
        await ctx.send(say("member_not_in_voice", name="สมาชิกคนนี้"))


@mute_sleep.error
async def mute_sleep_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        seconds = round(error.retry_after, 1)
        await ctx.send(f"⚠️ **ใจเย็นครับ!** ระบบแฮ็กเสียงกำลังพักเครื่อง รอก่อนอีก {seconds} วินาทีนะครับ", delete_after=10)
    else:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: {error}")


# 2. คำสั่งสำหรับปลดไมค์ตัวเอง
@bot.hybrid_command(name="unmute_me", description="ปลดการปิดไมค์ของตัวเองเมื่อตื่นแล้ว")
async def unmute_me(ctx):
    member = ctx.author
    if member.voice and member.voice.mute:
        try:
            await member.edit(mute=False) # ปลด Server Mute
            await ctx.send("🔊 " + say("welcome_back_mic", name=get_realtime_name(member.id, member.display_name)))
        except Exception as e:
            await ctx.send("ดูเหมือนผมจะปลดไมค์ให้ไม่ได้นะครับ")
    else:
        await ctx.send("ไมค์ของคุณไม่ได้ถูกปิดอยู่ครับ", delete_after=5)


@bot.hybrid_command(name="unmute_member", description="ปลดการปิดไมค์ให้สมาชิกคนอื่น")
@commands.cooldown(1, 60, commands.BucketType.user) # คูลดาวน์ร่วมกัน 1 นาที
async def unmute_member(ctx, member: discord.Member):
    if member.voice and member.voice.mute:
        try:
            await member.edit(mute=False) # ปลด Server Mute
            msg = f"เปิดไมค์ให้คุณ {get_realtime_name(member.id, member.display_name)} เรียบร้อยแล้วครับ!"
            await ctx.send(f"🔊 **{msg}**")
            
            # ส่งเสียง TTS รายงานผล (เสียงคุณนิวัท)
            if ctx.voice_client and not state.is_playing_music:
                await bagley_speak(ctx.guild, say("unmute_done"))
        except Exception as e:
            await ctx.send(say("no_power"))
    else:
        await ctx.send("สมาชิกคนนี้ไม่ได้ถูกปิดไมค์อยู่ครับ", delete_after=5)


@unmute_member.error
async def unmute_member_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        seconds = round(error.retry_after, 1)
        await ctx.send(f"⚠️ **คูลดาวน์อยู่ครับ!** รอก่อนอีก {seconds} วินาทีนะ", delete_after=10)


@bot.hybrid_command(name="group_move", description="เลือกย้ายกลุ่มเพื่อนไปห้องอื่นพร้อมกัน")
@commands.cooldown(1, 60, commands.BucketType.user)
async def group_move(ctx):
    if ctx.author.voice:
        members = ctx.author.voice.channel.members
        voice_channels = [c for c in ctx.guild.voice_channels if c != ctx.author.voice.channel]
        
        # 🛡️ [จุดเซฟตี้หลัก] เช็กก่อนเลยว่าในดิสคอร์ดมีห้องอื่นให้ย้ายไปไหม
        if not voice_channels:
            return await ctx.send("❌ ในเซิร์ฟเวอร์ไม่มีห้องเสียงอื่นให้ย้ายไปเลยครับ!")
            
        if len([m for m in members if not m.bot]) <= 1:
            return await ctx.send("ไม่มีใครให้ย้ายไปพร้อมกันเลยครับ")

        view = GroupMoveView(ctx.author, members, voice_channels)
        await ctx.send("คุณต้องการจะพาใครย้ายไปห้องไหนดีครับ?", view=view)

        msg = "คุณต้องการจะพาใครย้ายไปห้องไหนดีครับ เลือกสมาชิกและห้องปลายทางได้เลย"
        await bagley_speak(ctx.guild, msg)

    else:
        await ctx.send(say("need_voice"))


@bot.hybrid_command(name="create_party", description="สร้างห้องใหม่พร้อมดึงเพื่อนเข้าปาร์ตี้")
@app_commands.describe(name="ชื่อห้องที่ต้องการสร้าง")
async def create_party(ctx, name: str):
    if ctx.author.voice:
        members = ctx.author.voice.channel.members
        category = ctx.author.voice.channel.category
        
        view = PartyCreateView(ctx.author, members, category, name)
        await ctx.send(f"จะสร้างปาร์ตี้ **'{name}'** สินะครับ เลือกคนที่จะพาไปด้วยได้เลย!", view=view)

        msg = f"จะสร้างปาร์ตี้ {name} สินะครับ เลือกคนที่จะพาไปด้วยได้เลย"
        await bagley_speak(ctx.guild, msg)

    else:
        await ctx.send(say("need_voice"))


# ============================================================
# 🏷️ /rename_room - เปลี่ยนชื่อห้องเสียงที่ผู้สั่งอยู่ตอนนี้ชั่วคราว
# ============================================================
@bot.hybrid_command(
    name="rename_room",
    description="เปลี่ยนชื่อห้องเสียงที่คุณอยู่ชั่วคราว พอทุกคนออกจากห้องหมดจะเปลี่ยนชื่อกลับอัตโนมัติ",
)
@app_commands.describe(name="ชื่อใหม่ที่ต้องการตั้งให้ห้องเสียง (ชั่วคราว)")
async def rename_room(ctx: commands.Context, *, name: str):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)

    if not (ctx.author.voice and ctx.author.voice.channel):
        return await ctx.send(say("need_voice"))

    channel = ctx.author.voice.channel
    new_name = name.strip()[:100]
    if not new_name:
        return await ctx.send("ชื่อห้องใหม่ห้ามเว้นว่างนะครับ!")

    try:
        original_name = await bagley_rooms.rename_room_temp(channel, new_name, ctx.author)
    except Exception as e:
        return await ctx.send(f"❌ เปลี่ยนชื่อห้องไม่ได้ครับ ผมอาจไม่มีสิทธิ์จัดการห้องนี้: {e}")

    msg = (
        f"เปลี่ยนชื่อห้องเป็น '{new_name}' เรียบร้อยครับ! "
        f"พอทุกคนออกจากห้องหมด ผมจะเปลี่ยนชื่อกลับเป็น '{original_name}' ให้อัตโนมัติเลย"
    )
    await ctx.send(msg)
    if ctx.guild.voice_client:
        await bagley_speak(ctx.guild, msg)


# ============================================================
# 🔒 /lock_room - ล็อกห้องเสียงที่ผู้สั่งอยู่ตอนนี้ให้เป็นห้องส่วนตัว
# ============================================================
@bot.hybrid_command(
    name="lock_room",
    description="ล็อกห้องเสียงที่คุณอยู่ให้เป็นห้องส่วนตัว คนนอกห้องเข้าไม่ได้ ปลดล็อกอัตโนมัติเมื่อห้องว่าง",
)
async def lock_room(ctx: commands.Context):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)

    if not (ctx.author.voice and ctx.author.voice.channel):
        return await ctx.send(say("need_voice"))

    channel = ctx.author.voice.channel

    if channel.id in bagley_rooms.locked_voice_rooms:
        try:
            await bagley_rooms.unlock_room_private(channel, reason=f"ปลดล็อกโดย {ctx.author.display_name}")
        except Exception as e:
            return await ctx.send(f"❌ ปลดล็อกห้องไม่ได้ครับ: {e}")
        msg = f"ปลดล็อกห้อง '{channel.name}' กลับเป็นห้องปกติให้แล้วครับ ใครก็เข้าได้ตามเดิม"
    else:
        try:
            await bagley_rooms.lock_room_private(channel, ctx.author)
        except Exception as e:
            return await ctx.send(f"❌ ล็อกห้องไม่ได้ครับ ผมอาจไม่มีสิทธิ์จัดการห้องนี้: {e}")

        human_names = [get_realtime_name(m.id, m.display_name) for m in channel.members if not m.bot]
        who_text = "、".join(human_names) if human_names else "ยังไม่มีใครอยู่ในห้องเลยตอนนี้"
        msg = (
            f"ล็อกห้อง '{channel.name}' เป็นห้องส่วนตัวเรียบร้อยครับ! ตอนนี้เข้าได้เฉพาะ {who_text} เท่านั้น "
            f"พอทุกคนออกจากห้องหมด ผมจะปลดล็อกให้อัตโนมัติเลย"
        )

    await ctx.send(msg)
    if ctx.guild.voice_client:
        await bagley_speak(ctx.guild, msg)


@bot.hybrid_command(name="deaf_work", description="ปิดหูฟังสมาชิก (กรณีทำงาน/ต้องการความสงบ)")
@commands.cooldown(1, 60, commands.BucketType.user)
async def deaf_work(ctx, member: discord.Member):
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send("❌ " + say("member_not_in_voice", name="คุณ " + get_realtime_name(member.id, member.display_name)))
    
    # เช็คว่าเขาปิดหูฟังอยู่แล้วหรือเปล่า (Error Check)
    if member.voice.deaf:
        return await ctx.send(f"🎧 คุณ {get_realtime_name(member.id, member.display_name)} ปิดหูฟังอยู่แล้วครับ")

    try:
        await member.edit(deafen=True)
        msg = f"ปิดหูฟังให้คุณ {get_realtime_name(member.id, member.display_name)} เรียบร้อยครับ!"
        await ctx.send(f"🎧 **{msg}**")
        
        # ระบบพูด TTS เสียงคุณนิวัท (ถ้าไม่ได้เล่นเพลงอยู่)
        if ctx.voice_client and not state.is_playing_music:
            await bagley_speak(ctx.guild, say("deaf_done"))
    except Exception as e:
        await ctx.send(f"❌ ผมจัดการไม่ได้ครับ: {e}")


@bot.hybrid_command(name="undeaf_me", description="เปิดหูฟังของตัวเองเมื่อพร้อมคุยแล้ว")
async def undeaf_me(ctx):
    member = ctx.author
    
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send("❌ " + say("need_voice"))
    
    # เช็คว่าหูฟังไม่ได้ถูกปิดอยู่ ถ้าเปิดอยู่แล้วก็ไม่ต้องทำอะไร
    if not member.voice.deaf:
        return await ctx.send("🔊 หูฟังของคุณก็เปิดอยู่แล้วนะ! พร้อมลุยได้เลยครับ", delete_after=5)

    try:
        await member.edit(deafen=False) # ปลด Server Deafen
        await ctx.send("🎧 " + say("welcome_back_ears", name=get_realtime_name(member.id, member.display_name)))
        
        # ส่งเสียงทักทายหน่อย
        if ctx.voice_client and not state.is_playing_music:
            await bagley_speak(ctx.guild, say("welcome_back_short"))
    except Exception as e:
        await ctx.send(f"❌ ดูเหมือนผมจะมีปัญหาในการเข้าถึงระบบเสียงนะครับ: {e}")


@bot.hybrid_command(name="undeaf_member", description="ปลดหูฟังให้สมาชิกคนอื่น")
@commands.cooldown(1, 60, commands.BucketType.user)
async def undeaf_member(ctx, member: discord.Member):
    if not member.voice:
        return await ctx.send("❌ " + say("member_not_in_voice", name="คุณ " + get_realtime_name(member.id, member.display_name)))
    
    # เช็คว่าเขาเปิดหูฟังอยู่แล้วหรือเปล่า
    if not member.voice.deaf:
        return await ctx.send(f"🔊 หูฟังของคุณ {get_realtime_name(member.id, member.display_name)} ก็เปิดอยู่แล้วนะ")

    try:
        await member.edit(deafen=False)
        await ctx.send(f"🎧 ปลดหูฟังให้คุณ {get_realtime_name(member.id, member.display_name)} เรียบร้อย!")
        if ctx.voice_client and not state.is_playing_music:
            await bagley_speak(ctx.guild, say("undeaf_done"))
    except Exception as e:
        await ctx.send(f"❌ ผมปลดให้ไม่ได้ครับ: {e}")


@bot.hybrid_command(name="send_to", description="ส่ง Bagley ไปอยู่เป็นเพื่อนใครบางคน (ใส่ชื่อแท็ก หรือ เลข ID ก็ได้)")
async def send_to(ctx: commands.Context, friend: str): # 🔄 เปลี่ยนมารับเป็นข้อความดิบ (str) เพื่อรองรับ ID
    await ctx.defer(ephemeral=False)

    if ctx.guild is None:
        await ctx.send("ขออภัยครับ! คำสั่งนี้ต้องพิมพ์สั่งภายในเซิร์ฟเวอร์ที่ผมประจำการอยู่เท่านั้นครับ ใน DM ผมแอบวาร์ปเข้าห้องเสียงไม่ได้น้า! 🛸❌")
        return

    member = None

    # 🔍 1. ตรวจเช็คว่าข้อความที่ส่งมาเป็นเลข ID หรือไม่ (ตัวเลข 17-19 หลัก)
    id_match = regex_lib.search(r'(\d{17,19})', friend)
    
    if id_match:
        target_id = int(id_match.group(1))
        # พยายามค้นหาจากสมาชิกในเซิร์ฟเวอร์ก่อน
        member = ctx.guild.get_member(target_id)
        
        # ถ้าหาในเซิร์ฟเวอร์ไม่เจอทันที ให้พยายามดึงข้อมูล (Fetch) มาจากระบบดิสคอร์ด
        if not member:
            try:
                member = await ctx.guild.fetch_member(target_id)
            except:
                pass
    
    # 🔍 2. ถ้าไม่ใช่เลข ID หรือดึงข้อมูลไม่สำเร็จ ลองสแกนหาในรูปแบบการ @Mention (แท็ก)
    if not member and ctx.message and ctx.message.mentions:
        member = ctx.message.mentions[0]
        
    # 🔍 3. หากยังไม่เจออีก ลองค้นหาจากชื่อธรรมดาที่พิมพ์เข้ามาในเซิร์ฟเวอร์
    if not member:
        member = discord.utils.get(ctx.guild.members, name=friend) or discord.utils.get(ctx.guild.members, display_name=friend)

    # 🛑 ถ้าระบบแกะหาเพื่อนคนนี้ไม่เจอเลย แจ้งเตือนผู้สั่งการทันที
    if not member:
        await ctx.send("ขออภัยครับ ผมหาเพื่อนคนนี้ไม่เจอ รบกวนตรวจสอบเลข ID หรือแท็กชื่อใหม่อีกครั้งน้าครับ")
        return

    if member.voice and member.voice.channel:
        target_channel = member.voice.channel
        
        # เชื่อมต่อหรือย้ายห้องเสียง
        if ctx.voice_client:
            await ctx.voice_client.move_to(target_channel)
            vc = ctx.voice_client
        else:
            vc = await target_channel.connect()

        # แจ้งในช่องแชททันทีหลังจากก้าวเท้าเข้าห้องเสียง
        await ctx.send(f"รับทราบครับ! ผมจะไปอยู่เป็นเพื่อนคุณ {get_realtime_name(member.id, member.display_name)} เดี๋ยวนี้แหละ")

        # เล่นเสียงเปิดตัว (เฟดเสียง)
        audio_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=FFMPEG_PATH),
            volume=0.5
        )
        vc.play(audio_source)

        while vc.is_playing(): 
            await asyncio.sleep(0.1)

        steps = 10
        for _ in range(steps):
            if audio_source:
                audio_source.volume = max(0, audio_source.volume - (0.5 / steps))
                await asyncio.sleep(0.1)

        if vc.is_playing():
            vc.stop()

        # เตรียมคำพูด
        msg = (f"ไฮแจ๊คสำเร็จ สวัสดีครับ คุณ {get_realtime_name(member.id, member.display_name)} คุณ {get_realtime_name(ctx.author.id, ctx.author.display_name)} ส่งผมมาอยู่เป็นเพื่อนคุณครับ "
               f"หากมีอะไรให้ช่วยเรื่องคำสั่ง ค้นหาข้อมูล หรืออยากพูดคุย "
               f"สามารถเรียกหาผม แบ็คลี่ ได้ตลอดเลยนะครับ ผมประจำการอยู่ตรงนี้แล้วครับ!")

        await bagley_speak_wait(ctx.guild, msg)
        
    else:
        await ctx.send(f"คุณ {get_realtime_name(member.id, member.display_name)} ไม่ได้อยู่ในห้องเสียงครับ ผมคงแอบวาร์ปไปหาไม่ได้")


@bot.hybrid_command(name="report_voice", description="เปิดหรือปิดระบบพูดรายงานทักทายตอนคนเข้า-ออกห้องเสียง")
@app_commands.choices(status=[
    app_commands.Choice(name="เปิดระบบ (On)", value="on"),
    app_commands.Choice(name="ปิดระบบชั่วคราว (Off)", value="off")
])
async def report_voice_toggle(ctx: commands.Context, status: str):
    guild = ctx.guild

    if guild is None:
        await ctx.send("คำสั่งนี้จำเป็นต้องสั่งใช้งานภายในเซิร์ฟเวอร์หลักเท่านั้นน้า! 🛸❌", ephemeral=True)
        return

    guild_id = guild.id
    voice_client = guild.voice_client

    # รองรับทั้งค่าจาก choice ("on"/"off") และคำพูดธรรมชาติจาก AI Router ("เปิด"/"ปิด")
    status_value = status.lower().strip()
    is_on = status_value in ("on", "เปิด", "start", "เปิดระบบ")

    if is_on:
        state.voice_report_status[guild_id] = True
        response_text = "เปิดระบบคืนชีพ! 🔊 คราวนี้ใครเข้าหรือออกจากห้องเสียง ผมจะโผล่ไปรายงานส่งเสียงทักทายเหมือนเดิมแล้วครับ!"
        speech_text = _pick_speech(VOICE_REPORT_ON_SPEECH)
    else:
        state.voice_report_status[guild_id] = False
        response_text = "รับทราบครับ! 🔇 ผมจะปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงในเซิร์ฟนี้ให้ชั่วคราวน้า (แต่ระบบสถิติยังนับเวลาปกติครับ)"
        speech_text = _pick_speech(VOICE_REPORT_OFF_SPEECH)

    await ctx.send(response_text)

    if voice_client and voice_client.channel:
        if voice_client.is_playing():
            print(f"DEBUG: บอทกำลังเล่นเสียง/เปิดเพลงอยู่ จะไม่มีการพูดเสียงแทรกในกิลด์ {guild_id}")
            return
            
        await bagley_speak_wait(guild, speech_text)


@bot.hybrid_command(name="unfollow_me", description="สั่งให้ Bagley เลิกเดินตามตัวเราเอง")
async def unfollow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        state.auto_follow_status[user_id] = False
        await ctx.send(f"รับทราบครับ! แบ็คลี่ปิดระบบเดินตามของ {get_realtime_name(ctx.author.id, ctx.author.display_name)} เรียบร้อยครับ (ท่านอื่นยังตามปกติอยู่น้า)")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะผู้มีสิทธิ์ใช้งานเท่านั้นครับ!")


@bot.hybrid_command(name="follow_me", description="สั่งให้ Bagley กลับมาเดินตามตัวเราอีกครั้ง")
async def follow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        state.auto_follow_status[user_id] = True
        await ctx.send(f"ระบบ Neural Link เชื่อมต่อใหม่! แบ็คลี่เปิดระบบเดินตามของ {get_realtime_name(ctx.author.id, ctx.author.display_name)} พร้อมสแตนด์บายแล้วครับ!")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะผู้มีสิทธิ์ใช้งานเท่านั้นครับ!")


@bot.hybrid_command(name="kicktimer", description="ตั้งเวลาตามหน้าปัดนาฬิกาเพื่อดีดพวกนอนหลับคาห้องเสียง")
@app_commands.describe(target_time="ระบุเวลาที่ต้องการให้เตะออก เช่น 03:00, 3.00 หรือใส่แค่เลขชั่วโมง เช่น 3")
async def kick_timer(ctx: commands.Context, target_time: str):
    # 🆕 [DM Support] คูลดาวน์รวมผูกกับห้องเสียงในเซิร์ฟ ข้าม guild-check ตอนสั่งผ่าน DM
    if ctx.guild is not None:
        can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
        if not can_act:
            return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)

    cleaned_time = target_time.strip().replace(".", ":")

    time_match = regex_lib.match(r"^([0-1]?[0-9]|2[0-3])(?::([0-5][0-9]))?$", cleaned_time)
    
    if not time_match:
        return await ctx.send(
            "พิมพ์รูปแบบเวลาผิดครับ! กรุณาใส่เป็นรูปแบบเวลาที่ถูกต้อง เช่น `03:00`, `3.00` หรือใส่แค่ชั่วโมงตัวเดียว เช่น `3` ครับ", 
            ephemeral=True
        )

    hour_str, minute_str = time_match.groups()
    hour = int(hour_str)
    minute = int(minute_str) if minute_str is not None else 0
    
    now = datetime.now()
    target_datetime = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target_datetime <= now:
        target_datetime += timedelta(days=1)

    delay_seconds = (target_datetime - now).total_seconds()
    target_time_str = target_datetime.strftime("%H:%M น.")

    # 🆕 [DM Support] ไม่มีเซิร์ฟเวอร์ให้ใช้ ui.UserSelect เลือกเป้าหมาย -> ล็อกเป็นตัวเองอัตโนมัติ
    if ctx.guild is None:
        return await _dm_self_kick_timer(ctx, target_time_str, delay_seconds)

    view = KickVoiceView(target_time_str, delay_seconds)
    await ctx.send(f"ครับ! กรุณาเลือกสมาชิกที่คุณต้องการดีดออก ณ เวลา **{target_time_str}** :", view=view)


@bot.hybrid_command(name="kickcancel",description="เลือกยกเลิกรายชื่อคนที่ตั้งเวลาเตะไว้ในเซิร์ฟเวอร์นี้")
async def kick_cancel(ctx: commands.Context):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send("⚠️ " + say("cooldown", sec=rem), ephemeral=True)

    guild_id = ctx.guild.id
    has_active_task = any(key[0] == guild_id for key in state.active_kick_tasks.keys())
    
    if has_active_task:
        view = CancelVoiceView()
        await ctx.send("ครับ! กรุณาเลือกรายชื่อคนที่ต้องการยกเลิกคิวเตะจากเมนูด้านล่างนี้ได้เลยครับ:", view=view)
    else:
        await ctx.send("ไม่มีรายชื่อใครกำลังติดคิวตั้งเวลาเตะในเซิร์ฟนี้เลยครับ!", ephemeral=True)


@bot.hybrid_command(name="voicestats", description="ดูสรุปสถิติห้องเสียงของวันนี้ว่าใครคุยนานที่สุด")
async def voice_stats(ctx: commands.Context):
    try:
        if ctx.guild is None:
            return await ctx.send("ขออภัยครับ! คำสั่งสรุปสถิติต้องเรียกดูภายในเซิร์ฟเวอร์หลักเท่านั้นน้า 🛸❌", ephemeral=True)

        data = load_voice_data()
        today_str = datetime.now().strftime("%Y-%m-%d")

        if not data or data.get("date") != today_str or not data.get("stats"):
            return await ctx.send("วันนี้ยังไม่มีใครเข้าห้องเสียงเลยครับ!")

        stats = data["stats"]
        guild_id_str = str(ctx.guild.id)
        
        guild_stats = stats.get(guild_id_str, {})
        filtered_stats = [item for item in guild_stats.items() if int(item[0]) != bot.user.id]
        
        sorted_stats = sorted(filtered_stats, key=lambda x: x[1]['total_time'], reverse=True)[:5]
        
        if not sorted_stats:
            return await ctx.send("วันนี้ยังไม่มีสถิติของเซิร์ฟเวอร์นี้บันทึกไว้เลยครับ!")
        
        user_memory = load_user_data()

        # 📋 ก่อนอื่นไล่รายชื่อทุกคนที่แวะเข้าห้องเสียงวันนี้ เรียงตามเวลาที่เข้าห้องครั้งแรก
        entrants_sorted = sorted(filtered_stats, key=lambda x: x[1].get("first_join", "99:99"))
        entrant_lines = [f"{get_realtime_name(u_id, info['name'])} (เข้าห้องครั้งแรก {info.get('first_join', '-')})" for u_id, info in entrants_sorted]

        report = f"📊 **สรุปสถิติห้องเสียง (ประจำวันที่ {today_str})**\n"
        report += f"🚪 วันนี้มี {len(entrant_lines)} คนแวะเข้าห้องเสียง: " + ", ".join(entrant_lines) + "\n\n"

        top_name = get_realtime_name(sorted_stats[0][0], sorted_stats[0][1]['name'])
        
        for i, (u_id, info) in enumerate(sorted_stats, 1):
            ts = info['total_time']
            if ts >= 3600:
                time_display = f"{int(ts//3600)}ชม. {int((ts%3600)//60)}นาที"
            else:
                time_display = f"{max(1, int(ts//60))}นาที"
            
            display_name = get_realtime_name(u_id, info['name'])
            report += f"**{i}.** {display_name}: {time_display}\n"

        await ctx.send(report)
        
        if ctx.guild.voice_client:
            await bagley_speak(ctx.guild, f"รายงานผลของวันนี้ครับ อันดับหนึ่งคือคุณ {top_name} คุยนานที่สุดครับ")

    except Exception as e:
        print(f"🚨 ERROR ระบบสรุปสถิติห้องเสียง: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงข้อมูลสถิติครับ")


@bot.hybrid_command(name="guard_room", description="สั่งให้แบ็คลี่เปิด-ปิดโหมดเฝ้าห้องเสียงนี้ไว้ ไม่ให้บอทออกจากห้องเวลาร้าง")
@app_commands.choices(mode=[
    app_commands.Choice(name="เปิดระบบ (On)", value="on"),
    app_commands.Choice(name="ปิดระบบ (Off)", value="off")
])
async def guard_room(ctx: commands.Context, mode: str = None):
    
    if not ctx.guild.voice_client:
        return await ctx.send("❌ แบ็คลี่ต้องอยู่ในห้องเสียงก่อนถึงจะสั่งเฝ้าห้องได้ครับ!")

    guild_id = ctx.guild.id
    current_status = state.room_guard_status.get(guild_id, False)

    # 1. จัดการสถานะตามเงื่อนไขอัจฉริยะ (Toggle หรือ On/Off)
    if mode is None:
        # ถ้าพิมพ์ /guard_room เปล่า ๆ หรือดักคำพูดทั่วไป ให้สลับสถานะ
        new_status = not current_status
    else:
        # ถ้าเลือกช้อยส์หรือมาจากระบบคัดกรองคำพูด (AI Router อาจส่งคำที่ผู้ใช้พูดมาตรงๆ เช่น
        # "เฝ้าห้องนี้ไว้นะ" / "เลิกเฝ้าห้องแล้ว" ไม่ใช่แค่คำว่า on/off ตรงๆ เท่านั้น เลยต้องดักคำ
        # ใกล้เคียงให้ครอบคลุมขึ้น เช็คฝั่ง "ปิด" ก่อนเสมอ เพราะคำพวกนี้มักมีคำว่า "เฝ้า" ปนอยู่ด้วย
        # (เช่น "เลิกเฝ้า" มีคำว่า "เฝ้า" ปนอยู่ ถ้าเช็คฝั่งเปิดก่อนจะตีความผิดเป็นเปิดแทน)
        mode_lower = mode.lower().strip()
        off_keywords = ("off", "ปิด", "stop", "เลิก", "หยุด", "ไม่ต้อง")
        on_keywords = ("on", "เปิด", "start", "เฝ้า", "คุ้มกัน", "ปกป้อง", "guard")
        if any(kw in mode_lower for kw in off_keywords):
            new_status = False
        elif any(kw in mode_lower for kw in on_keywords):
            new_status = True
        else:
            # คำที่ส่งมาไม่ตรงกับที่รู้จักเลย กันเหนียวด้วยการสลับสถานะแทนที่จะปล่อยให้คำสั่งพังไปเฉยๆ
            new_status = not current_status

    state.room_guard_status[guild_id] = new_status

    # 2. ทำงานตามสถานะใหม่ที่เซ็ตไว้
    if state.room_guard_status[guild_id]:
        text_msg = "🛡️ เปิดโหมดสายตรวจแล้วครับ! แบ็คลี่จะปักหลักเฝ้าห้องเสียงนี้ไว้ให้เอง ไม่หนีไปไหนแน่นอนคัปพ้ม!"
        voice_msg = "เปิดโหมดสายตรวจแล้วครับ ผมจะเฝ้าห้องนี้ไว้ให้เองครับ"
    else:
        text_msg = "🔓 ปิดโหมดสายตรวจแล้วคัปพ้ม ต่อจากนี้ถ้าห้องร้าง แบ็คลี่จะถอนกำลังออกตามปกติถ้าร้างนะ!"
        voice_msg = "ปิดโหมดสายตรวจแล้วครับ ปล่อยตัวตามปกติแล้วคัป"

    # 3. ส่งข้อความในแชท
    await ctx.send(text_msg)
    
    # 4. สั่งให้บอทพูดออกไมค์ (ถ้าไม่ได้เปิดเพลงแช่อยู่)
    if not state.is_playing_music:
        try:
            await bagley_speak(ctx.guild, voice_msg)
        except Exception as e:
            print(f"Guard Room Speech Error: {e}")

    # 5. 🚪 [แก้บั๊ก] ถ้าปิดโหมดเฝ้าห้อง และห้องตอนนี้ "ว่างอยู่แล้วตั้งแต่ก่อนสั่ง" (เหลือแบ็คลี่คนเดียว)
    # ให้เช็คแล้วถอนกำลังออกทันทีเลย ไม่ต้องรอให้มีคนเข้า-ออกห้องอีกครั้งก่อน — เดิมตรรกะ "ห้องร้างให้ออก"
    # อยู่ใน on_voice_state_update เท่านั้น ซึ่งทำงานเฉพาะตอนมี event คนเข้า/ออกห้องจริงๆ ถ้าห้องว่าง
    # อยู่ก่อนแล้วตั้งแต่ต้น (ไม่มี event ใหม่เกิดขึ้นเลยหลังสั่งปิดโหมด) บอทเลยไม่เคยถูกกระตุ้นให้เช็คซ้ำ
    if not state.room_guard_status[guild_id]:
        vc = ctx.guild.voice_client
        if vc and vc.channel and len(vc.channel.members) == 1 and bot.user in vc.channel.members:
            if vc.channel.id not in state.created_party_channels:
                print(f"DEBUG: /guard_room ปิดโหมดแล้วพบว่าห้อง '{vc.channel.name}' ว่างอยู่แล้ว แบ็คลี่ถอนกำลังออกทันทีครับ")
                try:
                    await vc.disconnect()
                    state.voice_report_status.pop(guild_id, None)
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนถอนกำลังหลังปิดโหมดเฝ้าห้อง: {e}")


@bot.hybrid_command(name="party_recall", description="ดึงทุกคนในห้องปาร์ตี้ล่าสุดที่เราสร้าง กลับมาที่ห้องเสียงปัจจุบันของเรา")
async def party_recall(ctx: commands.Context):
    # 🔍 เช็กก่อนว่าคุณชะอมอยู่ในห้องเสียงไหม (เพราะเราจะดึงคนมาหาห้องที่เรานั่งอยู่คัป)
    if not ctx.author.voice:
        return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงปลายทางก่อนนะครับ ถึงจะเรียกเพื่อนกลับมาได้!")
        
    target_channel = ctx.author.voice.channel
    guild_id = ctx.guild.id

    # 🔍 หาห้องปาร์ตี้ล่าสุดที่ระบบสร้างขึ้น (ดูจากตัวแปรลิสต์ห้องปาร์ตี้ของกิลด์นี้)
    # สมมติว่าคุณเก็บ ID ไว้ในลิสต์ global ชื่อ created_party_channels
    if not state.created_party_channels:
        return await ctx.send("❌ แบ็คลี่หาประวัติห้องปาร์ตี้ที่สร้างไว้ไม่เจอเลยครับ!")

    # ดึง ID ห้องล่าสุดที่เพิ่งสร้างขึ้นมา
    last_party_id = state.created_party_channels[-1]
    source_channel = ctx.guild.get_channel(last_party_id)

    if not source_channel or not isinstance(source_channel, discord.VoiceChannel):
        return await ctx.send("❌ ดูเหมือนห้องปาร์ตี้ล่าสุดจะโดนลบ หรือหาไม่เจอแล้วครับ")

    # 👥 นับจำนวนคนในห้องปาร์ตี้นั้น (ไม่นับบอท)
    members_to_move = [m for m in source_channel.members if not m.bot]

    if not members_to_move:
        return await ctx.send(f"ห้อง **{source_channel.name}** ไม่มีเพื่อน ๆ นั่งอยู่เลยครับ ว่างเปล่าเลยคัป!")

    await ctx.defer() # ป้องกันอินเตอร์แอกชันหมดอายุเวลาคนเยอะคัปพ้ม

    success_count = 0
    # 🚀 เริ่มปฏิบัติการดึงพรรคพวกกลับบ้าน!
    for member in members_to_move:
        try:
            await member.edit(voice_channel=target_channel)
            success_count += 1
        except Exception as e:
            print(f"❌ ดึงตัว {member.display_name} พัง: {e}")

    # ย้ายแบ็คลี่ตามมาด้วยถ้าบอทเคยหลงไปอยู่ในนั้น
    if ctx.guild.voice_client and ctx.guild.voice_client.channel == source_channel:
        await ctx.guild.voice_client.move_to(target_channel)

    msg = f"🛸 ดึงพรรคพวกจากห้อง {source_channel.name} กลับมารวมกันที่ห้อง {target_channel.name} จำนวน {success_count} คน เรียบร้อยแล้วครับ!"
    await ctx.send(msg)
    await bagley_speak(ctx.guild, f"ดึงเพื่อน ๆ กลับห้องหลักเรียบร้อยแล้วครับ การแข่งขันจบลงแล้วสินะครับ")


@bot.hybrid_command(name="pull_room", description="เลือกดึงสมาชิกทั้งหมดจากห้องอื่น ย้ายมาที่ห้องเสียงปัจจุบันของเรา")
async def pull_room(ctx: commands.Context):
    # 🔍 เช็กว่าคนใช้คำสั่งนั่งอยู่ในห้องเสียงปลายทางก่อนไหมคัป
    if ctx.author.voice:
        current_channel = ctx.author.voice.channel
        
        # 💡 ส่งแค่ ctx.author กับห้องปัจจุบัน (current_channel) เข้าไปใน View คัปพ้ม คลีนขึ้นเยอะเลย!
        view = PullRoomView(ctx.author, current_channel)
        await ctx.send("🔮 คุณต้องการดึงคนทั้งหมดจากห้องไหน มารวมกันที่ห้องนี้ดีครับ?", view=view)
    else:
        await ctx.send("คุณต้องเข้ามานั่งในห้องเสียงหลักก่อนนะครับ แบ็คลี่ถึงจะรู้ว่าจะให้ดึงคนมาไว้ที่ห้องไหนคัปพ้ม!")


@bot.hybrid_command(
    # 🛠️ [แก้บั๊ก] Discord จำกัดความยาว description ของ slash command ไว้ที่ 100 ตัวอักษร
    # เท่านั้น ของเดิมยาวเกินลิมิต ทำให้ bot.tree.sync() ล้มทั้งก้อน (error code 50035)
    # ส่งผลให้ "ทุกคำสั่งในบอท" รวมถึงคำสั่งใหม่ (watch_live_chat ฯลฯ) ไม่ขึ้นในดิสคอร์ดเลย
    # คำอธิบายแบบเต็มยังคงอยู่ที่คอมเมนต์นี้ ส่วนที่ส่งให้ Discord ตัดให้สั้นลงแทน:
    # "ชวน" — สั่งให้แบ็คลี่วาร์ปตัวเองเข้าไปในห้องเสียงของเพื่อนคนนั้นโดยตรง เปิดไมค์พูดตื๊อ
    # เชิญตัวต่อตัว 3 รอบ แล้ววาร์ปกลับห้องเดิม ใช้เมื่อผู้ใช้พูดว่า 'ชวน' และต้องการให้บอท
    # ไปตื๊อถึงห้องเสียงเป้าหมายเอง (ต่างจาก call_member/'เรียก' ที่แค่ส่งข้อความส่วนตัว (DM)
    # ไปแจ้ง ไม่วาร์ปตามไปหา)
    name="invite_voice",
    description="ชวน — วาร์ปเข้าห้องเสียงเพื่อน ตื๊อเชิญ 3 รอบแล้ววาร์ปกลับ (ต่างจาก call_member ที่แค่ส่ง DM)"
)
async def invite_voice(ctx: commands.Context, เพื่อนที่จะชวน: discord.Member):
    await execute_warp_invite(ctx, ctx.author, เพื่อนที่จะชวน)


@bot.hybrid_command(
    # 🛠️ [แก้บั๊ก] เหตุผลเดียวกับ invite_voice ด้านบน (Discord จำกัด description ที่ 100 ตัวอักษร)
    # คำอธิบายแบบเต็ม: "เรียก" — สั่งให้แบ็คลี่ส่งข้อความส่วนตัว (DM) ไปหาเพื่อนคนนั้น พร้อมปุ่ม
    # ตอบรับ/ปฏิเสธ และลิงก์เชิญเข้าห้องเสียงให้เขากดไปเอง บอทไม่ได้วาร์ปตัวเองตามไปหา ใช้เมื่อ
    # ผู้ใช้พูดว่า 'เรียก' และแค่ต้องการฝากข้อความ/ลิงก์ไปแจ้งเฉยๆ (ต่างจาก invite_voice/'ชวน'
    # ที่บอทวาร์ปเข้าไปตื๊อถึงห้องเสียงเป้าหมายแล้ววาร์ปกลับ)
    name="call_member",
    description="เรียก — ส่ง DM แจ้งเพื่อนพร้อมปุ่มตอบรับ/ปฏิเสธ+ลิงก์ห้องเสียง ไม่วาร์ปตามไป (ต่างจาก invite_voice)"
)
async def call_member(ctx: commands.Context, เพื่อนที่จะเรียก: discord.Member):
    await execute_dm_call(ctx, ctx.author, เพื่อนที่จะเรียก)
