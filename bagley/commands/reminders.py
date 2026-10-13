"""bagley/commands/reminders.py — คำสั่งแจ้งเตือน นาฬิกาปลุก ตารางนัดหมาย"""
import asyncio
import discord
import secrets
from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands

from bagley.core import state
from bagley.core.app import bot
from bagley.core.config import bangkok_tz
from bagley.core.logutil import print
from bagley.data.storage import _ensure_schedule_ids, _normalize_schedule_date, _schedule_sort_key, get_realtime_name, load_user_data, save_user_data
from bagley.phrases import say
from bagley.ui.views import IdentityListPaginator, ScheduleDeleteView
from bagley.voice.tts import FFMPEG_PATH, bagley_speak, bagley_speak_wait


@bot.hybrid_command(name="alarm", description="ตั้งเวลาปลุกเพื่อน (เช่น 07:00 หรือ 16:30)")
async def alarm(
    ctx: commands.Context, 
    member: discord.Member, 
    time_str: str, 
    message: str = "ตื่นได้แล้วครับ!"
):
    try:
        clean_time = time_str.replace(".", ":")
        if ":" in clean_time:
            parts = clean_time.split(":")
            if len(parts[0]) == 1:
                parts[0] = "0" + parts[0]
            clean_time = ":".join(parts)

        target_time = datetime.strptime(clean_time, "%H:%M").time()
        now = datetime.now()
        target_datetime = datetime.combine(now.date(), target_time)

        if target_datetime < now:
            target_datetime += timedelta(days=1)

        wait_seconds = (target_datetime - now).total_seconds()

        await ctx.send(f"รับทราบครับ! ผมจะตั้งนาฬิกาปลุกไว้ที่เวลา {clean_time} และจะแจ้งคุณ {get_realtime_name(member.id, member.display_name)} ทันทีครับ")

        await asyncio.sleep(wait_seconds)

        if member.voice and member.voice.channel:
            # เช็คและเชื่อมต่อห้องเสียง
            if not ctx.voice_client or ctx.voice_client.channel != member.voice.channel:
                if ctx.voice_client:
                    await ctx.voice_client.move_to(member.voice.channel)
                    vc = ctx.voice_client
                else:
                    vc = await member.voice.channel.connect()
            else:
                vc = ctx.voice_client

            guild_id = ctx.guild.id
            state.active_alarms[guild_id] = True

            print(f"⏰ [Bagley] เริ่มกระบวนการปลุกคุณ {member.display_name} แล้วครับ")
            
            while ctx.voice_client is not None and state.active_alarms.get(guild_id, False):
                
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio('iphone_alarm.mp3', executable=FFMPEG_PATH)
                )
                source.volume = 0.4 
                vc.play(source)

                while vc.is_playing(): 
                    if not state.active_alarms.get(guild_id, False) or ctx.voice_client is None:
                        vc.stop()
                        break
                    await asyncio.sleep(0.1)

                if ctx.voice_client is None or not state.active_alarms.get(guild_id, False):
                    break

                msg = f"คุณ {get_realtime_name(member.id, member.display_name)} ครับ ขณะนี้เวลา {clean_time} แล้วนะครับ คุณ {get_realtime_name(ctx.author.id, ctx.author.display_name)} ฝากให้ผมมาปลุกคุณด้วยข้อความว่า: {message}"
                await bagley_speak_wait(ctx.guild, msg)

                for _ in range(20):
                    if not state.active_alarms.get(guild_id, False) or ctx.voice_client is None:
                        break
                    await asyncio.sleep(0.1)
            
            if guild_id in state.active_alarms:
                del state.active_alarms[guild_id]
            print(f"🛑 [Bagley] ปิดระบบลูปนาฬิกาปลุกในเซิร์ฟเวอร์ {ctx.guild.name} เรียบร้อย")
            
        else:
            await ctx.send(f"ถึงเวลา {clean_time} แล้วครับ แต่ดูเหมือนคุณ {get_realtime_name(member.id, member.display_name)} จะไม่อยู่ในห้องเสียงแล้ว")

    except ValueError:
        await ctx.send("คุณใส่รูปแบบเวลาผิดครับ! กรุณาใส่เป็น HH:MM หรือ HH.MM (เช่น 07:00 หรือ 7.30) นะครับ")


@bot.hybrid_command(name="clear_my_reminders", description="ลบรายการแจ้งเตือนทั้งหมดของตัวคุณเอง")
async def clear_my_reminders(ctx: commands.Context):
    data = load_user_data()
    user_id_str = str(ctx.author.id)
    
    has_reminder = "reminders" in data and any(r["user_id"] == user_id_str for r in data["reminders"])
    has_alarm = "alarms" in data and any(a["user_id"] == user_id_str for a in data["alarms"])
    
    if has_reminder or has_alarm:
        if "reminders" in data:
            data["reminders"] = [r for r in data["reminders"] if r["user_id"] != user_id_str]
            
        if "alarms" in data:
            data["alarms"] = [a for a in data["alarms"] if a["user_id"] != user_id_str]
            
        save_user_data(data)
        await ctx.send(say("reminders_cleared"))
    else:
        await ctx.send("คุณยังไม่มีรายการแจ้งเตือนหรือนาฬิกาปลุกในระบบเลยครับ")


