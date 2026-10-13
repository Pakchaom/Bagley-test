"""bagley/commands/admin.py — คำสั่งผู้ดูแลระบบ: sync, diagnostic, update, shutdown, log ฯลฯ"""
import asyncio
import discord
import os
import subprocess
import sys
import time
from discord import app_commands
from discord.ext import commands

from bagley.ai import persona
from bagley.core.app import bot, client
from bagley.core.config import ALLOWED_SHUTDOWN_USERS, ALLOWED_TEACH_USERS
from bagley.core.logutil import LOG_BUFFER, print
from bagley.core.security import is_developer
from bagley.core.util import make_gradle_bar, perform_cleanup
from bagley.data.storage import get_realtime_name, load_settings, load_user_data, save_settings
from bagley.db import conn
from bagley.phrases import say
from bagley.ui.views import RegisterModal
from bagley.voice.tts import bagley_speak


@bot.hybrid_command(name="sync", description="ซิงค์คำสั่งบอททั้งหมด (Owner Only)")
@commands.is_owner()
async def sync(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer(ephemeral=True)
    
    synced = await bot.tree.sync()
    
    msg = f"เรียบร้อยครับเจ้านาย! ซิงค์คำสั่งทั้งหมด {len(synced)} รายการให้แล้วครับ!"
    
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)
        
    # พูดรายงานผล
    await bagley_speak(ctx.guild, msg)


@bot.hybrid_command(name="reg_config", description="ตั้งค่าระบบรับยศลงทะเบียน (ล็อกคำถามชื่อเล่นและวันเกิดให้อัตโนมัติ)")
@app_commands.checks.has_permissions(administrator=True)
async def reg_config(ctx: commands.Context, role: discord.Role):
    final_questions = "ชื่อเล่นของคุณคืออะไร?|วันเกิดของคุณคือวันที่เท่าไหร่? (วว/ดด)"
    
    global conn
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO registration_settings VALUES (?, ?, ?)', 
              (ctx.guild.id, final_questions, role.id))
    conn.commit()
    
    await ctx.send(
        f"✅ **ตั้งค่าระบบลงทะเบียนเรียบร้อยครับแอดมิน!**\n"
        f"• ยศที่จะมอบให้เมื่อลงทะเบียนสำเร็จ: **{role.name}** ({role.mention})\n"
        f"• ระบบฟอร์มป๊อปอัปจะล็อกคำถาม 2 ช่องให้สมาชิกอัตโนมัติ:\n"
        f"  1. ช่องกรอกชื่อเล่น (สำหรับเซฟลงคลังความจำขานชื่อสถิติ)\n"
        f"  2. ช่องกรอกวันเกิด (วว/ดด)\n\n"
        f"*(ตอนนี้สมาชิกในเซิร์ฟเวอร์สามารถพิมพ์ `/register` เพื่อเปิดป๊อปอัปกรอกข้อมูลได้ทันทีเลยครับ!)*"
    )


@bot.hybrid_command(name="register", description="ลงทะเบียนเข้าสู่ระบบและรับยศด้วยป๊อปอัปฟอร์ม")
async def register(ctx: commands.Context):
    if not ctx.interaction:
        return await ctx.send("❌ คำสั่งลงทะเบียนเวอร์ชันใหม่ ต้องพิมพ์เรียกใช้งานผ่านสแลชคอมมานด์ `/register` เท่านั้นครับ! (พิมพ์ปกติบอทจะเปิดหน้าต่างป๊อปอัปให้ไม่ได้คัปพ้ม)")

    global conn
    c = conn.cursor()
    c.execute('SELECT target_role_id FROM registration_settings WHERE guild_id = ?', (ctx.guild.id,))
    config = c.fetchone()

    if not config:
        return await ctx.send("❌ แอดมินยังไม่ได้ตั้งค่าระบบเลยครับ!")

    target_role_id = config[0]
    
    await ctx.interaction.response.send_modal(RegisterModal(target_role_id=target_role_id))


