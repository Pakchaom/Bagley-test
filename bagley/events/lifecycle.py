"""bagley/events/lifecycle.py — บอทเริ่มทำงาน / สมาชิกใหม่ / ข้อผิดพลาดคำสั่ง"""
import asyncio
import discord
from discord.ext import commands

from bagley.core.app import bot, client, tree
from bagley.core.config import ALLOWED_TEACH_USERS
from bagley.core.logutil import print
from bagley.core.security import is_stream_mode_on, is_user_blocked
from bagley.data.storage import get_realtime_name, load_settings
from bagley.db import conn, init_db
from bagley.features import autonomy as bagley_autonomy, ephemeral_tools as ephemeral_tools, knowledge as bagley_knowledge, learning as bagley_learning, rooms as bagley_rooms, rules as bagley_rules, trust as bagley_trust
from bagley.phrases import say
from bagley.services.voice_relay import start_voice_relay_server
from bagley.tasks.loops import auto_brain_cleanup, check_expired_schedules, check_friend_reminders, check_reminders, daily_announcement_task, follow_creator_task
from bagley.voice import ack as voice_ack
from bagley.voice.tts import bagley_speak, warm_cache


@bot.event
async def on_ready():
    if not auto_brain_cleanup.is_running():
        auto_brain_cleanup.start()
    print(f'--- {bot.user.name} Online ---')
    client.reload()
    print(f"🧠 AI พร้อมใช้: chat={client.available('chat')} fast={client.available('fast')} vision={client.available('vision')}")
    if not client.available('chat'):
        print("⚠️ ยังไม่ได้ใส่ API key ของ AI ใน .env (GROQ_API_KEY / CEREBRAS_API_KEY / GITHUB_TOKEN ...) แชทกับ AI จะใช้ไม่ได้")
    if not getattr(bot, "_tts_warm_started", False):
        bot._tts_warm_started = True
        asyncio.create_task(warm_cache())
        asyncio.create_task(voice_ack.ensure_loaded())   # ไฟล์เสียงขานรับ (ครับ/ค้าบ/ครับผม) สร้างครั้งแรกครั้งเดียว + โหลดค้างไว้
    
    try:
        init_db()
        print("🗄️ Database: member_profiles table is ready.")
    except Exception as e:
        print(f"Database Error: {e}")

    try:
        synced = await tree.sync()
        print(f"📡 Synced {len(synced)} commands.")
    except Exception as e: 
        print(f"Sync Error: {e}")
        
    # 🔄 [เปลี่ยนระบบแล้ว] YouTube Monitoring ไม่วนลูปอัตโนมัติอีกต่อไป
    # ใช้คำสั่ง /yt_check หรือพิมพ์ "แชร์สตรีมล่าสุดให้หน่อย" เพื่อเช็คทันทีแทน
    print("📺 YouTube Monitoring: เปลี่ยนเป็นโหมดเช็คตามคำสั่ง (ใช้ /yt_check หรือพิมพ์ 'แชร์สตรีมล่าสุดให้หน่อย')")

    if not check_reminders.is_running():
        check_reminders.start()
    
    print(f"--- Bagley พร้อมทำหน้าที่เลขาแล้วครับ! ---")

    if not check_friend_reminders.is_running():
        check_friend_reminders.start()

    if not check_expired_schedules.is_running():
        check_expired_schedules.start()
        print("🗑️ ระบบ Reset ตารางนัดหมายที่ถึงเวลาแล้ว: Started.")

    if not follow_creator_task.is_running():
        follow_creator_task.start()
    print(f"Bagley พร้อมเป็นเงาติดตามตัวคุณชะอมแล้วครับ!")

    if not daily_announcement_task.is_running():
        daily_announcement_task.start()
    print("⏰ ระบบ daily_announcement_task เริ่มทำงานนับเวลาถอยหลังแล้วครับคัป")

    if not getattr(bot, "_voice_relay_started", False):
        bot._voice_relay_started = True
        asyncio.create_task(start_voice_relay_server())

    # ============================================================
    # 🧠🌱🤝⚡ ระบบเรียนรู้ / อยากพูดเอง / คำสั่งชั่วคราวที่ AI เขียนสด
    # ============================================================
    try:
        bagley_learning.configure(bot, client, conn)
        bagley_learning.init_learning_db(conn)
        if not bagley_learning.learning_loop.is_running():
            bagley_learning.learning_loop.start()

        bagley_autonomy.configure(bot, client, bagley_speak, get_realtime_name, conn=conn)
        bagley_autonomy.init_silence_db(conn)
        if not bagley_autonomy.autonomy_loop.is_running():
            bagley_autonomy.autonomy_loop.start()

        bagley_trust.configure(conn)
        bagley_trust.init_trust_db(conn)

        # 🏷️🔒 [Rooms] เฝ้าห้องที่ถูก /rename_room หรือ /lock_room ไว้ พอห้องว่างจากคนจริง
        # แล้วจะรีเซ็ตชื่อ/ปลดล็อกกลับเป็นค่าเดิมให้อัตโนมัติ (ลงทะเบียนแค่ครั้งเดียวกัน on_ready ยิงซ้ำ)
        if not getattr(bot, "_bagley_rooms_watcher_registered", False):
            bot._bagley_rooms_watcher_registered = True
            bot.add_listener(bagley_rooms.watch_voice_state, "on_voice_state_update")

        # คนใน ALLOWED_TEACH_USERS ได้สิทธิ์สร้างความสามารถชั่วคราวทันทีเสมอ
        # คนอื่นๆ จะได้สิทธิ์อัตโนมัติถ้าคุยกับแบ็คลี่คุ้นเคยพอ (ดู bagley_trust.py)
        ephemeral_tools.configure(client, is_user_blocked_fn=is_user_blocked)
        ephemeral_tools.ALLOWED_DYNAMIC_USERS = set(ALLOWED_TEACH_USERS)

        # 📜 [Rules] สอนแบ็คลี่ด้วยการพิมพ์คุยเฉยๆ (เช่น "จำไว้ว่าห้ามพูดคำหยาบ") ไม่ต้องพิมพ์ /teach
        # ใช้เกณฑ์สิทธิ์เดียวกับ ephemeral_tools เพราะกฎที่จำไปมีผลข้ามทุกเซิร์ฟเวอร์
        bagley_rules.configure(client, conn, is_user_blocked_fn=is_user_blocked)
        bagley_rules.init_rules_db(conn)
        bagley_rules.ALLOWED_RULE_TEACHERS = set(ALLOWED_TEACH_USERS)

        # 🧠 [Knowledge] ความจำระยะยาว: เรียนรู้เรื่องส่วนตัว/ความรู้ที่ถูกสอนจากการคุยเอง (ไม่ต้องพิมพ์ "จำไว้ว่า")
        bagley_knowledge.configure(client, conn, is_user_blocked_fn=is_user_blocked)
        bagley_knowledge.init_knowledge_db(conn)

        print("🧠 ระบบเรียนรู้ / อยากพูดเอง / คำสั่งชั่วคราว: Started.")
    except Exception as e:
        print(f"⚠️ ระบบเรียนรู้/อยากพูดเอง/คำสั่งชั่วคราว เริ่มไม่สำเร็จ: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        return await ctx.send("🛑 **ปฏิเสธการเข้าถึง:** " + say("owner_only"), delete_after=10)
    
    elif isinstance(error, commands.CommandOnCooldown):
        return await ctx.send("⚠️ " + say("cooldown", sec=f"{error.retry_after:.1f}"), delete_after=5)

    elif isinstance(error, commands.CheckFailure):
        if ctx.guild is not None and is_stream_mode_on(ctx.guild.id):
            return await ctx.send(
                "🎥 " + say("stream_locked"),
                delete_after=10
            )
        return await ctx.send("🛑 " + say("no_permission"), delete_after=10)

    else:
        print(f'Ignoring exception in command {ctx.command}:', error)


@bot.event
async def on_member_join(member):
    settings = load_settings()
    channel_id = settings.get(str(member.guild.id))
    
    # 1. คำนวณความเสี่ยง (อายุบัญชี)
    account_age_days = (discord.utils.utcnow() - member.created_at).days
    is_suspicious = account_age_days < 7  # ถ้าต่ำกว่า 7 วันคืออีนี่ถือว่าน่าสงสัย
    
    # 2. ส่งรายงานเข้าห้องแชท (ถ้าเซ็ตไว้)
    if channel_id:
        channel = member.guild.get_channel(channel_id)
        if channel:
            color = 0xff0000 if is_suspicious else 0x00ff00
            status_text = "⚠️ [พบไอดีต้องสงสัย]" if is_suspicious else "✅ [สมาชิกใหม่ระดับปกติ]"
            
            embed = discord.Embed(title=f"{status_text} เข้าระบบ", color=color)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="เป้าหมาย", value=f"{member.display_name} ({member.id})", inline=False)
            embed.add_field(name="อายุบัญชี", value=f"{account_age_days} วัน", inline=True)
            embed.set_footer(text="Hacker Vision กำลังเฝ้าดูอยู่ครับ")
            await channel.send(embed=embed)

    # 3. ระบบ "รายงานแบบอัตโนมัติด้วยเสียง" ถ้าแบ็คลี่อยู่ในห้องเสียง
    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
    voice_client = member.guild.voice_client
    if voice_client and voice_client.is_connected():
        
        if is_suspicious:
            voice_report = f"ครับ! ตรวจพบไอดีผีชื่อ {get_realtime_name(member.id, member.display_name)} เพิ่งสมัครมาได้แค่ {account_age_days} วัน แฝงตัวเข้ามาในเซิร์ฟเวอร์ครับ ระวังตัวด้วยนะ!"
        else:
            voice_report = f"มีพรรคพวกใหม่ชื่อ {get_realtime_name(member.id, member.display_name)} เชื่อมต่อเข้ามาในเซิร์ฟเวอร์ครับ ดูเหมือนจะเป็นพลเมืองปกติดีครับ"
        
        # สั่งให้แบ็คลี่พูด
        await bagley_speak(member.guild, voice_report)
