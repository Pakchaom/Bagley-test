"""bagley/events/voice_state.py — ตรวจจับคนเข้า-ออกห้องเสียง (on_voice_state_update)"""
import asyncio
import os
import time
from datetime import datetime

from bagley.core import state
from bagley.core.app import bot
from bagley.core.config import bangkok_tz
from bagley.core.logutil import print
from bagley.data.storage import _get_saved_voice_name, _register_voice_entry, get_realtime_name, get_reminders_for_user, load_user_data, load_voice_data, parse_birthday, save_voice_data
from bagley.phrases import VOICE_GUARD_STAY_MESSAGES, VOICE_JOIN_GREETINGS, pick as _pick_speech
from bagley.voice.tts import bagley_speak_wait

REPORT_OVER_MUSIC = os.getenv("REPORT_OVER_MUSIC", "1") != "0"


@bot.event
async def on_voice_state_update(member, before, after):
    
    if state.is_moving_group:
        return

    guild_id = member.guild.id

    if member.id == bot.user.id and after.channel is None:
        state.voice_report_status.pop(guild_id, None)
        state.room_guard_status.pop(guild_id, None) # รีเซ็ตโหมดเฝ้าห้องคัปพ้ม
        state.active_team_splits.pop(guild_id, None) # 🔀 แบ็คลี่ออกจากห้องแล้ว เลิกจำ session แยกห้องทีมของกิลด์นี้
        print(f"DEBUG: ตัวบอทออกจากห้องเสียงแล้ว ทำการรีเซ็ตสวิตช์รายงานเสียงและโหมดเฝ้าห้องของกิลด์ {guild_id}")

    voice_client = member.guild.voice_client
    has_followed_out = False

    if voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        followed_leader_id = state.bot_follow_targets.get(guild_id)
        
        is_target_leaving = False
        if followed_leader_id:
            if member.id == followed_leader_id:
                is_target_leaving = True

        # 🚶‍♂️➡️🚪 [แก้บั๊ก] เดิมเช็คแค่ "before.channel == bot_channel and after.channel != bot_channel"
        # ซึ่งเป็นจริงทั้งกรณีเจ้านาย "ออกจากห้องเสียงไปเลย" (after.channel is None) และกรณี
        # เจ้านาย "แค่ย้ายห้อง" (after.channel เป็นอีกห้องนึง ไม่ใช่ None) พอเข้าเงื่อนไขเดียวกันหมด
        # โค้ดเดิมเลยพูดบอกลา+ตัดสายทันทีแม้เจ้านายแค่ย้ายห้อง แล้วค่อยไปอาศัย
        # follow_creator_task (ลูปทุก 1 นาที) เชื่อมกลับเข้าห้องใหม่ทีหลัง ทำให้บางจังหวะ
        # ลูปนั้นดันมาบิน (move_to) ตามเข้าห้องใหม่ "ระหว่าง" ที่ยังพูดบอกลาไม่จบพอดี
        # กลายเป็นบอทพูดบอกลาทบเสียง/ตามไปพูดค้างคาที่ห้องใหม่ก่อนจะออกจริง
        # ตอนนี้แยกเคสให้ชัดเจน: ถ้าเจ้านายแค่ย้ายห้อง (after.channel ไม่ใช่ None) ให้แบ็คลี่
        # บินตามไปห้องใหม่ทันทีแบบเงียบๆ (ไม่พูดบอกลา ไม่ตัดสาย) ส่วนกรณีออกจากห้องเสียงไปเลย
        # (after.channel is None) เท่านั้นถึงจะเข้าลอจิกพูดบอกลา+ตัดสายแบบเดิม
        if is_target_leaving and before.channel == bot_channel and after.channel is not None and after.channel != bot_channel:
            if not voice_client.is_playing():
                try:
                    await voice_client.move_to(after.channel)
                    has_followed_out = True
                    print(f"DEBUG: 🔄 เจ้านาย {member.display_name} ย้ายห้อง แบ็คลี่บินตามไปห้อง {after.channel.name} ทันทีแบบเงียบๆ ครับ (ไม่พูดบอกลาเพราะยังไม่ได้ออกจากห้องเสียงจริงๆ)")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนบินตามเจ้านายย้ายห้อง: {e}")
            # ถ้าแบ็คลี่ติดเปิดเพลงอยู่ ปล่อยให้ follow_creator_task ตามไปทีหลังตอนเพลงจบตามปกติ

        elif is_target_leaving and before.channel == bot_channel and after.channel is None:
            
            data_memory = load_user_data() 
            special_info = data_memory.get(str(member.id))
            if special_info and isinstance(special_info, dict):
                calling_name = special_info.get("nickname", member.display_name)
            elif special_info:
                calling_name = special_info
            else:
                calling_name = member.display_name
            if calling_name == "ยังไม่ระบุ": calling_name = member.display_name

            if voice_client.is_playing():
                state.pending_exit_after_music[guild_id] = calling_name
                state.bot_follow_targets[guild_id] = None 
                has_followed_out = True 
                print(f"DEBUG: 📌 เจ้านาย {calling_name} ออกจากห้อง แต่แบ็คลี่ติดเปิดเพลงอยู่! แปะโน้ตรอเคลียร์ตอนเพลงจบครับ")
            
            else:
                state.bot_follow_targets[guild_id] = None
                has_followed_out = True 
                
                # ==========================================
                # 🔍 เช็กจำนวนมนุษย์ที่เหลืออยู่ในห้องเสียง (ไม่นับบอท)
                # ==========================================
                remaining_humans = len([m for m in bot_channel.members if not m.bot])
                
                if state.room_guard_status.get(guild_id, False):
                    print(f"DEBUG: เจ้านายออกไปแล้ว แต่กิลด์ {guild_id} เปิดโหมดเฝ้าห้องไว้ แบ็คลี่จะอยู่รอที่นี่คัปพ้ม!")
                    guard_msg = _pick_speech(VOICE_GUARD_STAY_MESSAGES)
                    await bagley_speak_wait(member.guild, guard_msg)
                else:
                    if remaining_humans <= 4:
                        print(f"DEBUG: เจ้านาย {member.display_name} ออกจากห้อง คนเหลือน้อย ({remaining_humans} คน) แบ็คลี่จะพูดบอกลาก่อนออกคัป")
                        exit_msg = f"คุณ {calling_name} ออกไปแล้ว งั้นผมขอออกจากห้องก่อนนะครับ ถ้าอยากให้ผมเข้ามาใหม่ พิมพ์ แบ็คลี่ เข้ามา หรือใช้คำสั่งทับ join ได้เลย ไปก่อนนะ"
                        await bagley_speak_wait(member.guild, exit_msg)
                    else:
                        print(f"DEBUG: คนยังอยู่กันเยอะ ({remaining_humans} คน) แบ็คลี่จะวาร์ปออกแบบเงียบเชียบครับ")
                
                    try:
                        await voice_client.disconnect()
                        state.voice_report_status.pop(guild_id, None)
                    except Exception as e:
                        print(f"❌ เกิดข้อผิดพลาดตอนบอทตัดสายตามเจ้านาย: {e}")

    # 🧹 [ส่วนที่ 1] จัดการเก็บกวาด "ห้องปาร์ตี้สร้างเอง"
    if not has_followed_out and before.channel is not None:
        channel_to_check = before.channel
        is_empty_or_only_bot = (len(channel_to_check.members) == 0) or \
                               (len(channel_to_check.members) == 1 and bot.user in channel_to_check.members)

        if channel_to_check.id in state.created_party_channels and is_empty_or_only_bot:
            if state.room_guard_status.get(guild_id, False):
                print(f"DEBUG: ห้องปาร์ตี้ '{channel_to_check.name}' ว่าง แต่เปิดโหมดเฝ้าห้องไว้ จึงไม่ลบคัป")
            else:
                try:
                    if voice_client and voice_client.channel == channel_to_check:
                        await voice_client.disconnect()
                        state.voice_report_status.pop(guild_id, None)

                    await channel_to_check.delete(reason="ห้องปาร์ตี้ร้าง - Bagley ลบให้อัตโนมัติ")
                    state.created_party_channels.remove(channel_to_check.id)
                    print(f"🗑️ เก็บกวาดห้อง '{channel_to_check.name}' เรียบร้อยครับ")
                    return
                except Exception as e:
                    print(f"❌ ลบห้องไม่ได้: {e}")

    # 🚶‍♂️ [ส่วนที่ 2] ออกจาก "ห้องทั่วไป" เมื่อไม่มีคนอยู่กับบอท
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
            if bot_channel.id in state.created_party_channels:
                return

            if state.room_guard_status.get(guild_id, False):
                pass
            else:
                print(f"DEBUG: ห้องทั่วไป '{bot_channel.name}' ร้างแล้ว แบ็คลี่เตรียมถอนกำลัง...")
                await asyncio.sleep(1.5)
                
                if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
                    try:
                        await voice_client.disconnect()
                        state.voice_report_status.pop(guild_id, None)
                        print(f"DEBUG: แบ็คลี่กดออกจากห้องร้าง '{bot_channel.name}' เรียบร้อยครับ")
                    except Exception as e:
                        print(f"❌ เกิดข้อผิดพลาดในการสั่ง Auto-Leave ห้องทั่วไป: {e}")

    # 📢 [ส่วนที่ 3] ตรวจสอบและรายงานเสียง คนเข้า-ออกห้องเสียงยามปกติ
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        # 🎵 พูดรายงานคนเข้า-ออก "ซ้อนบนเพลง" ได้ (ตัวผสมเสียงหรี่เพลงให้ชั่วคราว ไม่ตัดเพลง)
        # เดิมมีด่าน `if state.is_playing_music: return` ทำให้ตอนเปิดเพลงบอทเงียบไม่รายงานเลย
        # ถ้าอยากกลับไปเงียบตอนเปิดเพลง ใส่ REPORT_OVER_MUSIC=0 ใน .env
        # (ห้าม return ตรงนี้: ด้านล่างยังมีส่วนบันทึกสถิติเวลาที่ต้องทำงานเสมอ — ของเดิม return แล้วสถิติหายตอนเปิดเพลง)
        skip_report_for_music = state.is_playing_music and not REPORT_OVER_MUSIC

        is_reporting_enabled = state.voice_report_status.get(guild_id, True) and not skip_report_for_music

        if is_reporting_enabled:
            data_memory = load_user_data() 
            special_info = data_memory.get(str(member.id))
            
            if special_info:
                if isinstance(special_info, dict):
                    nickname = special_info.get("nickname", "ยังไม่ระบุ")
                    birthday = special_info.get("birthday", "ยังไม่ระบุ")
                else:
                    nickname = special_info
                    birthday = "ยังไม่ระบุ"
            else:
                nickname = "ยังไม่ระบุ"
                birthday = "ยังไม่ระบุ"

            calling_name = nickname if (nickname and nickname != "ยังไม่ระบุ") else get_realtime_name(member.id, member.display_name)
            
            # ⏱️ ดึงวันและเดือนปัจจุบันเพื่อตรวจสอบแบบสากล
            now_time = datetime.now()
            today_day = now_time.day
            today_month = now_time.month

            # 🚪 1. กรณีคน "เข้า" ห้องเสียง
            if before.channel != bot_channel and after.channel == bot_channel:
                if member.id != bot.user.id:
                    await asyncio.sleep(1.0)
                    
                    # 🎂 🔍 แปลงและตรวจสอบเงื่อนไขวันเกิดผ่านฟังก์ชันอัจฉริยะ
                    parsed_bday = parse_birthday(birthday)
                    is_birthday_today = parsed_bday and parsed_bday[0] == today_day and parsed_bday[1] == today_month
                    
                    if is_birthday_today:
                        report = f"คุณ {calling_name} เข้ามาในห้องแล้วครับ โอ้ว... วันนี้เป็นวันพิเศษของคุณนี่นา สุขสันต์วันเกิดนะครับ ขอให้มีความสุขมาก ๆ เล่นเกมชนะรัว ๆ เลยนะ!"
                    else:
                        # 🎲 สุ่มคำทักทายจากชุดคำพูดหลายแบบ กันความจำเจของแบ็คลี่
                        report = _pick_speech(VOICE_JOIN_GREETINGS, name=calling_name)
                    
                    await bagley_speak_wait(member.guild, report)

                    pending_notes = get_reminders_for_user(member.id) 
                    if pending_notes:
                        note_msg = f"อย่าลืมนะครับ คุณมีโน้ตที่ฝากไว้คือ {pending_notes}"
                        await bagley_speak_wait(member.guild, note_msg)

            # 🚪 2. กรณีคน "ออก" ห้องเสียงยามปกติ
            elif before.channel == bot_channel and after.channel != bot_channel:
                if member.id != bot.user.id:
                    msg = f"คุณ {calling_name} ออกจากห้องไปครับ"
                    await bagley_speak_wait(member.guild, msg)
        else:
            print(f"DEBUG: ข้ามการพูดรายงานในกิลด์ {guild_id} เนื่องจากคุณสั่ง 'ปิดรายงานห้องเสียง' ไว้ชั่วคราว")

    # =========================================================
    # ⏱️ ระบบบันทึกสถิติเวลา
    # =========================================================
    user_id = str(member.id)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if before.channel is None and after.channel is not None:
        if user_id not in state.user_join_times:
            state.user_join_times[user_id] = time.time()
            print(f"DEBUG: [⏱️ ขาเข้า] เริ่มจับเวลาให้คุณ {member.display_name} เรียบร้อยครับ!")
        # 📋 บันทึกทันทีว่าเข้าห้องเสียงวันนี้แล้ว (ถึงจะยังไม่ออกจากห้องเลยก็ให้ขึ้นชื่อ
        # ในรายงาน "วันนี้ใครเข้าห้องเสียงบ้าง" ได้ พร้อมจำเวลาที่เข้าห้องครั้งแรกไว้ด้วย)
        _register_voice_entry(member)

    if before.channel is not None and after.channel is None:
        join_time = state.user_join_times.pop(user_id, None)
        if join_time:
            duration = time.time() - join_time
            data = load_voice_data()
            if data.get("date") != today_str:
                data = {"date": today_str, "stats": {}}
            
            stats = data["stats"]
            guild_id_str = str(member.guild.id)

            if guild_id_str not in stats:
                stats[guild_id_str] = {}
                
            guild_stats = stats[guild_id_str]
            if user_id not in guild_stats:
                guild_stats[user_id] = {
                    "total_time": 0,
                    "name": _get_saved_voice_name(member),
                    "first_join": datetime.now(bangkok_tz).strftime("%H:%M"),
                }
            
            guild_stats[user_id]["total_time"] += duration
            save_voice_data(data)
            print(f"DEBUG: [ประจำวันที่ {today_str}] บันทึกเวลาให้ {member.display_name} ในเซิร์ฟ {guild_id_str} แล้วครับ")
