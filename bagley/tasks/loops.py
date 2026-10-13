"""bagley/tasks/loops.py — งานวนลูปเบื้องหลัง (@tasks.loop): แจ้งเตือน, ตารางนัด, เดินตามเจ้านาย, ประกาศเที่ยงวัน/เที่ยงคืน"""
import asyncio
import discord
import traceback
from datetime import datetime, time as dt_time
from discord.ext import tasks

from bagley.ai import persona
from bagley.core import state
from bagley.core.app import bot, client
from bagley.core.config import ALLOWED_TEACH_USERS, ALLOWED_USERS, bangkok_tz
from bagley.core.logutil import print
from bagley.core.util import perform_cleanup
from bagley.data.storage import get_realtime_name, load_reminders, load_user_data, load_voice_data, save_reminders, save_user_data
from bagley.features.party import check_and_invite_party, check_and_warn_gamers
from bagley.phrases import BIG_ROOM_GREETINGS, BIG_ROOM_MOVE_GREETINGS, REPORT_PERMISSION_PHRASES, pick as _pick_speech, say
from bagley.voice.alerts import _deliver_voice_reminder
from bagley.voice.tts import FFMPEG_PATH, bagley_speak_wait


@tasks.loop(minutes=1)
async def check_reminders():
    now_colon = datetime.now().strftime("%H:%M")
    now_dot = datetime.now().strftime("%H.%M")
    
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    remaining_reminders = []
    updated = False

    for r in reminders:
        r_time = r.get('time')
        r_user_id = r.get('user_id')

        if not r_time or not r_user_id:
            updated = True  
            continue        

        if (r_time == now_colon or r_time == now_dot):
            try:
                user_id = int(r_user_id)
                user = await bot.fetch_user(user_id)
                if user:
                    content = r.get('content', 'แจ้งเตือนความจำครับ!')
                    
                    member = None
                    for guild in bot.guilds:
                        m = guild.get_member(user_id)
                        if m and m.voice and m.voice.channel:
                            member = m
                            break
                    
                    if member:
                        bot.loop.create_task(_deliver_voice_reminder(member.voice.channel.guild, member.voice.channel, content))
                    else:
                        try:
                            try:
                                dm_prompt = f"""
                                {persona.BRIEF}
สถานการณ์: คุณกำลังส่ง DM มาแจ้งเตือนความจำให้คุณ
                                หน้าที่: เจนข้อความ DM แจ้งเตือนสั้นๆ เป็นกันเอง (1-2 ประโยค) โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

                                [เนื้อหาที่ต้องแจ้งเตือน]: {content}

                                กฎ: พูดแบบเป็นกันเอง แทนตัวเองว่า 'แบ็คลี่' ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะข้อความที่จะส่งเท่านั้น
                                """
                                dm_response = await client.aio.models.generate_content(model="chat", contents=dm_prompt)
                                dm_text = (dm_response.text or "").strip()
                                if not dm_text:
                                    raise ValueError("AI ตอบข้อความว่างเปล่า")
                                await user.send(dm_text)
                            except Exception as ai_err:
                                print(f"❌ AI เจนข้อความ DM แจ้งเตือนพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
                                await user.send("🔔 " + say("reminder_dm", content=f"**{content}**"))
                        except Exception as e:
                            print(f"DEBUG: ส่ง DM ไม่ได้เพราะ {e}")
                            
                    updated = True
                
            except Exception as e:
                print(f"Error processing reminder: {e}")
                remaining_reminders.append(r)
        else:
            remaining_reminders.append(r)

    if updated:
        data["reminders"] = remaining_reminders
        save_user_data(data)


@tasks.loop(minutes=1)
async def check_friend_reminders():
    reminders = load_reminders()
    if not reminders:
        return

    now = datetime.now().strftime("%H:%M")
    updated_reminders = []
    has_changed = False
    
    for rem in reminders:
        # ถ้าถึงเวลาเตือนของเพื่อน
        if rem['time'] == now:
            try:
                target_id = int(rem['target_id'])
                user = await bot.fetch_user(target_id)
                content = rem['text']
                
                if user:
                    member = None
                    for guild in bot.guilds:
                        m = guild.get_member(target_id)
                        if m and m.voice and m.voice.channel:
                            member = m
                            break
                    
                    if member:
                        # สั่งให้ Bagley วาร์ปบุกห้องเสียงเพื่อน (หรือพูดตรงๆ ถ้าอยู่ห้องเดียวกันอยู่แล้ว)
                        bot.loop.create_task(_deliver_voice_reminder(member.voice.channel.guild, member.voice.channel, content))
                    else:
                        # ส่ง DM ปกติถ้าเพื่อนไม่ได้เข้าห้องเสียงไหนเลย
                        try:
                            friend_dm_prompt = f"""
                            {persona.BRIEF}
สถานการณ์: คุณกำลังส่ง DM มาแจ้งเตือนความจำให้คุณ (แจ้งเตือนที่เพื่อนฝากไว้ให้)
                            หน้าที่: เจนข้อความ DM แจ้งเตือนสั้นๆ เป็นกันเอง (1-2 ประโยค) โดยอ้างอิงเนื้อหาแจ้งเตือนและเวลาด้านล่าง

                            [เนื้อหาที่ต้องแจ้งเตือน]: {content}
                            [เวลา]: {now}

                            กฎ: พูดแบบเป็นกันเอง แทนตัวเองว่า 'แบ็คลี่' ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะข้อความที่จะส่งเท่านั้น
                            """
                            friend_dm_response = await client.aio.models.generate_content(model="chat", contents=friend_dm_prompt)
                            alert_msg = (friend_dm_response.text or "").strip()
                            if not alert_msg:
                                raise ValueError("AI ตอบข้อความว่างเปล่า")
                        except Exception as ai_err:
                            print(f"❌ AI เจนข้อความ DM แจ้งเตือนเพื่อนพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
                            alert_msg = f"⏰ **สวัสดีครับ ผม Bagley ครับ! มาแจ้งเตือนว่า: {content} ตอนเวลา {now}**"
                        await user.send(alert_msg)
                
                has_changed = True
            except Exception as e:
                print(f"Error sending friend reminder: {e}")
                updated_reminders.append(rem)  # เกิดข้อผิดพลาด ให้เก็บรายการนี้ไว้ก่อน
        else:
            updated_reminders.append(rem)  # ยังไม่ถึงเวลา เก็บรักษาลงลิสต์ปกติ
            
    if has_changed:
        save_reminders(updated_reminders)


async def _notify_schedule_due(sch: dict):
    """แจ้งเตือนเจ้าของตารางนัดที่ถึงเวลาแล้ว: ถ้าเจ้าของอยู่ในห้องเสียงอยู่ ให้บอทวาร์ปเข้าไปเตือน
    (ผ่าน _deliver_voice_reminder/bagley_hijack_alert) แล้ววาร์ปกลับห้องเดิม/ออกจากห้องให้อัตโนมัติ
    ถ้าไม่ได้อยู่ห้องเสียงไหนเลย ก็ส่ง DM แจ้งแทน (เหมือนระบบเตือนตัวเอง/เพื่อนเดิม)"""
    try:
        owner_id = sch.get("owner_id")
        if not owner_id:
            return
        owner_id = int(owner_id)

        event_text = sch.get("event", "ไม่ระบุกิจกรรม")
        time_text = sch.get("time", "")
        content = f"ถึงเวลานัด {event_text}" + (f" ตอน {time_text}" if time_text and time_text != "ไม่ระบุเวลา" else "") + " แล้วครับ"

        member = None
        for guild in bot.guilds:
            m = guild.get_member(owner_id)
            if m and m.voice and m.voice.channel:
                member = m
                break

        if member:
            await _deliver_voice_reminder(member.voice.channel.guild, member.voice.channel, content)
            return

        # ไม่ได้อยู่ห้องเสียงไหนเลยตอนนี้ -> ส่ง DM แจ้งแทน
        try:
            user = await bot.fetch_user(owner_id)
            if not user:
                return
            try:
                dm_prompt = f"""
                {persona.BRIEF}
สถานการณ์: คุณกำลังส่ง DM มาแจ้งเตือนตารางนัดหมายให้คุณ
                หน้าที่: เจนข้อความ DM แจ้งเตือนสั้นๆ เป็นกันเอง (1-2 ประโยค) โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

                [เนื้อหาที่ต้องแจ้งเตือน]: {content}

                กฎ: พูดแบบเป็นกันเอง แทนตัวเองว่า 'แบ็คลี่' ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะข้อความที่จะส่งเท่านั้น
                """
                dm_response = await client.aio.models.generate_content(model="chat", contents=dm_prompt)
                dm_text = (dm_response.text or "").strip()
                if not dm_text:
                    raise ValueError("AI ตอบข้อความว่างเปล่า")
                await user.send(dm_text)
            except Exception as ai_err:
                print(f"❌ AI เจนข้อความ DM แจ้งเตือนตารางนัดพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
                await user.send("🔔 " + say("reminder_dm", content=f"**{content}**"))
        except Exception as e:
            print(f"DEBUG: ส่ง DM แจ้งเตือนตารางนัดไม่ได้เพราะ {e}")
    except Exception as e:
        print(f"❌ ERROR _notify_schedule_due: {e}")
        print(traceback.format_exc())


@tasks.loop(minutes=1)
async def check_expired_schedules():
    """เช็คตารางนัดหมาย (schedules ที่ฝากไว้ผ่าน /remind หรือพิมพ์ธรรมชาติ) ที่ถึงวัน-เวลาที่กำหนดแล้ว
    แจ้งเตือนด้วยเสียงจริง (วาร์ปเข้าห้องเสียงถ้าจำเป็น ผ่าน bagley_hijack_alert) หรือ DM ถ้าไม่ได้อยู่ห้องเสียงไหนเลย
    แล้วค่อยลบออกจากคลังความจำ กันไม่ให้ค้างอยู่ใน /schedule_list ตลอดไป
    🛠️ [แก้บั๊ก]: เดิมฟังก์ชันนี้ลบทิ้งเงียบๆ อย่างเดียว ไม่เคยแจ้งเตือนด้วยเสียงเลยแม้แต่ครั้งเดียว"""
    try:
        now = datetime.now(bangkok_tz)
        data = load_user_data()
        schedules = data.get("schedules", [])
        if not schedules:
            return

        remaining_schedules = []
        removed_any = False
        for sch in schedules:
            try:
                sch_dt = datetime.strptime(f"{sch.get('date', '')} {sch.get('time', '')}", "%Y-%m-%d %H:%M")
                sch_dt = sch_dt.replace(tzinfo=bangkok_tz)
            except Exception:
                # ถ้าพาร์สวันที่/เวลาไม่ได้ (เช่น '3 ทุ่ม') ให้เก็บไว้ก่อน ไม่ลบทิ้งมั่วครับ
                remaining_schedules.append(sch)
                continue

            if sch_dt <= now:
                removed_any = True
                bot.loop.create_task(_notify_schedule_due(sch))
                print(f"🔔 [Schedule Due] แจ้งเตือนตารางงาน '{sch.get('event')}' ของ {sch.get('owner_id')} ที่ถึงเวลา {sch.get('time')} วันที่ {sch.get('date')} แล้ว และลบออกจากระบบเรียบร้อยครับ")
            else:
                remaining_schedules.append(sch)

        if removed_any:
            data["schedules"] = remaining_schedules
            save_user_data(data)
    except Exception as e:
        print(f"❌ ERROR check_expired_schedules: {e}")
        print(traceback.format_exc())


@tasks.loop(hours=6.0)
async def auto_brain_cleanup():
    before, after, saved = perform_cleanup(bot)
    print(f"🤖 [Auto Cleanup]: ล้างสมองสำเร็จ! RAM ลดลง {saved:.2f} MB (จาก {before:.2f} MB เหลือ {after:.2f} MB)")


# --- 🔄 1. ระบบ Loop เช็กทุก 1 นาที ---
@tasks.loop(minutes=1)
async def follow_creator_task():
    today = datetime.today().date()
    active_targets = []

    for guild in bot.guilds:
        guild_id = guild.id
        
        if state.room_guard_status.get(guild_id, False):
            print(f"DEBUG: 🛡️ เซิร์ฟเวอร์ {guild.name} เปิดโหมดสายตรวจอยู่ แบ็คลี่ล็อกขาตัวเองไว้ ข้ามระบบตามเจ้านายชั่วคราวครับ")
            continue

        # 🎯 ถ้ามีคนถูกตั้งให้ตามติดผ่านคำสั่ง /follow ในเซิร์ฟนี้ ให้ตามคนนั้นแทนระบบตามผู้พัฒนาปกติ
        followed_uid = state.command_follow_targets.get(guild_id)
        if followed_uid:
            followed_member = guild.get_member(followed_uid)
            if followed_member and followed_member.voice and followed_member.voice.channel:
                active_targets.append((followed_member, followed_member.voice.channel, guild))
            continue

        for user_id in ALLOWED_USERS:
            if not state.auto_follow_status.get(user_id, True):
                continue
                
            member = guild.get_member(user_id)
            if member and member.voice and member.voice.channel:
                active_targets.append((member, member.voice.channel, guild))

    if not active_targets:
        return

    target_member = None
    target_channel = None
    guild_to_join = None
    both_present = False

    if len(active_targets) == 1:
        target_member, target_channel, guild_to_join = active_targets[0]
    else:
        if active_targets[0][2].id == active_targets[1][2].id and active_targets[0][1].id != active_targets[1][1].id:
            guild_obj = active_targets[0][2]
            voice_client = guild_obj.voice_client
            split_channel_ids = {active_targets[0][1].id, active_targets[1][1].id}

            # 🛡️ [แก้บั๊ก] "ไม่ลำเอียง" ควรแปลว่า "ไม่เลือกเข้าห้องใหม่ให้ใครฝ่ายใดฝ่ายหนึ่ง"
            # ไม่ใช่ "ต้องออกจากห้องที่อยู่อยู่แล้ว" - ถ้าแบ็คลี่อยู่กับคุณชะอมหรือคุณชาช่าคนใดคนหนึ่งอยู่ก่อน
            # ตั้งแต่ก่อนที่อีกคนจะแยกไปอีกห้อง แปลว่าแบ็คลี่ไม่ได้เพิ่งเลือกข้างตอนนี้ อยู่ต่อได้เลยครับ
            if voice_client and voice_client.is_connected() and voice_client.channel.id in split_channel_ids:
                print(f"DEBUG: [⚖️ โหมดไม่ลำเอียง] คุณชะอมและคุณชาช่าแยกห้องกัน แต่แบ็คลี่อยู่กับคนใดคนหนึ่งอยู่ก่อนแล้ว ไม่ใช่การเลือกข้างใหม่ เลยขออยู่ต่อครับ ไม่ออกจากห้องนะครับ")
                return

            print(f"DEBUG: [⚖️ โหมดไม่ลำเอียง] พบคุณชะอมและคุณชาช่าอยู่คนละห้องในเซิร์ฟเวอร์เดียวกัน แบ็คลี่จะไม่เลือกข้างใครครับ!")

            if voice_client:
                try:
                    # 🛠️ [แก้บั๊ก] เดิมใช้ disconnect() แบบไม่ force ซึ่งบางครั้งดิสคอร์ดค้าง
                    # ทำให้ guild.voice_client ยังเหลือ client ตัวเก่าที่พังอยู่ในระบบ
                    # ผลคือรอบถัดไปที่ควรจะบินเข้าไปหาอีกคน กลับเชื่อมต่อไม่ติดเงียบๆ
                    # เปลี่ยนเป็น force=True ให้เหมือนกับจุดอื่นๆ ที่รีคอนเน็กต์ปกติ
                    await voice_client.disconnect(force=True)
                    state.voice_report_status.pop(guild_obj.id, None)
                    state.bot_follow_targets[guild_obj.id] = None
                    print(f"DEBUG: ⚖️ ถอนกำลังออกจากห้องเดิมเรียบร้อย เพื่อความเท่าเทียมคัปพ้ม!")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนสั่งบอทถอนกำลังโหมดไม่ลำเอียง: {e}")
                    print(traceback.format_exc())
            return

        if active_targets[0][1] == active_targets[1][1]:
            target_member, target_channel, guild_to_join = active_targets[0]
            both_present = True
        else:
            un_greeted_targets = [t for t in active_targets if state.last_greeting_dates.get(t[0].id) != today]
            if len(un_greeted_targets) == 1:
                target_member, target_channel, guild_to_join = un_greeted_targets[0]
            else:
                chaom_target = next((t for t in active_targets if t[0].id == 1133740216822267954), active_targets[0])
                target_member, target_channel, guild_to_join = chaom_target

    if target_channel and guild_to_join and target_member:
        voice_client = guild_to_join.voice_client

        # เช็กสลับห้อง
        if voice_client and voice_client.is_connected():
            if voice_client.channel == target_channel:
                # 🛠️ [แก้บั๊ก] เดิมโค้ด return ตรงนี้ทันที ทำให้ระบบเตือนเล่นเกมนาน
                # กับระบบชวนตี้คนนอกห้อง ไม่ถูกเรียกอีกเลยตราบใดที่บอทยังอยู่ห้องเดิม
                # (มันจะรันแค่ตอนบอทเพิ่งเข้าห้อง/ย้ายห้องครั้งแรกเท่านั้น)
                # เปลี่ยนให้ยังเช็คสองระบบนี้ทุกครั้งที่ลูปนาทีวิ่งมา ก่อนจะ return
                await check_and_warn_gamers(guild_to_join)
                await check_and_invite_party(guild_to_join)
                return
            else:
                print(f"🔄 [Auto Follow] เจ้านายย้ายห้องแล้ว! กำลังพาน้องแบ็คลี่บินจากห้อง {voice_client.channel.name} ไปห้อง {target_channel.name}")
        
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(target_channel)
                vc = voice_client
            else:
                if voice_client:
                    await voice_client.disconnect(force=True)
                    await asyncio.sleep(0.5)
                vc = await target_channel.connect()
                
            if both_present:
                state.bot_follow_targets[guild_to_join.id] = "both"
            else:
                state.bot_follow_targets[guild_to_join.id] = target_member.id
                
            print(f"🛸 [Auto Follow Success] บินตามมาถึงห้อง {target_channel.name} เรียบร้อยคัปพ้ม!")
        except Exception as e:
            print(f"❌ [Bagley] เกิดข้อผิดพลาดขณะเข้าห้องเสียง: {e}")
            print(traceback.format_exc())
            return

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
            await asyncio.sleep(0.5) # 🌟 เคลียร์ช่องสัญญาณเสียงหลังโดรนดังเสร็จสิ้น
        except Exception as e:
            print(f"❌ [Bagley] เกิดข้อผิดพลาดขณะเล่นเสียง Drone เปิดตัว: {e}")

        # ==========================================
        #  ส่วนประมวลผลลอจิกการส่งเสียงพูด
        # ==========================================
        greeting_key = "both_together" if both_present else target_member.id
        guild_id = guild_to_join.id
        
        all_humans_in_room = [m for m in target_channel.members if not m.bot]
        human_count = len(all_humans_in_room)
        human_ids = [m.id for m in all_humans_in_room]
        
        should_speak = False
        msg = ""

        user_memory = load_user_data()
        
        today_str = datetime.now(bangkok_tz).strftime("%Y-%m-%d")
        today_schedules = []
        try:
            all_schedules = user_memory.get("schedules", [])
            for sch in all_schedules:
                if sch.get("date") == today_str and sch.get("owner_id") in human_ids:
                    today_schedules.append(sch)
        except Exception as e:
            print(f"DEBUG: 📅 ดึงตารางงานใน Loop พลาด: {e}")

        pending_reminders = []
        for sch in today_schedules:
            remind_key = f"{sch.get('owner_id')}_{sch.get('event')}_{today_str}"
            if state.last_reminder_dates.get(remind_key) != today:
                pending_reminders.append(sch)

        reminder_context = ""
        reminder_fallback_text = ""
        if pending_reminders:
            reminder_context = "ตารางแจ้งเตือนด่วนของคนในห้องนี้วันนี้:\n"
            reminder_fallback_text = " อ้อ! แล้วก็วันนี้มีแจ้งเตือนตารางงานด้วยครับ"
            for r in pending_reminders:
                owner_member = guild_to_join.get_member(r.get('owner_id'))
                owner_name = get_realtime_name(r.get('owner_id'), owner_member.display_name if owner_member else "เพื่อน")
                reminder_context += f"- ของคุณ {owner_name}: งาน '{r.get('event')}' เวลา {r.get('time')}\n"
                reminder_fallback_text += f" มีงานของคุณ {owner_name} กิจกรรม {r.get('event')} เวลา {r.get('time')}"

        def generate_report_speech(guild):
            """
            🔧 [ปรับปรุง] ตัดส่วนรายงานสถิติเวลาสะสมในห้องเสียง (อันดับที่ 1/2/3 ใช้เวลาไปกี่ชั่วโมง)
            ออกไปแล้ว เพราะพูดยาวเกินไปและฟังดูเป็นทางการเกินความจำเป็น เหลือไว้แค่ 2 อย่างที่ยังมีประโยชน์
            และพูดสั้นกว่าเดิมมาก:
              1) บอกว่าวันนี้มีใครแวะเข้าห้องเสียงของเซิร์ฟเวอร์นี้บ้าง (เหมือนเดิม)
              2) บอกว่ามีสมาชิกใหม่เข้าเซิร์ฟเวอร์วันนี้หรือไม่ (เหมือนเดิม)
            """
            report_msg = ""
            try:
                data = load_voice_data()
                today_str = datetime.now().strftime("%Y-%m-%d")
                guild_id_str = str(guild.id)

                guild_stats = {}
                if data and data.get("date") == today_str and data.get("stats"):
                    guild_stats = data["stats"].get(guild_id_str, {})

                filtered_stats = [item for item in guild_stats.items() if int(item[0]) != bot.user.id]

                if filtered_stats:
                    # 🔧 [ปรับตามคำขอผู้พัฒนา] เดิมไล่รายชื่อทุกคนที่แวะเข้าห้องเสียงมาพูดทั้งหมด
                    # ตอนนี้ตัดชื่อออก เหลือรายงานแค่ "จำนวนคน" ที่แวะเข้าห้องเสียงเซิร์ฟเวอร์นี้พอ
                    entrant_count = len(filtered_stats)
                    if entrant_count == 1:
                        report_msg += " วันนี้มีคนแวะเข้าห้องเสียงเซิร์ฟเวอร์นี้แล้ว 1 คนครับ"
                    else:
                        report_msg += f" วันนี้มีคนแวะเข้าห้องเสียงเซิร์ฟเวอร์นี้แล้วทั้งหมด {entrant_count} คนครับ"

                    new_server_users = []
                    for u_id, info in filtered_stats:
                        member = guild.get_member(int(u_id))
                        if member and member.joined_at:
                            join_date_str = member.joined_at.astimezone().strftime("%Y-%m-%d")
                            if join_date_str == today_str:
                                new_server_users.append(member)

                    if not new_server_users:
                        report_msg += " ส่วนการตรวจสอบผู้ใช้ใหม่ ไม่พบคนเข้ามาใหม่ในวันนี้ครับ"
                    else:
                        new_user_names = []
                        for member in new_server_users:
                            name_to_call = get_realtime_name(member.id, member.display_name)
                            new_user_names.append(f"คุณ {name_to_call}")
                        names_str = " และ ".join(new_user_names)
                        report_msg += f" ส่วนการตรวจสอบผู้ใช้ใหม่ วันนี้พบสมาชิกใหม่ {names_str} ที่เพิ่งเข้าร่วมเซิร์ฟเวอร์ในวันนี้ เข้ามาร่วมแจมในห้องเสียงด้วยนะครับ"
                else:
                    report_msg += " และดูเหมือนว่าในเซิร์ฟเวอร์นี้ พวกคุณจะเป็นกลุ่มแรกที่เปิดประเดิมห้องเสียงของวันนี้เลยครับ ส่วนการตรวจสอบผู้ใช้ใหม่ ก็ไม่พบคนเข้ามาใหม่ครับ"
            except Exception as err:
                print(f"❌ เกิดข้อผิดพลาดขณะดึงรายงาน: {err}")
                report_msg += " ไม่สามารถดึงรายงานได้ในขณะนี้ครับ"
            return report_msg

        # 🕐 [ทักทายตามช่วงเวลา] ครอบคลุมเช้า-บ่าย-เย็น-กลางคืน
        now_hour = datetime.now(bangkok_tz).hour
        time_greeting = "อรุณสวัสดิ์ครับ" if 0 <= now_hour < 13 else "สวัสดีตอนบ่ายครับ" if 13 <= now_hour < 14 else "สวัสดีตอนเย็นครับ" if 14 <= now_hour < 19 else "สวัสดีตอนกลางคืนครับ"

        # 👥 [กติกาจำนวนคนในห้อง] ถ้าคนในห้องมากกว่า 4 คน -> ทักรวบทีเดียวว่า "สวัสดีทุกคน" สั้นๆ
        # (ไม่เอ่ยชื่อทีละคน เพราะห้องใหญ่จะพูดยาวเกินไป) ถ้ามี 4 คนหรือน้อยกว่า -> ทักทายทีละชื่อแบบเดิม
        is_big_room = human_count > 4
        print(f"DEBUG: 🔍 [Follow Greeting Check] human_count={human_count}, is_big_room={is_big_room}, greeting_key={greeting_key} ")

        chaom_name = get_realtime_name(1133740216822267954, "คุณชะอม")
        other_id = next((uid for uid in ALLOWED_USERS if uid != 1133740216822267954), None)
        chacha_name = get_realtime_name(other_id, "คุณชาช่า") if other_id else "คุณชาช่า"

        # 🟢 [กรณีที่ 1: ทักทายก้อนแรกแรกของวัน]
        if state.last_greeting_dates.get(greeting_key) != today:
            if is_big_room:
                # ห้องคนเยอะ (>4 คน) -> ทักรวบสั้นๆ ว่าสวัสดีทุกคน ไม่เอ่ยชื่อทีละคน
                # และห้ามรายงานว่าใครเข้าเซิฟมาบ้าง/เข้าเซิฟมาใหม่ (เก็บไว้รายงานทีหลังตอนคนน้อยลง)
                msg = _pick_speech(BIG_ROOM_GREETINGS, time_greeting=time_greeting) + reminder_fallback_text
                should_speak = True
                for m in all_humans_in_room:
                    state.last_greeting_dates[m.id] = today
            else:
                try:
                    friends = [m for m in all_humans_in_room if m.id != target_member.id and (not both_present or m.id != other_id)]
                    friend_names_list = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in friends]
                    friends_context = " และมีเพื่อนในห้องคือ " + " กับ ".join(friend_names_list) if friend_names_list else ""
                    caller_context = f"คุณ {chaom_name} และคุณ {chacha_name}" if both_present else f"คุณ {get_realtime_name(target_member.id, target_member.display_name)}"

                    prompt = f"""
                    {persona.BRIEF}
สถานการณ์: คุณยินดีต้อนรับเจ้านายเข้าห้องเสียงครั้งแรกของวันนี้!
                    หน้าที่: สร้างประโยคทักทายเปิดตัวสั้นๆ กวนๆ น่ารัก (1-2 ประโยค) และสรุปแจ้งเตือนตารางงาน (ถ้ามี)
                    
                    [ข้อมูลบริบท]:
                    - เจ้านายหลักที่เจอวันนี้: {caller_context}{friends_context}
                    - ช่วงเวลา: {time_greeting}
                    - ข้อมูลแจ้งเตือนตารางงานของคนในห้อง: {reminder_context if reminder_context else 'ไม่มี'}
                    
                    กฎ: แทนตัวเองว่า 'แบ็คลี่' ทักทายชื่อคนให้ครบตามข้อมูลด้านบน และถ้ามีตารางงานให้พูดต่อท้ายให้ชัดเจน ห้ามพิมพ์หัวข้อหรือวงเล็บเด็ดขาด เอาเฉพาะบทพูดเท่านั้น!
                    """
                    
                    response = await client.aio.models.generate_content(model="chat", contents=prompt)
                    ai_greet = (response.text or "").strip()
                    msg = ai_greet + generate_report_speech(guild_to_join)
                    should_speak = True
                    
                    for m in all_humans_in_room:
                        state.last_greeting_dates[m.id] = today
                        
                except Exception as ai_err:
                    print(f"❌ AI ใน Loop ขัดข้อง ย้อนกลับไปใช้คำพูดดั้งเดิม: {ai_err}")
                    creator_greet = f"{time_greeting} {chaom_name}และ{chacha_name}! แบ็คลี่ตามมาแล้วครับ" if both_present else f"{time_greeting} เพิ่งมาหรอคุณ {get_realtime_name(target_member.id, target_member.display_name)} ยินดีต้อนรับนะ"
                    friends = [m for m in all_humans_in_room if m.id != target_member.id and (not both_present or m.id != other_id)]
                    friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in friends]
                    other_friends_greet = f" สวัสดี {" และ ".join(friend_names)} ด้วยนะครับ" if friend_names else ""
                    
                    msg = creator_greet + other_friends_greet + reminder_fallback_text + generate_report_speech(guild_to_join)
                    should_speak = True

                # 📋 ห้องไม่เยอะ (≤4 คน) รอบนี้พูดรายงานจริงแล้ว (แนบไปกับ generate_report_speech ด้านบน)
                state.reported_content_today[guild_id] = today

            state.last_greeting_dates[greeting_key] = today
            if both_present:
                for uid in ALLOWED_USERS: state.last_greeting_dates[uid] = today
            state.reported_guilds_today[guild_id] = today

        # 🔵 [กรณีที่ 2: บอทย้ายเซิร์ฟเวอร์ในวันเดียวกัน]
        elif state.reported_guilds_today.get(guild_id) != today:
            un_greeted_people = [m for m in all_humans_in_room if state.last_greeting_dates.get(m.id) != today]

            if is_big_room:
                # ห้องคนเยอะ (>4 คน) -> ทักรวบสั้นๆ เหมือนกัน ไม่เอ่ยชื่อทีละคน และไม่รายงานเช่นกัน
                msg = _pick_speech(BIG_ROOM_MOVE_GREETINGS, time_greeting=time_greeting) + reminder_fallback_text
                should_speak = True
                for f in un_greeted_people:
                    state.last_greeting_dates[f.id] = today
            else:
                try:
                    new_friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in un_greeted_people]
                    names_str = " กับ ".join(new_friend_names) if new_friend_names else "ทุกคนในห้องใหม่"
                    
                    prompt = f"""
                    {persona.BRIEF}
สถานการณ์: วันนี้คุณเพิ่งย้ายเซิร์ฟเวอร์บินตามเจ้านายมาเจอเพื่อนๆ กลุ่มใหม่ในห้องเสียงนี้
                    หน้าที่: เจนคำพูดทักทายคนกลุ่มใหม่นี้แบบสั้นๆ กวนๆ น่ารักๆ เป็นกันเอง (1 ประโยค) 
                    - รายชื่อคนใหม่ที่เจอในห้องนี้: {names_str}
                    - ข้อมูลแจ้งเตือนตารางงานของคนในห้องนี้: {reminder_context if reminder_context else 'ไม่มี'}
                    
                    กฎ: ตอบสั้นมาก ห้ามพิมพ์หัวข้อ พ่วงเตือนตารางงานถ้ามี
                    """
                    response = await client.aio.models.generate_content(model="chat", contents=prompt)
                    ai_new_server_greet = (response.text or "").strip()
                    
                    msg = ai_new_server_greet + generate_report_speech(guild_to_join)
                    should_speak = True
                    
                    for f in un_greeted_people:
                        state.last_greeting_dates[f.id] = today
                        
                except Exception as e:
                    print(f"❌ AI ย้ายเซิร์ฟเวอร์พัง: {e}")
                    base_report = "กำลังตรวจสอบเซิฟเวอร์ย้อนหลัง" + generate_report_speech(guild_to_join)
                    new_friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in un_greeted_people]
                    extra_greet = f" อ้อ แล้วก็ สวัสดี {" และ ".join(new_friend_names)} ที่เพิ่งเจอกันในห้องนี้ด้วยนะครับ" if new_friend_names else ""
                    msg = base_report + extra_greet + reminder_fallback_text
                    should_speak = True

            state.reported_guilds_today[guild_id] = today
            
        else:
            # 🙋 [รายงานภายหลัง] ถ้ายังไม่เคยพูดรายงานจริงๆ วันนี้เลย (เช่น รอบแรกเจอห้องคนเยอะ
            # เลยข้ามการรายงานไปตอนทักทาย) แล้วตอนนี้มีผู้พัฒนา (ALLOWED_TEACH_USERS) อยู่ในห้อง
            # และห้องเหลือคนไม่เกิน 4 คนแล้ว -> พูดรายงานให้ โดยไม่ทักทายซ้ำ แค่ขออนุญาตรายงานก่อน
            developers_in_room = [m for m in all_humans_in_room if m.id in ALLOWED_TEACH_USERS]
            if developers_in_room and not is_big_room and state.reported_content_today.get(guild_id) != today:
                report_speech = generate_report_speech(guild_to_join)
                if report_speech.strip():
                    msg = _pick_speech(REPORT_PERMISSION_PHRASES) + report_speech + reminder_fallback_text
                    should_speak = True
                    state.reported_content_today[guild_id] = today
                elif pending_reminders:
                    msg = f"อ้อ แบ็คลี่แวะมาบอกเพิ่มคัปพ้ม! {reminder_fallback_text}"
                    should_speak = True
                else:
                    should_speak = False
            # 💡 ถ้าย้ายห้องธรรมดาภายในเซิร์ฟเวอร์เดิม และมีตารางงานค้าง -> ให้แจ้งเตือนงานนั้นเสมอ
            elif pending_reminders:
                msg = f"อ้อ แบ็คลี่แวะมาบอกเพิ่มคัปพ้ม! {reminder_fallback_text}"
                should_speak = True
            else:
                should_speak = False

        print(f"DEBUG: 🗣️ [Follow Greeting] ก่อนพูด -> should_speak={should_speak}, msg_length={len(msg) if msg else 0}")
        
        # 🌟 บังคับเงื่อนไขการันตีเสียงพูดเมื่อมีข้อความและได้รับการอนุญาตให้ส่งเสียง
        if should_speak and msg:
            try:
                # เคลียร์เสียงที่ค้างอยู่ก่อนเปิดเสียงพูด
                if vc.is_playing():
                    vc.stop()
                await asyncio.sleep(0.2)
                
                await bagley_speak_wait(guild_to_join, msg)
                for r in pending_reminders:
                    remind_key = f"{r.get('owner_id')}_{r.get('event')}_{today_str}"
                    state.last_reminder_dates[remind_key] = today
            except Exception as e:
                print(f"❌ [Bagley] เกิดข้อผิดพลาดตอนส่งเสียงทักทายมนุษย์: {e}")

    if active_targets:
        await check_and_warn_gamers(guild_to_join)
        await check_and_invite_party(guild_to_join)