@bot.hybrid_command(name="stop_alarm", description="สั่งปิดนาฬิกาปลุกที่กำลังส่งเสียงดังอยู่ในตอนนี้")
async def stop_alarm(ctx: commands.Context):
    guild_id = ctx.guild.id
    
    if guild_id in state.active_alarms and state.active_alarms[guild_id]:
        state.active_alarms[guild_id] = False
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.send("⏰ **[Bagley System]** ปิดนาฬิกาปลุกประจำเซิร์ฟเวอร์เรียบร้อยครับ! แยกย้ายไปนอนต่อ.. เอ้ย! ไปทำภารกิจกันได้เลยครับ!")
        if ctx.guild and ctx.guild.voice_client:
            await bagley_speak(ctx.guild, say("alarm_stopped"))
    else:
        await ctx.send("❌ ตอนนี้ไม่มีนาฬิกาปลุกกำลังทำงานในเซิร์ฟเวอร์นี้ครับ")


@bot.hybrid_command(name="clear_user_reminders", description="[Admin] ลบรายการแจ้งเตือนทั้งหมดของสมาชิกที่ระบุ")
async def clear_user_reminders(ctx: commands.Context, member: discord.Member):
    data = load_user_data()
    target_id_str = str(member.id)
    
    has_reminder = "reminders" in data and any(r["user_id"] == target_id_str for r in data["reminders"])
    has_alarm = "alarms" in data and any(a["user_id"] == target_id_str for a in data["alarms"])
    
    if has_reminder or has_alarm:
        if "reminders" in data:
            data["reminders"] = [r for r in data["reminders"] if r["user_id"] != target_id_str]
            
        if "alarms" in data:
            data["alarms"] = [a for a in data["alarms"] if a["user_id"] != target_id_str]
            
        save_user_data(data)
        await ctx.send(f"รับทราบครับ! ลบรายการแจ้งเตือนและนาฬิกาปลุกทั้งหมดของ คุณ {get_realtime_name(member.id, member.display_name)} ให้เรียบร้อยแล้วครับ")
    else:
        await ctx.send(f"ไม่พบรายการแจ้งเตือนหรือนาฬิกาปลุกของ คุณ {get_realtime_name(member.id, member.display_name)} ในระบบครับ")


@bot.hybrid_command(name="remind", description="สั่งให้แบ็คลี่บันทึกกำหนดการและแจ้งเตือนในห้องเสียงเมื่อถึงวัน")
@app_commands.describe(
    date="ระบุวันที่ (เช่น 2026-07-11 หรือใส่แค่ตัวเลขวันที่ เช่น '11')",
    time="ระบุเวลา (เช่น 21:00, 3 ทุ่ม, 5 โมงเย็น)",
    event="กิจกรรมที่ต้องการให้เตือน (เช่น แข่ง VCT, ซ้อมทีม Scrim, ตี้หมูกระทะ)"
)
async def slash_remind(ctx: commands.Context, date: str, time: str, event: str):
    # ดึงเวลาไทยปัจจุบันขึ้นมาอ้างอิง
    now = datetime.now(bangkok_tz)

    # 📅 แปลงค่าวันที่ให้เป็น YYYY-MM-DD เสมอ (รองรับ 'วันนี้'/'พรุ่งนี้'/'มะรืน'/เลขวันสั้นๆ ด้วย)
    # กันบั๊กเดิมที่พิมพ์ "เตือนฉันตอน 17:30 ว่า..." แล้ว AI Command Router เติมวันที่มาเป็นคำว่า
    # "วันนี้" ดิบๆ ทำให้ /schedule_list โชว์ผิดเพี้ยน และ check_expired_schedules เคลียร์ไม่ได้
    clean_date = _normalize_schedule_date(date, now)

    # โหลดไฟล์ความจำ JSON ปัจจุบันขึ้นมา
    user_data = load_user_data()
    if "schedules" not in user_data:
        user_data["schedules"] = []
        
    # บันทึกข้อมูลนัดหมายเข้าคลังความจำ (ใส่ id ไว้ด้วย เผื่อจะเอาไปลบผ่าน /delete_schedule ทีหลัง)
    new_job = {
        "id": secrets.token_hex(4),
        "date": clean_date,
        "time": time.strip(),
        "owner_id": ctx.author.id,
        "event": event.strip()
    }
    user_data["schedules"].append(new_job)
    save_user_data(user_data) # บันทึกลงไฟล์ JSON คัปพ้ม

    # 📤 ตอบกลับในห้องแชทเป็นภาษาไทยสไตล์แบ็คลี่สุดหล่อ!
    await ctx.send(
        f"🛸 **ล็อกเป้าหมายตารางงานเรียบร้อยคัป!**\n"
        f"📌 **กิจกรรม:** {event}\n"
        f"📅 **วันที่:** {clean_date}\n"
        f"⏰ **เวลา:** {time}\n"
        f"ปล่อยเป็นหน้าที่ของแบ็คลี่ได้เลย! พอถึงวันเดี๋ยวผมบินโดรนแวะเข้าห้องเสียงไปเปิดไมค์แจ้งเตือนให้คัปพ้ม! 🫡\n"
        f"-# ลืม/พิมพ์ผิดเดี๋ยวลบทีหลังได้นะครับ พิมพ์ `/delete_schedule` แล้วเลือกรายการที่จะลบได้เลย"
    )