@bot.hybrid_command(name="diagnostic", description="รันระบบตรวจสอบสถานะการทำงานทั้งหมด")
async def diagnostic(ctx: commands.Context):
    # เริ่มต้นส่งข้อความในแชท
    msg = await ctx.send("🤖 **Bagley Diagnostic Initiated...**\n`กำลังตรวจสอบระบบส่วนกลาง...`")
    
    # ส่วนที่ 1: ตรวจสอบฐานข้อมูล (Memory Core)
    db_status = "ONLINE"
    try:
        conn.cursor().execute("SELECT 1")
    except:
        db_status = "OFFLINE"
    
    await asyncio.sleep(1)
    await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`")

    # ส่วนที่ 2: ตรวจสอบการเชื่อมต่อ API (Neural Link)
    ping = round(bot.latency * 1000)
    await asyncio.sleep(1)
    await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`AI: {client.stats_text()}`")

    # ส่วนที่ 3: ตรวจสอบระบบเสียง (Audio Output)
    vc = ctx.guild.voice_client
    voice_info = "READY" if vc and vc.is_connected() else "IDLE"
    await asyncio.sleep(1)
    await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`AI: {client.stats_text()}`\n`Audio Output: {voice_info}`")

    # --- สรุปผลด้วยเสียง ---
    if vc and vc.is_connected():
        # ถ้าบอทอยู่ในห้องเสียง ให้รายงานเป็นลำดับ
        report_text = f"ตรวจสอบระบบเสร็จสิ้น ระบบฐานข้อมูล {db_status}, ระบบเนือรัลลิงก์ปกติ, ระบบเสียงพร้อมใช้งาน, ทุกระบบทำงานเต็มรูปแบบหนึ่งร้อยเปอร์เซ็นต์ครับ"
        
        # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
        await bagley_speak(ctx.guild, report_text)
        
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`AI: {client.stats_text()}`\n`Audio Output: {voice_info}`\n\n✅ **ทุกระบบพร้อมสอดแนมครับ!**")
    else:
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`AI: {client.stats_text()}`\n`Audio Output: {voice_info}`\n\n⚠️ **การตรวจสอบเสร็จสิ้น (ระบบเสียงไม่ได้เชื่อมต่อ)**")


@bot.hybrid_command(name="shutdown", description="⚡ สั่งปิดบอทพร้อมกับดับเครื่องคอมพิวเตอร์บริษัทระยะไกล")
async def shutdown_all(ctx: commands.Context):
    if ctx.author.id not in ALLOWED_SHUTDOWN_USERS:
        await ctx.send(
            "❌ **[ACCESS DENIED]** ไม่มีระดับสิทธิ์เพียงพอในการสั่งดับเครื่องคอมพิวเตอร์ครับ!",
            ephemeral=True
        )
        return

    await ctx.send(
        f"🛸 **[DEDSEC REMOTE HACK]** รับทราบครับคุณ **{get_realtime_name(ctx.author.id, ctx.author.display_name)}**! กำลังปิดระบบแบ็คลี่ และ Shut Down คอมพิวเตอร์ใน 5 วินาที... 💻💤"
    )

    await asyncio.sleep(5.0)

    print(f"🛸 คำสั่งอนุมัติโดย {ctx.author.name} กำลังทำการปิดบอท และ Shut Down เครื่อง...")

    await bot.close()

    if sys.platform == "win32":
        os.system("shutdown /s /f /t 0")
    else:
        os.system("sudo shutdown -h now")


@bot.hybrid_command(name="update_bot", description="ดึงโค้ดล่าสุดจาก GitHub แบบล้างประวัติชนกันและรีสตาร์ทบอท")
async def update_bot(ctx: commands.Context):
    await ctx.defer()
    
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    start_time = time.time()
    
    status_msg = await ctx.send(
        "📡 **[SYSTEM UPDATE]** กำลังเริ่มกระบวนการดึงโค้ด...\n" + 
        make_gradle_bar(0, "STARTING", start_time)
    )
    await asyncio.sleep(1.0)
    
    try:
        await status_msg.edit(content="📡 **[SYSTEM UPDATE]** กำลังสั่ง Git Fetch...\n" + make_gradle_bar(20, "EXECUTING :gitFetch", start_time))
        fetch_output = subprocess.check_output(
            ["git", "fetch", "--all"], 
            stderr=subprocess.STDOUT, 
            text=True
        )
        await asyncio.sleep(0.8)
        
        await status_msg.edit(content="📡 **[SYSTEM UPDATE]** กำลังสั่ง Git Reset Hard...\n" + make_gradle_bar(50, "EXECUTING :gitReset", start_time))
        reset_output = subprocess.check_output(
            ["git", "reset", "--hard", "origin/main"], 
            stderr=subprocess.STDOUT, 
            text=True
        )
        print(f"🤠 [Git Force Sync Success]:\n{fetch_output}\n{reset_output}")
        await asyncio.sleep(0.8)
        
        await status_msg.edit(content="✅ **[GIT FORCE SYNC SUCCESS]** ซิงค์โค้ดจักรวาลใหม่ตรงปกแล้วครับ!\n" + make_gradle_bar(75, "EXECUTING :prepareRestart", start_time))
        await asyncio.sleep(1.5)
        
    except subprocess.CalledProcessError as e:
        error_git = f"❌ **[GIT SYNC FAILED]** สั่งซิงค์โค้ดล้มเหลวเนื่องจาก:\n```\n{e.output}\n```"
        print(error_git)
        await status_msg.edit(content=error_git)
        return
        
    except Exception as e:
        error_system = f"❌ **[SYSTEM ERROR]** มีข้อผิดพลาดในระบบเน็ตเวิร์กหรือโปรแกรม Git: {e}"
        print(error_system)
        await status_msg.edit(content=error_system)
        return

    await status_msg.edit(content="🔄 โค้ดเวอร์ชันคลีนพร้อมใช้งานแล้ว! กำลังสั่งรีสตาร์ทตัวเอง...\n" + make_gradle_bar(90, "EXECUTING :restart", start_time))
    await asyncio.sleep(1.5)

    try:
        print("🛸 [Update Bot] อัปเดตโค้ดสำเร็จ กำลังปิดตัวเองเพื่อให้ตัวคุม (bagley_tray.py) เริ่มบอทใหม่ให้อัตโนมัติ...")

        await status_msg.edit(content="✅ **[BUILD SUCCESSFUL]** อัปเดตโครงสร้างเสร็จสิ้น กำลังรีสตาร์ทบอทครับ!\n" + make_gradle_bar(100, "SUCCESSFUL", start_time))

        try:
            global conn
            if conn: conn.close()
        except: pass

        # 🔧 [แก้บั๊ก] เดิม await bot.close() เฉยๆไม่มีการจำกัดเวลา ถ้ามันค้าง
        # (เช่น task เบื้องหลังบางตัวไม่ยอมจบ) โค้ดจะไม่มีทางไปถึง os._exit(87)
        # เลย -> Discord เห็นบอทออฟไลน์ (gateway ถูกปิดไปแล้ว) แต่ตัวโปรเซสจริงๆ
        # ยังไม่ตาย ทำให้ bagley_tray.py ไม่เห็นว่ามันปิดไปแล้ว เลยไม่สั่งเริ่มใหม่
        # ให้ ต้องไปเปิดเองจากไอคอน ตอนนี้จำกัดเวลาไว้ 5 วิ ไม่ว่า bot.close()
        # จะสำเร็จ ค้าง หรือ error ก็ตาม การันตีว่าจะไปถึง os._exit(87) เสมอ
        try:
            await asyncio.wait_for(bot.close(), timeout=5.0)
        except Exception as close_err:
            print(f"⚠️ [Update Bot] bot.close() ไม่สำเร็จ/ค้างเกิน 5 วิ ({close_err}) "
                  f"แต่จะบังคับปิดตัวเองต่อไปอยู่ดี")

        # 🔧 [แก้ไข] เดิมใช้ start_hidden.bat + DETACHED_PROCESS สั่งรีสตาร์ทเอง
        # แต่วิธีนั้นจะสร้างโปรเซสใหม่ที่ bagley_tray.py (ตัวคุมไอคอนถาด) ไม่รู้จัก
        # ทำให้ไอคอนถาดหลุดการติดตามสถานะบอทไปทุกครั้งที่ /update_bot ทำงาน
        # ตอนนี้เปลี่ยนมาแค่ "ปิดตัวเอง" ด้วย exit code พิเศษ (87) แทน แล้วให้
        # bagley_tray.py เป็นคนตรวจจับรหัสนี้แล้วสั่งเริ่มบอทใหม่ให้เองอัตโนมัติ
        # (ถ้ารันบอทตรงๆไม่ผ่าน bagley_tray.py จะแค่ปิดไปเฉยๆ ต้องเปิดขึ้นมาใหม่เอง)
        print("🛸 [Update Bot] กำลังปิดตัวเองด้วย exit code 87 ทันที...")
        sys.stdout.flush()
        os._exit(87)  # 87 = รหัสลับ "ปิดเพื่ออัปเดต ให้เริ่มใหม่ได้เลย" ไม่ใช่ crash

    except Exception as e:
        error_bat = f"❌ **[RESTART ERROR]** เกิดข้อผิดพลาดตอนสั่งรีสตาร์ทบอท: {e}"
        print(error_bat)
        await status_msg.edit(content=error_bat)


@bot.hybrid_command(name="profile_scan", description="สแกนและวิเคราะห์พฤติกรรมเป้าหมาย พร้อมรายงานด้วยเสียง")
async def profile_scan(ctx, member: discord.Member):
    await ctx.defer()

    try:
        user_data = load_user_data()
        member_info = user_data.get(str(member.id), {})
        custom_nickname = member_info.get("nickname", "ยังไม่ระบุ")
        birthday = member_info.get("birthday", "ยังไม่ระบุ")
    except Exception as e:
        print(f"📁 Error loading user data in scan: {e}")
        custom_nickname = "ยังไม่ระบุ"
        birthday = "ยังไม่ระบุ"

    # --- 1. ข้อมูลพื้นฐาน (Hacker Vision Version) ---
    created_at = member.created_at.strftime("%d %b %Y")
    joined_at = member.joined_at.strftime("%d %b %Y")
    
    account_age_days = (discord.utils.utcnow() - member.created_at).days
    days_since_joined = (discord.utils.utcnow() - member.joined_at).days
    
    top_role = member.top_role.name if member.top_role else "พลเมืองทั่วไป"
    
    # --- 2. วิเคราะห์กิจกรรมและเตรียมบทพูด (AI Analysis) ---
    activities = []
    current_game = "ไม่พบกิจกรรม"
    
    if member.activities:
        for act in member.activities:
            if isinstance(act, discord.Game):
                current_game = act.name
                activities.append(f"🎮 กำลังเล่น: {act.name}")
            elif isinstance(act, discord.Spotify):
                activities.append(f"🎵 ฟังเพลง: {act.title}")
            elif isinstance(act, discord.CustomActivity):
                activities.append(f"💬 สถานะ: {act.name}")

    scanner_id = ctx.author.id
    target_id = member.id
    relationship_context = f"- เป้าหมายคือ คุณ {get_realtime_name(member.id, member.display_name)} ซึ่งเป็นสมาชิกในเซิร์ฟเวอร์ สามารถใช้มุกตลกหน้าตายแซะขี้เล่นได้ตามความเหมาะสม\n"

    prompt = f"""
{persona.BRIEF}
งานนี้:
จงใช้ข้อมูลที่มีอยู่ในดิสคอร์ดเหล่านี้มาวิเคราะห์พฤติกรรมเป้าหมาย:
- ชื่อบัญชี: {member.display_name}
- ชื่อเล่นในคลังสมอง: {custom_nickname}
- วันเกิดในคลังสมอง: {birthday}
- ยศสูงสุด (Top Role): {top_role}
- อายุบัญชีดิสคอร์ด: {account_age_days} วัน
- ระยะเวลาที่อยู่ในเซิร์ฟนี้: {days_since_joined} วัน
- กิจกรรมที่กำลังทำ: {current_game}
- สิ่งที่กำลังทำอื่น ๆ: {', '.join(activities) if activities else 'ใช้ชีวิตลึกลับ ไร้ร่องรอยดิจิทัลค้างคา'}

เงื่อนไขและบริบทพิเศษที่คุณต้องรู้:
{relationship_context}

กฎเหล็กด้านบุคลิกภาพ (สำคัญมาก):
1. ห้ามมโนว่าแฮ็กหรือสืบข้อมูลจริง (แซวสไตล์ DedSec ได้ แต่ห้ามอ้างว่าเจาะระบบจริง) ห้ามพูดจาเพ้อเจ้อ อวดอ้างเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นวิเคราะห์นิสัยใจคอและพฤติกรรมตามข้อมูลดิบจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนคนสนิทนินทากัน (หากมีชื่อเล่นหรือวันเกิดระบุมา สามารถหยิบมาแซวร่วมด้วยได้เลย)
2. หากอายุบัญชี (Account Age) น้อยกว่า 30 วัน ให้เหน็บแนมแบบขำ ๆ ว่าเป็นบุคคลต้องสงสัยหรือไอดีผีเพิ่งเกิด
3. แทนตัวเองว่า 'ผม' และเรียกชื่อเล่นของผู้ใช้ ลงท้ายด้วย 'ครับ' แบบเป็นธรรมชาติ ไม่ต้องใส่ทุกประโยค
4. ส่วน Voice: เขียนคำอ่านภาษาไทยให้สละสลวย กระชับ 2-3 ประโยค เพื่อให้ระบบพูดออกเสียง (TTS) ได้ราบรื่น ไม่ติดขัด

โปรดตอบกลับแยกเป็น 2 ส่วนตามรูปแบบโครงสร้างนี้อย่างเคร่งครัด (ห้ามเปลี่ยนคำหัวข้อ):
Embed: [บทวิเคราะห์พฤติกรรมขี้เล่นกวนๆ น่ารักๆ สั้นๆ สำหรับแสดงในแชท]
Voice: [คำพูดรายงานสรุปให้คุณฟังผ่านระบบเสียง]
"""

    try:
        response = await client.aio.models.generate_content(
            model="chat", 
            contents=prompt
        )
        ai_text = (response.text or "").strip()
        
        analysis_report = ai_text.split("Embed:")[1].split("Voice:")[0].strip()
        voice_report = ai_text.split("Voice:")[1].strip()
        
    except Exception as e:
        print(f"AI Error: {e}")
        analysis_report = "ระบบป้องกันของเป้าหมายสูงเกินไป สแกนได้ไม่สมบูรณ์ครับ"
        voice_report = f"สแกนข้อมูลของคุณ {get_realtime_name(member.id, member.display_name)} เรียบร้อยครับ"

    # --- 3. ส่ง Embed (หน้าจอรายงานผลที่มีชื่อเล่นและวันเกิด) ---
    embed = discord.Embed(title=f"📁 [PROFILER V.3] TARGET ANALYSIS: {member.display_name}", color=0x00ff00)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    user_data_value = f"• Name: {member.name}\n• Nickname: {custom_nickname}\n• Birthday: {birthday}\n• ID: {member.id}"
    embed.add_field(name="🆔 USER DATA", value=user_data_value, inline=False)
    
    embed.add_field(name="🧠 BEHAVIORAL ANALYSIS", value=f"```fix\n{analysis_report}\n```", inline=False)
    
    if activities:
        embed.add_field(name="🕵️ LIVE STATUS", value="\n".join(activities), inline=False)
    
    await ctx.send(embed=embed)

    # --- 4. ระบบรายงานด้วยเสียง (TTS) ---
    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" และ "ต้องอยู่ห้องเดียวกับคนสั่ง" ออก
    # bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว และแบ็คลี่ควรพูดทุกครั้งที่ตอบกลับไม่ว่าใครจะอยู่ห้องไหน
    if ctx.voice_client and ctx.voice_client.channel:
        full_report = f"{voice_report} {analysis_report}"
        try:
            import re
            clean_voice_text = re.sub(r'[^\w\s\u0e00-\u0e7f]+', '', full_report)
            await bagley_speak(ctx.guild, clean_voice_text)
        except Exception as tts_err:
            print(f"🚨 Scan Command TTS Error: {tts_err}")


@bot.hybrid_command(name="set_alert", description="ตั้งค่าห้องรายงาน และให้แบ็คลี่รายงานตัว")
@commands.has_permissions(administrator=True)
async def set_alert(ctx, channel: discord.TextChannel):
    settings = load_settings()
    settings[str(ctx.guild.id)] = channel.id
    save_settings(settings)
    
    msg = f"ระบบเซ็นเซอร์พร้อมทำงานที่ห้อง {channel.name} เรียบร้อยครับ"
    await ctx.send(f"📡 **[SYSTEM]** {msg}")
    
    if ctx.voice_client:
        await bagley_speak(ctx.guild, msg)


@bot.hybrid_command(name="view_logs", description="[Developer Only] ดู Log การทำงานล่าสุด 10 บรรทัดของบอท Bagley")
@is_developer() # 🔒 บล็อกล็อกสิทธิ์เฉพาะรายชื่อผู้พัฒนาเท่านั้น
async def view_logs(ctx: commands.Context):
    await ctx.defer(ephemeral=True)

    if not LOG_BUFFER:
        await ctx.send("📋 ตอนนี้คลัง Log ยังว่างเปล่า ไม่มีประวัติผิดปกติครับ!", ephemeral=True)
        return

    log_text = "\n".join(LOG_BUFFER)
    
    embed = discord.Embed(
        title="🤖 Bagley System Live Logs",
        description=f"```text\n{log_text}\n```",
        color=0x00ffcc
    )
    embed.set_footer(text="แสดงเฉพาะข้อมูลล่าสุด 10 บรรทัดใน RAM")
    
    await ctx.send(embed=embed, ephemeral=True)


@view_logs.error
async def view_logs_error(ctx: commands.Context, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🛑 ขออภัยด้วยครับ! คำสั่งนี้จำกัดสิทธิ์เฉพาะผู้พัฒนาบอทที่ระบุไว้เท่านั้นน้าครับ!", ephemeral=True)


@bot.hybrid_command(name="sys_cleanup", description="สั่งให้แบ็คลี่เคลียร์แคชและคืนพื้นที่ RAM ของระบบทันที")
async def sys_cleanup(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer()
    
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        msg_denied = "❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name))
        if ctx.interaction:
            await ctx.interaction.followup.send(msg_denied)
        else:
            await ctx.send(msg_denied)
        return
        
    before, after, saved = perform_cleanup(ctx.bot)
    
    if saved > 0:
        msg = (
            f"🧹 **[SYSTEM CLEANUP]** แบ็คลี่เคลียร์ RAM โล่งแล้วครับ!\n"
            f"📊 **RAM ก่อนเคลียร์:** `{before:.2f} MB`\n"
            f"📉 **RAM หลังเคลียร์:** `{after:.2f} MB`\n"
            f"♻️ **คืนพื้นที่ความจำได้:** `{saved:.2f} MB` ครับ!"
        )
    else:
        msg = (
            f"🧹 **[SYSTEM CLEANUP]** สมองของแบ็คลี่สะอาดกริ๊บอยู่แล้วครับ!\n"
            f"📊 **RAM ปัจจุบัน:** `{after:.2f} MB` ไม่จำเป็นต้องรีไซเคิลเพิ่มครับ"
        )
        
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)
        
    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
    await bagley_speak(ctx.guild, say("cleanup_done"))