@tasks.loop(time=[
    dt_time(hour=0, minute=0, tzinfo=bangkok_tz), 
    dt_time(hour=12, minute=0, tzinfo=bangkok_tz)
])
async def daily_announcement_task():
    
    # ดึงเวลาปัจจุบันที่เป็นเวลาประเทศไทย
    now = datetime.now(bangkok_tz)
    
    # 🛡️ ปรับตัวเช็กให้ยืดหยุ่น ป้องกันบั๊กเวลาคลาดเคลื่อนระดับวินาที
    if now.hour not in [0, 12]:
        print(f"DEBUG: ⏰ ข้ามการแจ้งเตือนเนื่องจากระบบทำงานนอกเวลาเป้าหมาย (เวลาปัจจุบัน: {now.strftime('%H:%M')})")
        return

    # 🧠 เรียกใช้สมอง AI (ใช้ client กลางแบบ async ตัวเดียวกับส่วนอื่นในไฟล์)
    ai_ready = True

    for voice_client in bot.voice_clients:
        # 🎥 [โหมดสตรีม] ถ้ากิลด์นี้ปิดระบบแจ้งเตือนเที่ยงวัน/เที่ยงคืนไว้ (ผ่าน /stream_mode หรือสั่งปิด
        # เองโดยตรง) ให้ข้ามกิลด์นี้ไปเลย ไม่ต้องพูดแจ้งเตือน
        if voice_client and voice_client.guild and not state.daily_announcement_status.get(voice_client.guild.id, True):
            continue

        if voice_client and voice_client.channel and voice_client.is_connected():
            
            human_members = [m for m in voice_client.channel.members if not m.bot]
            
            if human_members:
                # 🎮 ระบบสแกนหาเกมที่คนในห้องกำลังเล่นอยู่คัปพ้ม
                playing_games = []
                for member in human_members:
                    if member.activities:
                        for activity in member.activities:
                            if activity.type == discord.ActivityType.playing:
                                playing_games.append(activity.name)
                
                # เอาเฉพาะชื่อเกมที่ไม่ซ้ำกัน
                playing_games = list(set(playing_games))
                game_context = f"ตอนนี้คนในห้องกำลังเล่นเกม: {', '.join(playing_games)}" if playing_games else "ตอนนี้ไม่มีใครเปิดเกมเล่นอยู่"

                # 📝 เขียน Prompt ส่งให้สมอง AI แปลงร่างเป็นน้องแบ็คลี่ผู้อัจฉริยะและกวนประสาท
                prompt = f"""
                {persona.BRIEF}
                หน้าที่ของคุณคือ สร้างประโยคทักทายหรือเตือนเวลาแบบสดใหม่ (ห้ามซ้ำซาก) โดยใช้ข้อมูลสถานการณ์ปัจจุบันดังนี้:
                
                - เวลาปัจจุบัน: {'เที่ยงคืนตรง (00:00 น.) เริ่มต้นวันใหม่' if now.hour == 0 else 'เที่ยงวันตรง (12:00 น.) ได้เวลามื้อเที่ยง'}
                - บริบทเกมยามนี้: {game_context}
                
                คำแนะนำในการเจนข้อความ:
                1. ถ้าเป็นเวลาเที่ยงคืน: ให้เน้นแซวเรื่องการเล่นเกมข้ามวันข้ามคืน นั่งลากยาวไม่ยอมไปหลับไปนอน (ถ้ามีชื่อเกมระบุอยู่ ให้เอาชื่อเกมนั้นมาแซวประชดขำ ๆ ด้วย เช่น เล่นเกมจนจะสิงเกมแล้ว)
                2. ถ้าเป็นเวลาเที่ยงวัน: ให้เตือนให้ไปกินข้าวมื้อเที่ยง พักสายตา กองทัพต้องเดินด้วยท้อง แซวให้วางมือจากเกมก่อน
                3. ใช้คำพูดภาษาไทยที่เป็นกันเอง ตลก ขี้เล่น มีหางเสียง 'ครับ' แบบเป็นธรรมชาติ (ไม่ต้องใส่ทุกประโยค) และใช้สรรพนามแทนตัวเองว่า 'แบ็คลี่'
                4. ข้อความต้องกระชับ ไม่ยาวจนเกินไป (ประมาณ 2-4 ประโยค) เพื่อให้บอทพูดได้สมูท ไม่ยืดเยื้อ
                
                คำตอบของคุณต้องมีแค่ข้อความที่จะให้บอทพูดเท่านั้น ห้ามมีคำอธิบายอื่นผสม
                """

                # 🚀 ยิงคำสั่งให้ Google Gen AI คิดคำพูดสุดเจ๋งให้
                msg = ""
                if ai_ready:
                    try:
                        print("🤖 [AI]: กำลังคิดคำพูดเตือนเวลารอบพิเศษให้คุณชะอม...")
                        response = await client.aio.models.generate_content(
                            model="chat",
                            contents=prompt,
                        )
                        msg = (response.text or "").strip()
                    except Exception as ai_err:
                        print(f"❌ AI ขัดข้อง: {ai_err} (จะสลับไปใช้ระบบสำรองดั้งเดิม)")
                
                # 🛡️ ระบบสำรอง (Fallback) หาก API ติดขัด จะสุ่มคำพูดเดิมให้ เพื่อป้องกันบอทเอ๋อคัป
                if not msg:
                    if now.hour == 0:
                        msg = f"ขณะนี้เวลาเที่ยงคืนตรงเป๊ะแล้วครับ เริ่มต้นวันใหม่แล้ว ลากยาวเกม {playing_games[0] if playing_games else ''} ข้ามวันเลยหรอเนี่ย ไปนอนกันบ้างนะ"
                    else:
                        msg = "เที่ยงตรงเป๊ะแล้วครับ พักสายตาจากเกมแล้วไปหาของอร่อย ๆ ทานมื้อเที่ยงกันก่อนดีกว่า กองทัพต้องเดินด้วยท้องนะ!"

                # 🔊 สั่งให้บอทเปิดไมค์พูดคำพูดจาก AI ทันทีคัปพ้ม!
                try:
                    await bagley_speak_wait(voice_client.guild, msg)
                    print(f"DEBUG: ⏰ Bagley AI แจ้งเตือนรอบเวลา {now.strftime('%H:%M')} สำเร็จ! ข้อความ: '{msg}'")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนพูดแจ้งเตือนเวลาด้วย AI: {e}")