@bot.hybrid_command(name="schedule_list", description="ดูตารางนัดหมาย/งานทั้งหมดที่คุณฝากแบ็คลี่จำไว้ (จาก /remind)")
async def schedule_list(ctx: commands.Context):
    try:
        user_data = load_user_data()
        schedules = user_data.get("schedules", [])

        # 🛠️ เผื่อมีรายการเก่าที่ยังไม่มี id (บันทึกไว้ก่อนมีระบบ /delete_schedule) เติมให้ครบ
        if _ensure_schedule_ids(schedules):
            user_data["schedules"] = schedules
            save_user_data(user_data)

        my_schedules = [s for s in schedules if str(s.get("owner_id")) == str(ctx.author.id)]

        if not my_schedules:
            return await ctx.send("ตอนนี้คุณยังไม่มีตารางนัดหมายที่ฝากผมจำไว้เลยครับ! ลองฝากไว้ด้วย `/remind` ได้เลยครับ")

        # 🗂️ เรียงตามวันที่ + เวลาก่อน-หลัง (นัดที่ใกล้ถึงก่อนจะขึ้นก่อน)
        my_schedules_sorted = sorted(my_schedules, key=_schedule_sort_key)

        formatted_list = [
            f"📅 **{s.get('date', 'ไม่ระบุวันที่')}** ⏰ **{s.get('time', 'ไม่ระบุเวลา')}** — 📌 {s.get('event', 'ไม่ระบุกิจกรรม')}"
            for s in my_schedules_sorted
        ]
        title_text = f"🗂️ ตารางนัดหมายของคุณ {get_realtime_name(ctx.author.id, ctx.author.display_name)}"

        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
        view.message = await ctx.send(
            content="-# อยากลบรายการไหน พิมพ์ `/delete_schedule` แล้วเลือกจากเมนูได้เลยครับ",
            embed=view.create_embed(),
            view=view
        )

    except Exception as e:
        print(f"🚨 ERROR ระบบดูตารางงาน: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงตารางนัดหมายครับ")


@bot.hybrid_command(
    name="delete_schedule",
    description="ลบตารางนัดหมาย/งานที่ฝากแบ็คลี่จำไว้ โดยเลือกได้ว่าจะลบรายการไหน"
)
async def delete_schedule(ctx: commands.Context):
    try:
        user_data = load_user_data()
        schedules = user_data.get("schedules", [])

        # 🛠️ เผื่อมีรายการเก่าที่ยังไม่มี id ให้เติมก่อน จะได้เลือกลบได้แม่นยำทุกรายการ
        if _ensure_schedule_ids(schedules):
            user_data["schedules"] = schedules
            save_user_data(user_data)

        my_schedules = [s for s in schedules if str(s.get("owner_id")) == str(ctx.author.id)]

        if not my_schedules:
            return await ctx.send("ตอนนี้คุณยังไม่มีตารางนัดหมายให้ลบเลยครับ! ลองฝากไว้ด้วย `/remind` ก่อนได้เลยครับ")

        my_schedules_sorted = sorted(my_schedules, key=_schedule_sort_key)

        view = ScheduleDeleteView(ctx.author, my_schedules_sorted)

        extra_note = ""
        if len(my_schedules_sorted) > 25:
            extra_note = f"\n-# (คุณมีทั้งหมด {len(my_schedules_sorted)} รายการ แต่เมนูเลือกได้สูงสุด 25 รายการที่ใกล้ถึงที่สุดก่อนนะครับ ลบไปทีละส่วนแล้วค่อยเรียกคำสั่งใหม่ได้)"

        view.message = await ctx.send(
            f"🗑️ เลือกตารางนัดหมายที่ต้องการลบจากเมนูด้านล่างได้เลยครับ (เลือกได้ทีละรายการ){extra_note}",
            view=view
        )

    except Exception as e:
        print(f"🚨 ERROR ระบบลบตารางงาน: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการลบตารางนัดหมายครับ")
