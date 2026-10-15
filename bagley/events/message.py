"""bagley/events/message.py — ตัวรับข้อความ (on_message): ด่านกรอง -> คำสั่งธรรมชาติ -> AI Router -> แชท"""
import asyncio
import discord
import io
import time as _time
import random
import re as regex_lib
import secrets
import traceback
from PIL import Image
from datetime import datetime, timedelta

from bagley.ai import gate as bagley_gate, humanize, persona, understanding
from bagley.ai.classifiers import ai_detect_apology_to_bagley, ai_detect_insult_to_bagley
from bagley.ai.router import ai_route_and_execute, has_pending_clarification, looks_like_personal_reminder, try_resolve_pending_slot_fill
from bagley.core import state
from bagley.core.app import bot, client
from bagley.core.config import OWNER_DISCORD_ID, PENDING_REMINDER_TIMEOUT_SECONDS, SPAM_THRESHOLD, bangkok_tz
from bagley.core.http import get_bytes as http_get_bytes
from bagley.core.logutil import print
from bagley.core.security import block_user_for_today, has_potential_profanity, is_message_addressed_to_bagley, is_reply_to_bagley_message, is_stream_authorized, is_stream_mode_on, is_user_blocked, unblock_user
from bagley.data.storage import _normalize_schedule_date, get_realtime_name, load_reminders, load_user_data, load_voice_data, save_reminders, save_user_data
from bagley.db import conn
from bagley.features import autonomy as bagley_autonomy, ephemeral_tools as ephemeral_tools, knowledge as bagley_knowledge, learning as bagley_learning, rules as bagley_rules, trust as bagley_trust
from bagley.features.members import _describe_member_activities, find_member_by_name, find_voice_member_across_guilds, resolve_target_member
from bagley.features.memory import execute_remember_logic
from bagley.features.party import execute_dm_call, execute_warp_invite, handle_same_game_query
from bagley.features.reminders import handle_remembered_reminder, try_finish_pending_reminder
from bagley.phrases import FORGIVE_REPLIES, pick as _pick_speech, say
from bagley.services.images import _get_cached_image_caption, _remember_image_caption, generate_and_send_image, get_quick_image_caption
from bagley.ui.views import IdentityListPaginator
from bagley.voice.tts import FFMPEG_PATH, bagley_speak, clean_for_speech, synth as tts_synth


@bot.event
async def on_message(message):
    global conn

    is_from_my_webhook = False

    if getattr(message, "is_voice_relay_command", False):
        # ✅ นี่คือคำสั่งเสียงจาก mic_to_discord.py ที่มาผ่าน Local Voice Relay
        # ในเครื่องเท่านั้น (ไม่ใช่ Discord Webhook จริง) ยืนยันว่าใช้ได้
        # 🔧 message.author ถูกกำหนดถูกต้องแล้วตั้งแต่ตอนสร้าง VoiceRelayMessage
        # (เป็นสมาชิกจริงตาม owner_id ที่ mic_to_discord.py ส่งมา เช่น ชะอม
        # หรือ ชาช่า) ไม่ต้องสวมรอยทับด้วย ID คงที่อีกแล้ว
        is_from_my_webhook = True
        original_lower = message.content.strip().lower()

        # ✂️ เตรียมประโยคสำหรับเช็กคีย์เวิร์ดคำสั่งระบบ
        clean_content = message.content.replace("แบ็คลี่", "").replace("bagley", "").strip()
        clean_lower = clean_content.lower()

        voice_keywords = [
            "เตือน", "ฝากบอก", "บอกเพื่อนว่า", "สรุปสถิติห้องเสียง", "ใครคุยนานสุด", "รายงานห้องเสียง", "ทักห้องเสียง",
            "ฝากจำ", "บันทึกตาราง", "ตั้งเตือน", "เรียก", "ชวน", "จัดการ", "เตะ", "เขี่ย", "kick", "ตัดสาย",
            "ย้าย", "เอาไปห้อง", "พาไปห้อง", "แยกกลุ่ม", "ปิดเสียง", "ปิดไมค์", "เปิดเสียงให้ที", "เปิดเสียงให้หน่อย", 
            "เปิดไมค์ให้หน่อย", "เปิดไมค์ให้ที", "เปิดเสียงให้", "เปิดไมค์ให้", "ปลดไมค์ให้", "ปิดหูฟัง", 
            "ทำงานอยู่", "ขอความสงบ", "เปิดหูฟังให้ฉัน", "กลับมาแล้ว", "เลิกทำงานแล้ว", "เปิดหูฟังให้", 
            "ปลดหูฟังให้", "สแกน", "เช็คประวัติ", "ดูโปรไฟล์", "ข้อมูลของ", "คนนี้คือใคร", "เฝ้าห้อง", "เลิกเฝ้า", 
            "หยุดเฝ้า", "ฝากเฝ้า", "เข้ามา", "join", "มานี่", "เข้ามาในห้อง", "เข้ามาห้อง", "เปิดเพลง", 
            "หาเพลง", "play", "เล่นเพลง", "หยุดเพลง", "ปิดเพลง", "stop", "ลำคาญ", "หนวกหู", "ออกไป", 
            "ออกไปก่อน", "ขอคุยธุระ", "ออกจากห้อง", "เพลงถัดไป", "ข้ามเพลง", "เพลงต่อไป", "ข้าม", 
            "ปิดล่าม", "เปิดล่าม", "หยุดพูด", "ไม่ต้องพูด", "พูดให้", "เช็คสถานะระบบ", "ตรวจสอบระบบ", 
            "เช็คการทำงาน", "คุณโอเคมั้ย", "คุณโอเคไหม", "ตรวจสอบสถานะการทำงาน",
            # 🆕 เพิ่มให้ครบทุกคำสั่งที่มีอยู่จริงใน on_message (ไล่เช็คทีละส่วนแล้ว)
            "หายไปไหน", "ไปไหน", "ลงทะเบียน", "สมัคร", "register",
            "ภาพอะไร", "รูปอะไร", "ดูรูปนี้หน่อย", "วาดรูป", "เจนภาพ", "วาดภาพ",
            "จำไว้ว่า", "แปล", "translate", "รายชื่อคนในดิส",
            "สร้างห้อง", "เปิดห้อง", "ตั้งปาร์ตี้",
            "ปิดคอมบริษัท", "ปิดเครื่องบริษัท", "shutdown",
            "รีเซ็ตคำสั่ง", "ตรวจสอบคำสั่ง", "เช็คคำสั่ง",
            "ลืมฉันซะ", "ลบข้อมูลฉัน", "ลืมชื่อคนนี้", "ลบข้อมูลคนนี้",
            "ตามคน", "ตามเพื่อน", "จัดประชุม",
            # 🆕 เช็คไลฟ์สด/คลิปใหม่จาก YouTube ทันที (แทนระบบลูปอัตโนมัติเดิม)
            "แชร์สตรีมล่าสุด", "แชร์คลิปล่าสุด", "เช็คสตรีมล่าสุด", "เช็คยูทูป", "เช็คคลิปใหม่",
            "มีคลิปใหม่ไหม", "มีสตรีมใหม่ไหม",
            # 🆕 ระบบหยุด/เปิดแม่สื่อชวนตี้ (check_and_invite_party) + ถามหาคนเล่นเกมเดียวกัน
            "หยุดหาคน", "เลิกหาคน", "หาคนต่อ", "เปิดหาคน", "กลับมาหาคน",
            "เล่นเกมเดียวกัน", "เกมเดียวกันบ้าง"
        ]
        
        # 1.1 เช็กว่าเป็นคำสั่งระบบไหม
        if any(kw in clean_lower for kw in voice_keywords):
            print(f"🛸 [Voice Command] ส่งต่อคำสั่งเสียง '{clean_content}' ไปประมวลผลระบบด้านล่าง!")
            message.content = clean_content  
            # ปล่อยให้ข้อความไหลลงไปข้างล่างเอง ห้ามใส่ return ห้ามใส่ pass
            
        # 1.2 [แก้ไขให้ถูกต้องที่สุด]: ถ้าเป็นข้อความคุยเล่นทั่วไป ให้ไหลลงไปหาสมอง AI ด้านล่างได้เลย!
        else:
            print(f"💬 [Voice Chat] คุณชะอมชวนคุย ส่งต่อเสียง '{message.content}' ไปหาระบบด้านล่างคัป!")
            # 🌟 ลบ bot.process_commands และ return ออกไปเลยครับ! 
            # ปล่อยให้โค้ดมันไหลทะลุลงไปทำงานในส่วน Teach Memory และ Free Chat ด้านล่างตามธรรมชาติ

    elif message.webhook_id:
        # 🚫 [ปิดใช้งานแล้ว] Discord Webhook จริงจากภายนอกถูกปิดไปแล้วตามที่ขอ
        # ให้บอทรับคำสั่งได้เฉพาะจากคนจริงๆ ในดิสคอร์ด หรือผ่าน Local Voice
        # Relay (mic_to_discord.py ในเครื่องเดียวกัน) เท่านั้น
        return

    # ========================================================
    # 🛑 [ด่านที่ 2]: ดักจับบอทตัวอื่น (ยกเว้นเว็บบุคของเรา)
    # ========================================================
    allowed_ids = [1133740216822267954] # <- ใส่ ID ของคุณชะอม และ ID ของตัวแอปเสียงลงไปในนี้
    
    is_allowed_voice_app = message.author.id in allowed_ids or message.author.name == "ชะอม"

    # ปรับด่านตรวจ: ถ้าเป็นบอทตัวอื่น ที่ไม่ใช่วีไอพีของเรา ให้ดีดออกทันที!
    if message.author.bot and not (is_from_my_webhook or is_allowed_voice_app): 
        print(f"🛑 [ด่านที่ 2] ดักจับและดีดบอทแปลกหน้า ID: {message.author.id} ออกไปแล้วคัป!")
        return

    if message.mention_everyone:
        return

    # ==========================================
    # 🚫 [ด่านที่ 3: เช็กว่าโดนแบนคำสั่งของแบ็คลี่อยู่ไหม]
    # ==========================================
    if not message.author.bot and is_user_blocked(str(message.author.id)):
        stripped_content = message.content.strip()
        lower_check = stripped_content.lower()

        # 🤝 [ระบบง้อ] ถ้าโดนแบนอยู่ แต่แท็ก/เอ่ยชื่อแบ็คลี่พร้อมขอโทษ/ง้อ (ไม่จำเป็นต้องมีคำว่า
        # "ขอโทษ" ตรงๆ ให้ AI ช่วยตัดสิน เช่น "sorry", "ไม่งอนนะ" ก็นับ) -> ปลดแบนให้ทันที
        # ไม่ต้องรอถึงเที่ยงคืน แล้วตอบรับคำขอโทษแบบเป็นมิตร
        if stripped_content and is_message_addressed_to_bagley(lower_check):
            try:
                if await ai_detect_apology_to_bagley(message.content):
                    unblock_user(str(message.author.id))
                    await message.channel.send(
                        f"{message.author.mention} {_pick_speech(FORGIVE_REPLIES)}"
                    )
                    return
            except Exception as e:
                print(f"⚠️ [ด่านที่ 3] ระบบตรวจคำขอโทษทำงานผิดพลาด: {e}")

        # ถ้าเป็นการพิมพ์คำสั่ง (สไตล์ prefix "!") ให้ตอบปฏิเสธสั้นๆ
        if stripped_content.startswith(bot.command_prefix):
            try:
                await message.channel.send(
                    f"{message.author.mention} " + say("blocked_cmd") + " 🙅‍♂️",
                    delete_after=10
                )
            except Exception:
                pass
        # ถ้าเป็นการพิมพ์คุยเล่นทั่วไป แบ็คลี่จะเมินไม่ตอบกลับเลย
        return

    # ==========================================
    # ⏳ [ด่านที่ 3.5: รอคำตอบเวลาแจ้งเตือน ที่เพิ่งถามไปจาก "จำไว้ว่า...พรุ่งนี้มีสอบ" ฯลฯ]
    # ==========================================
    if not message.author.bot and message.content.strip():
        _pending_key = (message.channel.id, message.author.id)
        _pending = state.pending_remember_reminders.get(_pending_key)
        if _pending:
            if (datetime.now() - _pending["asked_at"]).total_seconds() > PENDING_REMINDER_TIMEOUT_SECONDS:
                # เงียบไปนานเกินไป ถือว่ายกเลิกคำถามนี้ไปแล้ว ไม่เอาข้อความใหม่มาจับมั่ว
                state.pending_remember_reminders.pop(_pending_key, None)
            else:
                try:
                    _finish_reply = await try_finish_pending_reminder(message, _pending, get_realtime_name)
                except Exception as e:
                    print(f"⚠️ [Remember Reminder] ปิดคำถามรอเวลาพลาด: {e}")
                    _finish_reply = None
                if _finish_reply is not None:
                    state.pending_remember_reminders.pop(_pending_key, None)
                    await message.reply(_finish_reply)
                    return
                # ยังจับเวลาจากคำตอบไม่ได้ -> ปล่อยข้อความไหลต่อไปตามปกติ (เผื่อเป็นข้อความอื่นที่ไม่เกี่ยวกัน
                # เดี๋ยวคำถามก็ยังค้างรออยู่จนกว่าจะตอบเวลามาจริงๆ หรือหมดเวลา)

    # ==========================================
    # 🧩 [ด่านที่ 3.6: รอคำตอบที่ขาดของคำสั่ง (เช่น 'ตั้งเวลาเตะ' ที่ถามเวลากลับไปแล้ว)]
    # ผูกกับระบบ Slot Filling ใน ai_command_router.py — ถ้าเพิ่งถามผู้ใช้คนนี้ในห้องนี้ไปว่า
    # "กี่โมงครับ" ให้ลองแกะข้อความถัดไปมาเติมค่าแล้วยิงคำสั่งเดิมทันที ก่อนจะไหลไปเข้าระบบอื่นใดๆ
    # ==========================================
    if not message.author.bot and message.content.strip():
        try:
            if await try_resolve_pending_slot_fill(message, bot, find_member_by_name):
                return
        except Exception as e:
            print(f"⚠️ [ด่านที่ 3.6] ระบบ Slot Filling ทำงานผิดพลาด: {e}")

    # ==========================================
    # 🚨 [ด่านที่ 4: ตรวจจับคำหยาบที่พิมเจาะจงใส่แบ็คลี่ตรงๆ]
    # ==========================================
    if (
        not message.author.bot
        and not is_from_my_webhook
        and message.author.id != OWNER_DISCORD_ID
        and message.content.strip()
    ):
        _lower_check = message.content.lower()
        if is_message_addressed_to_bagley(_lower_check) and has_potential_profanity(message.content):
            try:
                if await ai_detect_insult_to_bagley(message.content):
                    await message.channel.send(
                        f"{message.author.mention} คำพูดที่คุณพูดมาดูไม่ดีเลยนะครับ 😔 "
                        f"ขออนุญาตแบนคำสั่งของคุณไปก่อนจนกว่าจะถึงเที่ยงคืนนะครับ"
                    )
                    block_user_for_today(str(message.author.id))
                    return
            except Exception as e:
                print(f"⚠️ [ด่านที่ 4] ระบบตรวจคำหยาบทำงานผิดพลาด: {e}")

    # ==========================================
    # 🔇 [ด่านที่ 4.5: สั่งให้แบ็คลี่ "เงียบ/หุบปาก" หยุดทักเอง]
    # หยุดระบบทักเอง (bagley_autonomy.autonomy_loop) เฉพาะเซิร์ฟเวอร์นี้ทันที บันทึกถาวรลง DB
    # จนกว่าจะมีใครคุยกับแบ็คลี่ตรงๆ อีกครั้ง (ดูจุดที่เรียก unsilence_guild ด้านล่าง) ถึงจะเปิดกลับมาเอง
    # ==========================================
    if (
        message.guild is not None
        and not message.author.bot
        and message.content.strip()
    ):
        _silence_lower_check = message.content.lower()
        if (
            is_message_addressed_to_bagley(_silence_lower_check)
            and bagley_autonomy.is_silence_request(_silence_lower_check)
        ):
            bagley_autonomy.silence_guild(message.guild.id)
            try:
                await message.channel.send(
                    "รับทราบครับ 🤐 ผมจะหยุดทักเองในเซิร์ฟเวอร์นี้ไปก่อนนะครับ "
                    "จนกว่าจะมีใครมาชวนผมคุยเล่นอีกครั้งถึงจะกลับมาทักเองแบบเดิมครับ"
                )
            except Exception:
                pass
            return

    # ==========================================
    # 🎮 [ด่านที่ 4.6: สั่งให้แบ็คลี่ "หยุดหาคน" / "หาคนต่อ"]
    # หยุด/เปิดระบบ check_and_invite_party (แม่สื่อชวนตี้ที่คอยบอกว่าใครนอกห้องเสียง
    # เพิ่งเปิดเกมตรงกับคนในห้อง) เฉพาะเซิร์ฟเวอร์นี้เท่านั้น ไม่กระทบระบบเตือนเล่นเกมนาน
    # หรือระบบอื่นๆ เลย — เก็บสถานะไว้ในแรม (party_matcher_disabled_guilds) รีเซ็ตเมื่อบอทรีสตาร์ท
    # ==========================================
    if (
        message.guild is not None
        and not message.author.bot
        and message.content.strip()
    ):
        _party_lower_check = message.content.lower()
        if is_message_addressed_to_bagley(_party_lower_check):
            _stop_party_keywords = (
                "หยุดหาคน", "เลิกหาคน", "ไม่ต้องหาคนละ", "ไม่ต้องหาคนแล้ว",
                "หยุดชวนคนเล่นเกมเดียวกัน", "ไม่ต้องชวนคนเล่นเกมเดียวกัน",
                "หยุดบอกคนเล่นเกมเดียวกัน", "ไม่ต้องบอกคนเล่นเกมเดียวกัน",
            )
            _resume_party_keywords = ("หาคนต่อ", "เปิดหาคน", "กลับมาหาคน", "หาคนเหมือนเดิม")

            if any(kw in _party_lower_check for kw in _stop_party_keywords):
                state.party_matcher_disabled_guilds.add(message.guild.id)
                try:
                    await message.reply(
                        "รับทราบครับ 🙅‍♂️ ผมจะหยุดคอยบอกว่าใครนอกห้องเปิดเกมเดียวกันอยู่บ้างในเซิร์ฟนี้ก่อนนะครับ "
                        "จนกว่าจะสั่งให้ผมหาคนต่ออีกที"
                    )
                except Exception:
                    pass
                return
            elif any(kw in _party_lower_check for kw in _resume_party_keywords):
                state.party_matcher_disabled_guilds.discard(message.guild.id)
                try:
                    await message.reply("โอเคครับ กลับมาคอยสอดส่องคนเล่นเกมเดียวกันให้เหมือนเดิมแล้วนะครับ 🕵️")
                except Exception:
                    pass
                return

    # ==========================================
    # 🎮 [ด่านที่ 4.7: ถามหา "ใครเล่นเกมเดียวกับเราบ้าง"]
    # ตอบทันทีแบบไม่ต้องผ่าน AI (เช็คตรงจาก activity จริง) ใช้ชื่อจากคลังความจำก่อนเสมอ
    # ==========================================
    if (
        message.guild is not None
        and not message.author.bot
        and message.content.strip()
    ):
        _same_game_lower = message.content.lower()
        if is_message_addressed_to_bagley(_same_game_lower) and (
            "เล่นเกมเดียวกัน" in _same_game_lower or "เกมเดียวกันบ้าง" in _same_game_lower
        ):
            await handle_same_game_query(message)
            return

    user_message = message.content.lower().strip()

    global conn
    cursor = conn.cursor()
    user_id = str(message.author.id)
    lower_content = message.content.lower()
    now = datetime.now()
    
    # ดึงความจำคำสั่งสอนของบอทมาก่อน (จะนำไปใช้พิจารณาตอบท้ายฟังก์ชัน)
    cursor.execute("SELECT keyword, response FROM teach_memory")
    all_memories = cursor.fetchall()

    final_text = None
    for keyword, response_text in all_memories:
        if message.guild:
            pattern = rf"แบ็คลี่\s*{regex_lib.escape(keyword)}\b"
        else:
            pattern = rf"\b{regex_lib.escape(keyword)}\b"
        
        if regex_lib.search(pattern, lower_content):
            caller_mention = message.author.mention
            final_text = response_text.replace("{user}", caller_mention)
            break

    # ==========================================
    # 🤖 [ด่านที่ 5: AI Command Router]
    # ให้ AI (function calling) ตัดสินใจเองว่าข้อความนี้ควรสั่งคำสั่งไหนของบอท
    # ถ้าตีความว่าเป็นคำสั่ง -> เรียกคำสั่งจริงให้ทันทีแล้ว return เลย
    # ถ้าไม่ใช่คำสั่ง (คุยเล่นทั่วไป) -> ไหลลงไปทำ teach memory / free chat ตามปกติ
    # ==========================================
    # 🧠 [ระบบเรียนรู้] สะสมข้อความในห้องไว้ให้ AI สรุปเป็น insight เป็นระยะ (ไม่ใช่ทุกข้อความที่คุยกับแบ็คลี่)
    # 🏠 [ระบบเรียนรู้] ทำเครื่องหมายว่าห้องนี้บอท "เคยถูกเรียก/เกี่ยวข้องด้วยจริง" ก่อนสะสมข้อความ —
    # กันไม่ให้ bagley_learning/bagley_autonomy ไปอ่านหรือพูดเองในห้องอื่นที่บอทไม่เคยเกี่ยวข้องด้วยเลย
    # (เช่นห้องที่แค่มีคนคุยกันเอง ไม่เคยเรียกบอท) — ดู bagley_learning.mark_channel_active
    _addressed_to_bagley_now = (
        not message.author.bot
        and (
            message.guild is None
            or is_from_my_webhook
            or is_message_addressed_to_bagley(lower_content)
            # 💬 นับว่า "เรียกบอท" ด้วย ถ้าเป็นการตอบกลับ (reply) ข้อความใดๆ ที่แบ็คลี่เคยพูด/พิมพ์ไว้ก่อนหน้า
            # ไม่ว่าจะเป็นข้อความที่แบ็คลี่ทักขึ้นเอง หรือข้อความที่แบ็คลี่ตอบใครไว้ก่อน — ไม่ต้องพิมพ์ชื่อ
            # แบ็คลี่ในข้อความที่ reply มาเลยก็ได้ เหมือนพฤติกรรมใน DM
            or await is_reply_to_bagley_message(message)
        )
    )

    if message.guild is not None and _addressed_to_bagley_now:
        bagley_learning.mark_channel_active(message.channel.id, message.guild.id)

    # 🖼️ [ใหม่] ถ้ามีคนแนบรูปภาพมาในห้องที่บอทเคยเกี่ยวข้องด้วย (is_channel_active) แต่ "ไม่ได้" เรียกชื่อ
    # บอทตรงๆ ให้แคปชั่นรูปสั้นๆ เก็บเข้าระบบเรียนรู้/ชวนคุยไว้ด้วย (ให้ bagley_autonomy เอาไปใช้ทักทาย/
    # แซวเกี่ยวกับรูปนั้นเองทีหลังได้ คล้ายๆระบบสแกนรูปที่มีอยู่ แต่ทำงานเบื้องหลังไม่ตอบกลับทันที)
    # ถ้าเรียกชื่อบอทตรงๆ มาพร้อมรูป ปล่อยให้ระบบสแกนรูปเต็มรูปแบบ (ส่วนที่ 10 ด้านล่าง) จัดการแทน กันแคปซ้ำ 2 รอบ
    _image_caption_for_learning = None
    if (
        not message.author.bot
        and message.guild is not None
        and message.attachments
        and not _addressed_to_bagley_now
        and bagley_learning.is_channel_active(message.channel.id)
    ):
        _img_attachment_for_learning = next(
            (a for a in message.attachments if a.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))),
            None,
        )
        if _img_attachment_for_learning:
            _image_caption_for_learning = await get_quick_image_caption(_img_attachment_for_learning.url)
            _remember_image_caption(message.id, _image_caption_for_learning)

    if not message.author.bot and (message.content.strip() or _image_caption_for_learning):
        bagley_learning.track_message(
            message.channel.id,
            get_realtime_name(message.author.id, message.author.display_name),
            message.content,
            image_caption=_image_caption_for_learning,
        )

    # 🧠 [Knowledge] เรียนรู้เองจากข้อความที่ "เรียกแบ็คลี่" (เล่าเรื่องตัวเอง/สอนความรู้) แบบเบื้องหลัง
    # ไม่ต้องพิมพ์ "จำไว้ว่า" — รันขนานกับขั้นตอนอื่น ไม่หน่วงการตอบ; Free Chat จะรอผลไม่เกิน 3 วินาทีเพื่อ
    # ให้ตอบรับสิ่งที่เพิ่งได้ยินได้ทันที (ดู bagley/features/knowledge.py)
    _learn_task = None
    if _addressed_to_bagley_now and message.content.strip():
        humanize.note_user_message(message.guild.id if message.guild else None, message.content)
        _learn_task = asyncio.create_task(bagley_knowledge.maybe_learn(message, get_realtime_name))

        def _after_learn(t, _m=message):
            try:
                if not t.cancelled() and t.result():
                    asyncio.create_task(bagley_knowledge.react_learned(_m))
            except Exception:
                pass
        _learn_task.add_done_callback(_after_learn)

        # 🗂️ ขอดู/ขอให้ลืมความจำด้วยภาษาพูด ("รู้อะไรเกี่ยวกับฉันบ้าง", "ลืมเรื่องส้มตำไปเลย")
        # ต้องมาก่อน AI Router เพราะไม่งั้น "ลืม..." จะไปชนคำสั่ง /forget
        if await bagley_knowledge.handle_memory_request(message, get_realtime_name):
            return

    # 📜 [Rules] เช็คก่อนว่าข้อความนี้เป็นการ "จำไว้ว่า.../สั่งสอน/กำหนดกฎ" ให้แบ็คลี่จำมั้ย (ดู bagley_rules.py)
    # AI จะแยกหมวดให้ก่อนว่าเป็น ข้อมูลส่วนตัว (personal) / กฎถาวร (rule) / เรื่องที่ต้องตั้งเตือน (reminder)
    # ทำก่อนไหลลงไป teach_memory/free chat/AI command router ตามปกติ
    if _addressed_to_bagley_now:
        remember_result = await bagley_rules.maybe_learn_from_message(message, get_realtime_name)
        if remember_result:
            remember_category, remember_payload = remember_result
            if remember_category == "rule":
                await message.reply(remember_payload)
                return
            elif remember_category == "personal":
                await execute_remember_logic(message)
                return
            elif remember_category == "reminder":
                await handle_remembered_reminder(message, remember_payload, get_realtime_name)
                return

    stripped_for_ai = message.content.strip()
    if stripped_for_ai and not stripped_for_ai.startswith(bot.command_prefix):
        should_try_ai_command = (
            message.guild is None
            or is_from_my_webhook
            or is_message_addressed_to_bagley(lower_content)
            # 💬 นับว่า "เรียกบอท" ด้วย ถ้าเป็นการตอบกลับ (reply) ข้อความใดๆ ของแบ็คลี่ก่อนหน้า
            # (ทั้งข้อความทักขึ้นเอง และข้อความที่ตอบใครไว้ก่อน) แม้ผู้ใช้จะไม่ได้เอ่ยชื่อ/แท็กบอทตรงๆ
            # ในข้อความที่ตอบกลับมาเลยก็ตาม เหมือนพฤติกรรมใน DM
            or await is_reply_to_bagley_message(message)
            # ❓ แบ็คลี่เพิ่งถามกลับเรื่องคำสั่งที่ขาดข้อมูล -> ข้อความนี้คือคำตอบ ไม่ต้องเรียกชื่อซ้ำ
            or has_pending_clarification(message)
        )
        # 🎥 [โหมดสตรีม] ถ้ากิลด์นี้เปิดโหมดสตรีมอยู่ รับคำสั่ง (ผ่าน AI Router/พิมพ์ธรรมชาติ หรือความสามารถ
        # ชั่วคราว) เฉพาะเจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้น คนอื่นข้ามส่วนสั่งคำสั่งพวกนี้ไปเลย
        # (แต่ยังคุยเล่นทั่วไปกับแบ็คลี่ต่อได้ตามปกติ ไหลลงไปเข้า teach memory/free chat ด้านล่างแทน)
        _stream_mode_blocks_command = (
            message.guild is not None
            and not message.author.bot
            and is_stream_mode_on(message.guild.id)
            and not is_stream_authorized(message.author, message.guild)
        )

        if should_try_ai_command and not _stream_mode_blocks_command:
            # 🤝 [ระบบ Trust] นับว่าคนนี้คุยกับแบ็คลี่ตรงๆ อีกครั้ง (ใช้สะสมสิทธิ์ ephemeral tools)
            if message.guild is not None and not message.author.bot:
                bagley_trust.track_interaction(message.author.id, message.guild.id)
                # 🌱 [Autonomy] มีคนมาคุยกับแบ็คลี่ตรงๆ แล้ว — ถ้าเซิร์ฟเวอร์นี้เคยถูกสั่งเงียบไว้
                # (บอกให้เงียบ/หุบปาก) ให้เปิดระบบทักเองกลับมาอัตโนมัติทันที
                bagley_autonomy.unsilence_guild(message.guild.id)

            # 🧭 ดึงบริบทแชทล่าสุดให้ AI เข้าใจคำอ้างอิง (เฉพาะข้อความที่ดูเป็นการสั่ง — ไม่ยิง REST โดยไม่จำเป็น)
            _ctx_text = ""
            if has_pending_clarification(message) or bagley_gate.looks_like_command(message.content) \
                    or understanding.looks_requestish(message.content):
                _ctx_text = await understanding.fetch_recent_context(
                    message, 6, get_realtime_name, bot.user.id if bot.user else None)

            handled = await ai_route_and_execute(message, bot, client, find_member_by_name, context_text=_ctx_text)
            if handled:
                return

            # ⚡ [Ephemeral Tools] ไม่ตรงคำสั่งไหนที่มีอยู่แล้วเลย -> ลองให้ AI เขียนความสามารถชั่วคราวดู
            # (เฉพาะคนที่มีสิทธิ์ตาม ephemeral_tools._is_dynamic_allowed เท่านั้น คนอื่นจะคืน False เฉยๆ
            #  แล้วไหลลงไปทำ teach memory / free chat ตามปกติ ไม่กระทบผู้ใช้ทั่วไป)
            # 🛡️ [แก้บั๊ก] กันไม่ให้ Ephemeral Tools แย่งข้อความ "เตือนฉันตอน.../เตือน @เพื่อน ตอน..." ไปเขียน
            # โค้ดชั่วคราวเอง — SafeAPI ไม่มีความสามารถตั้งเวลา/แจ้งเตือนเลย พอเจอข้อความแบบนี้มันเลยได้แต่
            # เขียนโค้ดที่ await api.send(...) อธิบายว่า "เข้าถึงเวลา/ระบบตั้งเวลาไม่ได้" แล้วคืน handled=True
            # ทำให้ on_message return ทันที ไม่มีทางไหลไปถึงระบบเตือนตัวเอง/เพื่อนจริงที่ [ส่วนที่ 2] ด้านล่างเลย
            # ใช้เงื่อนไขเดียวกับที่ ai_route_and_execute กันไว้แล้วข้างบน (looks_like_personal_reminder)
            if not looks_like_personal_reminder(message.content):
                handled = await ephemeral_tools.try_create_and_run(message, message.content, _ctx_text)
                if handled:
                    return

    # ==========================================
    # 🚨 [ส่วนที่ 1: ระบบตรวจจับสแปม]
    # ==========================================
    current_content = message.content.strip()
    if current_content and not is_from_my_webhook: 
        if user_id in state.spam_check:
            data = state.spam_check[user_id]
            if data['content'] == current_content and (now - data['last_time']).total_seconds() < 60:
                data['count'] += 1
                if data['count'] >= SPAM_THRESHOLD:
                    try:
                        await message.delete()
                        if data['count'] == SPAM_THRESHOLD:
                            await message.channel.send(
                                f"🚨 **ระบบตรวจพบการสแปม!** \n{message.author.mention} " + say("spam_stop"),
                                delete_after=15
                            )
                            if message.guild and message.guild.voice_client:
                                await bagley_speak(message.guild, say("spam_alert", name=get_realtime_name(message.author.id, message.author.display_name)))
                        return
                    except discord.Forbidden: 
                        pass
            else:
                state.spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}
        else:
            state.spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}

    # ==========================================
    # ⏰ [ส่วนที่ 2: ระบบแจ้งเตือนความจำ]
    # ==========================================
    if "เตือน" in lower_content and ("ตอน" in lower_content or "เวลา" in lower_content):
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        # คุยใน DM ทำได้เลยทันที / ถ้าในเซิร์ฟเวอร์ต้องเรียกชื่อบอท
        if message.guild is None or is_bot_called:
            target_user_id = None
            target_display_name = ""
            is_remind_self = False

            if "เตือนฉัน" in lower_content or "เตือนผม" in lower_content:
                is_remind_self = True
                target_user_id = message.author.id
                target_display_name = "ตัวเอง"
            else:
                has_id = regex_lib.search(r'(\d{17,19})', message.content)
                if message.mentions:
                    target_user = message.mentions[0]
                    target_user_id = target_user.id
                    target_display_name = f"คุณ {get_realtime_name(target_user.id, target_user.display_name)}"
                elif has_id:
                    target_user_id = int(has_id.group(1))
                    try:
                        fetched_user = await bot.fetch_user(target_user_id)
                        if fetched_user:
                            target_display_name = f"คุณ {get_realtime_name(fetched_user.id, fetched_user.display_name)}"
                    except:
                        target_display_name = f"พรรคพวก ID: {target_user_id}"
                elif message.guild is not None:
                    # 🔍 ไม่ได้แท็ก/ไม่มี ID ให้ลองแกะชื่อจากข้อความ เทียบกับคลังความจำ/ชื่อดิสคอร์ดแทน
                    named_target, _ = resolve_target_member(
                        message,
                        remove_keywords=["แบ็คลี่", "bagley", "เตือน", "ตอน", "เวลา"]
                    )
                    if named_target:
                        target_user_id = named_target.id
                        target_display_name = f"คุณ {get_realtime_name(named_target.id, named_target.display_name)}"

            if target_user_id:
                try:
                    time_match = regex_lib.search(r'(\d{1,2}[:.]\d{2})', message.content)
                    if time_match:
                        target_time = time_match.group(1).replace('.', ':').zfill(5)
                        note_text = message.content.split("ว่า")[-1].strip() if "ว่า" in message.content else "ถึงเวลาแล้วครับ!"
                        
                        if is_remind_self:
                            user_data = load_user_data()
                            if "reminders" not in user_data:
                                user_data["reminders"] = []
                                
                            user_data["reminders"].append({
                                "user_id": str(target_user_id),
                                "time": target_time,
                                "content": note_text,
                                "channel_id": str(message.channel.id),
                                "is_notified": False
                            })
                            save_user_data(user_data)
                            await message.reply(say("self_alarm_set", time=target_time, note=note_text) + " ⏰")
                        else:
                            reminders = load_reminders()
                            reminders.append({
                                "target_id": str(target_user_id),
                                "from": get_realtime_name(message.author.id, message.author.display_name),
                                "time": target_time,
                                "text": note_text
                            })
                            save_reminders(reminders)
                            await message.reply(f"รับทราบครับ! ผมตั้งนาฬิกาปลุกไว้ตอน {target_time} แล้ว ผมจะรีบตามไปกระซิบแจ้งเตือน {target_display_name} ให้เองครับ! 🫡⏰")
                        return
                    else:
                        await message.reply("ขออภัยครับ ผมงงเวลานิดหน่อย รบกวนพิมพ์ระบุเวลาแบบ '21:00' ด้วยน้า")
                        return
                except Exception as e:
                    print(f"DEBUG Error Reminder System: {e}")
                    await message.reply("เกิดข้อผิดพลาดด้านเทคนิคในการบันทึกระบบแจ้งเตือนครับ")
                    return
            else:
                await message.reply("คุณพิมพ์คำสั่งไม่ครบถ้วนครับ รบกวนพิมพ์ระบุ เช่น 'เตือนฉันตอน 21:00' หรือ 'เตือน @ชื่อเพื่อน ตอน 21:00' น้าครับ")
                return

    # ==========================================
    # 📝 [ส่วนที่ 3: ระบบฝากข้อความ/บอกเพื่อนตอนไม่อยู่]
    # ==========================================
    trigger_words = ["ฝากบอกว่า", "ฝากบอกทีว่า", "บอกเพื่อนว่า", "ฝากบอก"]
    found_trigger = next((word for word in trigger_words if word in lower_content), None)

    if found_trigger:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        # คุยใน DM สั่งฝากข้อความได้เลยทันทีไม่ต้องพิมพ์ชื่อบอท
        if message.guild is None or is_bot_called:
            parts = message.content.split(found_trigger, 1)
            reason = parts[1].strip() if len(parts) > 1 else ""

            if reason:
                try:
                    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    cursor.execute("INSERT OR REPLACE INTO user_status (user_id, status_message, is_away, timestamp) VALUES (?, ?, ?, ?)",
                                (str(message.author.id), reason, 1, now_str))
                    conn.commit()
                    await message.reply(say("note_saved", reason=f"**{reason}**"))
                    return  
                except Exception as db_err:
                    print(f"❌ [DEBUG ฝากบอก ERROR]: {db_err}")
                    return
            else:
                await message.reply("คุณลืมบอกครับว่าให้ฝากบอกว่าอะไร?")
                return

    # ตรวจสอบคนหาย (ระบบตามหาเพื่อน - ใช้ได้เฉพาะในกลุ่ม)
    if message.guild is not None and ("หายไปไหน" in message.content or "ไปไหน" in message.content or message.mentions):
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if any(keyword in lower_content for keyword in bot_keywords):
            target_user = None
            cursor.execute("DELETE FROM user_status WHERE timestamp < DATETIME('now', '-30 minutes')")
            conn.commit()

            if message.mentions:
                target_user = next((u for u in message.mentions if u.id != bot.user.id), None)
            else:
                cursor.execute("SELECT user_id FROM user_status WHERE is_away = 1")
                active_away_users = cursor.fetchall()
                for (uid,) in active_away_users:
                    member = message.guild.get_member(int(uid))
                    if member and (member.display_name in message.content or member.name in message.content):
                        target_user = member
                        break

            if target_user:
                cursor.execute("SELECT status_message, is_away, timestamp FROM user_status WHERE user_id = ?", (str(target_user.id),))
                row = cursor.fetchone()
                if row:
                    status_msg, is_away, timestamp_str = row
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                    
                    if is_away == 1 and datetime.now() < timestamp + timedelta(minutes=30):
                        name = get_realtime_name(target_user.id, target_user.display_name)

                        # 🆕 [AI-generated] เดิมสุ่มมุกจากลิสต์คงที่ 3 แบบ ตอนนี้ให้ AI เจนประโยค
                        # แซวธรรมชาติแบบใหม่ทุกครั้งจากสิ่งที่เจ้าตัวฝากบอกไว้ (status_msg) เหมือนระบบ
                        # เจนคำแจ้งเตือน/ตื๊อชวนตี้ที่มีอยู่แล้วในบอท ถ้า AI พังค่อย fallback ไปใช้มุกเดิม
                        try:
                            away_reply_prompt = f"""
                            {persona.BRIEF}
สถานการณ์: คุณกำลังตอบคำถามว่า
                            "{name} หายไปไหน" ให้เพื่อนในกลุ่มฟัง

                            [ข้อความที่ {name} ฝากบอกไว้ก่อนหายตัวไป]: "{status_msg}"

                            หน้าที่: เจนประโยคตอบสั้นๆ 1 ประโยค เป็นธรรมชาติ อ้างอิงข้อความที่ฝากไว้ตรงๆ
                            (ห้ามเปลี่ยนความหมาย) แต่ใส่มุกแซวกวนๆ นิดหน่อยแบบเพื่อนหยอกเพื่อน
                            กฎ: ห้ามหยาบคาย ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น ลงท้ายด้วย "ครับ"
                            """
                            away_ai_resp = await client.aio.models.generate_content(
                                model="chat", contents=away_reply_prompt
                            )
                            selected_joke = (away_ai_resp.text or "").strip()
                            if not selected_joke:
                                raise ValueError("AI ตอบข้อความว่างเปล่า")
                        except Exception as ai_err:
                            print(f"❌ AI เจนคำตอบระบบฝากบอกพัง ย้อนกลับไปใช้มุกสำรอง: {ai_err}")
                            jokes = [
                                f"คุณ {name} ฝากบอกว่า '{status_msg}' ครับ แต่ทรงนี้น่าจะแอบไปนอนมากกว่า",
                                f"เจ้าตัวบอกว่า '{status_msg}' นะครับ แต่อย่าไปเชื่อมากเลย ผมว่าแอบไปอู้งาน!",
                                f"พิกัดล่าสุดของ {name} คือ '{status_msg}' ครับ!"
                            ]
                            selected_joke = random.choice(jokes)

                        await message.channel.send(f"🤖 **[BAGLEY]**: {selected_joke}")
                        await bagley_speak(message.guild, selected_joke)
                        return

                if "หายไปไหน" in message.content or "ไปไหน" in message.content:
                    reply = f"คุณ {get_realtime_name(target_user.id, target_user.display_name)} ไม่ได้บอกอะไรไว้เลยครับ สงสัยจะหายตัวไปเฉยๆ!"
                    await message.channel.send(f"🤖 **[BAGLEY]**: {reply}")
                    await bagley_speak(message.guild, reply)
                    return

    # ==========================================
    # 🔍 [ส่วนที่ 4: ระบบเช็คประวัติ คนนี้คือใคร]
    # ==========================================
    if "คนนี้คือใคร" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None:
                await message.reply("ขออภัยครับ! คำสั่งเช็คประวัติต้องใช้ภายในเซิร์ฟเวอร์หลักเท่านั้นน้า ใน DM ผมเชื่อมต่อระบบคัดกรองไม่ได้ครับ! 🛸❌")
                return
            
            guild = message.guild
            target_user = None
            has_id = regex_lib.search(r'(\d{17,19})', message.content)
            
            if has_id:
                target_id = int(has_id.group(1))
                member_in_guild = guild.get_member(target_id)
                if member_in_guild:
                    target_user = member_in_guild
                else:
                    await message.reply("หว่า... ผมส่องเรดาร์หาคนๆ นี้ในเซิร์ฟเวอร์ปัจจุบันไม่เจอเลยครับ ข้อมูลของเขาจะถูกล็อกไว้เพื่อความเป็นส่วนตัวน้า 🤫❌")
                    return
            elif message.mentions:
                target_user = message.mentions[0]
            else:
                # 🔍 ไม่ได้แท็ก/ไม่มี ID ให้ลองแกะชื่อจากข้อความ เทียบกับคลังความจำ/ชื่อดิสคอร์ดแทน
                target_user, _ = resolve_target_member(
                    message,
                    remove_keywords=["แบ็คลี่", "bagley", "คนนี้คือใคร"]
                )

            if target_user:
                data_memory = load_user_data()
                user_info = data_memory.get(str(target_user.id))
                
                if user_info:
                    if isinstance(user_info, str):
                        await message.reply(f"คนนี้เหรอครับ... ผมจำได้ว่าเขาคือ '{user_info}' ครับ")
                    else:
                        nickname = user_info.get("nickname", "ยังไม่มีฉายา/ชื่อเล่น")
                        birthday = user_info.get("birthday", "ยังไม่ได้ระบุวันเกิด")
                        response_msg = (f"คนนี้เหรอครับ... ข้อมูลในสมองกลผมบอกว่า:\n"
                                        f"🔹 **ฉายา/ชื่อเล่น:** {nickname}\n"
                                        f"🎂 **วันเกิด:** {birthday} ครับ!")
                        await message.reply(response_msg)
                else:
                    await message.reply(f"ขออภัยครับ ผมยังไม่มีข้อมูลของ คุณ {get_realtime_name(target_user.id, target_user.display_name)} ในฐานข้อมูลเลยครับ")
            else:
                await message.reply("ช่วย @Tag (Mention) เพื่อน หรือพิมพ์ใส่เลข ID ของคนที่อยากให้ผมเช็คประวัติด้วยน้าครับ!")
            return

    # ==========================================
    # 📊 [ส่วนที่ 5: ดูรายชื่อทั้งหมด / รายชื่อคนในดิส - รองรับ DM แบบมาสเตอร์]
    # ==========================================
    if "รายชื่อคนในดิส" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            try:
                MY_MASTER_ID = 1133740216822267954
                user_data = load_user_data()

                if not user_data:
                    await message.reply("ตอนนี้คลังความจำของผมยังว่างเปล่าอยู่เลยครับ")
                    return

                # 🔒 [ปรับปรุงใหม่]: เช็คว่าเป็นการตั้งใจเรียกดูข้อมูลมาสเตอร์ทั้งหมดจริง ๆ หรือไม่
                is_master_command = "ทั้งหมด" in lower_content or "ทุกเซิร์ฟ" in lower_content

                # --- เคสที่ 1: คุยใน DM (message.guild เป็น None) ---
                if message.guild is None:
                    # ถ้าคุยใน DM แต่ไม่ได้พิมพ์คำว่า "ทั้งหมด" หรือ "ทุกเซิร์ฟ" -> ปฏิเสธทันที!
                    if not is_master_command:
                        await message.reply("ขออภัยครับ! หากคุยใน DM ไม่สามารถเช็คแค่รายชื่อคนในดิสได้จะต้องเปิดใช้แค่ 'รายชื่อคนในดิสทั้งหมด' เพื่อเรียกคลังข้อมูลระบบตาทิพย์น้าครับ! 🛸❌")
                        return
                    
                    # ถ้าพิมพ์คำว่าทั้งหมดมาแล้ว แต่ ID ไม่ใช่ Master ผู้สร้าง -> ปฏิเสธสิทธิ์
                    if message.author.id != MY_MASTER_ID:
                        await message.reply("ขออภัยครับ คำสั่งระดับสูงนี้ถูกจำกัดสิทธิ์ไว้เฉพาะผู้สร้างผมขึ้นมาเท่านั้นครับ! 🤫❌")
                        return
                    
                    # ผ่านฉลุยแสดงข้อความทั้งหมดใน DM (ใช้ตัวเพจแบบเดียวกับ /memberlist กันข้อความยาวเกิน 2000 ตัวอักษร)
                    title_text = "👁️ คลังระบบตาทิพย์: รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟ"
                    formatted_list = []
                    for user_id_str, data in user_data.items():
                        if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                        formatted_list.append(f"<@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})")

                    if not formatted_list:
                        await message.reply("ในขอบเขตนี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับ!")
                        return

                    view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
                    view.message = await message.reply(embed=view.create_embed(), view=view)
                    return

                # --- เคสที่ 2: คุยในเซิร์ฟเวอร์กลุ่มปกติ ---
                else:
                    # ถ้าอยู่ในกลุ่มดันพิมพ์คำว่า "ทั้งหมด" มาด้วย และคนพิมพ์คือมาสเตอร์
                    if is_master_command and message.author.id == MY_MASTER_ID:
                        title_text = "👁️ คลังระบบตาทิพย์: รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟ"
                        formatted_list = []
                        for user_id_str, data in user_data.items():
                            if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                            nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                            birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                            formatted_list.append(f"<@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})")

                        if not formatted_list:
                            await message.reply("ในขอบเขตนี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับ!")
                            return

                        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
                        view.message = await message.reply(embed=view.create_embed(), view=view)
                        return
                    
                    # กรณีเรียกดูรายชื่อเฉพาะคนในเซิร์ฟเวอร์นั้น ๆ (ไม่ว่าจะเป็นมาสเตอร์หรือสมาชิกทั่วไป)
                    guild = message.guild
                    title_text = f"📊 รายชื่อพรรคพวกในดิส '{guild.name}' ที่ผมจำได้"
                    formatted_list = []
                    
                    for user_id_str, data in user_data.items():
                        if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                        member = guild.get_member(int(user_id_str))
                        if not member: continue
                        
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                        
                        if birthday != "ยังไม่ได้ระบุ":
                            formatted_list.append(f"<@{user_id_str}>: {nickname} (วันเกิด: {birthday})")
                        else:
                            formatted_list.append(f"<@{user_id_str}>: {nickname}")
                    
                    if formatted_list:
                        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
                        view.message = await message.reply(embed=view.create_embed(), view=view)
                    else:
                        await message.reply("ในเซิร์ฟเวอร์นี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับ!")
                    return
            except Exception as e:
                print(f"🚨 ERROR ระบบรายชื่อ: {e}")
                print(traceback.format_exc())
                await message.reply("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อครับ")
                return

    # ==========================================
    # 🔊 [ส่วนที่ 6: ระบบสรุปสถิติห้องเสียง] (เวอร์ชันปรับปรุง)
    # ==========================================
    if "สรุปสถิติห้องเสียง" in lower_content or "ใครคุยนานสุด" in lower_content:
        # 🟢 ทุกบรรทัดด้านล่างนี้ถูกขยับย่อหน้าเข้ามาอยู่ใต้เงื่อนไข if เรียบร้อยแล้วครับ!
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None:
                await message.reply("ขออภัยครับ! คำสั่งสรุปสถิติต้องเรียกดูภายในเซิร์ฟเวอร์หลักเท่านั้นน้า 🛸❌")
                return

            data = load_voice_data()
            today_str = datetime.now().strftime("%Y-%m-%d")

            if not data or data.get("date") != today_str or not data.get("stats"):
                await message.reply("วันนี้ยังไม่มีใครเข้าห้องเสียงเลยครับ!")
                return

            stats = data["stats"]
            guild_id_str = str(message.guild.id)
            
            guild_stats = stats.get(guild_id_str, {})
            filtered_stats = [item for item in guild_stats.items() if int(item[0]) != bot.user.id]
            
            sorted_stats = sorted(filtered_stats, key=lambda x: x[1]['total_time'], reverse=True)[:5]
            
            if not sorted_stats:
                await message.reply("วันนี้ยังไม่มีสถิติของเซิร์ฟเวอร์นี้บันทึกไว้เลยครับ!")
                return
            
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
                report += f"{i}. {display_name}: {time_display}\n"

            await message.reply(report)
            if message.guild.voice_client:
                await bagley_speak(message.guild, f"รายงานผลของวันนี้ครับ อันดับหนึ่งคือคุณ {top_name} คุยนานที่สุดครับ")
            return

    # ==========================================
    # 🔇 [ส่วนที่ 7: ระบบเปิด/ปิดรายงานห้องเสียง - ปรับปรุงความแม่นยำ]
    # ==========================================
    if "รายงานห้องเสียง" in lower_content or "ทักห้องเสียง" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None: 
                await message.reply("คำสั่งตั้งค่าระบบเสียงต้องทำในเซิร์ฟเวอร์กลุ่มเท่านั้นครับ!")
                return

            # สแกนหาคำสั่ง "ปิด"
            if "ปิด" in lower_content:
                state.voice_report_status[message.guild.id] = False
                await message.reply("รับทราบครับ! 🔇 ปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงชั่วคราวแล้วครับ")
                return

            # สแกนหาคำสั่ง "เปิด"
            elif "เปิด" in lower_content:
                state.voice_report_status[message.guild.id] = True
                await message.reply("เปิดระบบคืนชีพ! 🔊 เปิดระบบรายงานห้องเสียงตามปกติแล้วครับ!")
                return

    # ==========================================
    # 🧠 [ส่วนที่ 8: ระบบฝากจำตารางงานผ่าน AI แชท] (ต่อเนียน ๆ คัปพ้ม!)
    # ==========================================
    if "ฝากจำ" in lower_content or "บันทึกตาราง" in lower_content or "ตั้งเตือน" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        # ทำงานเมื่อบอทโดนเรียกชื่อ หรือพิมพ์คุยส่วนตัวใน DM
        if message.guild is None or is_bot_called:
            try:
                # ดึงวันเวลาปัจจุบันฝั่งไทยเพื่อส่งไปให้ AI ช่วยคำนวณวัน
                today_now = datetime.now(bangkok_tz)
                today_str = today_now.strftime("%Y-%m-%d")
                
                prompt = f"""
                วิเคราะห์ข้อความภาษาไทยของผู้ใช้ต่อไปนี้ เพื่อสกัดหาข้อมูล 'วันที่', 'เวลา' และ 'ชื่อกิจกรรม' สำหรับตารางนัดหมาย
                ข้อความผู้ใช้: "{message.content}"
                
                ข้อมูลอ้างอิงเพื่อใช้คำนวณ: วันนี้คือวันที่ {today_str} 
                (คำแนะนำ: หากผู้ใช้พิมพ์ว่า 'พรุ่งนี้' ให้คำนวณบวกไป 1 วันจาก {today_str}, ถ้าพิมพ์ว่า 'มะรืน' ให้บวกไป 2 วัน หรือถ้าใส่แค่ตัวเลขวันที่ดื้อๆ ให้ยึดเดือนและปีปัจจุบัน)
                
                จงตอบกลับเป็นรูปแบบ JSON เท่านั้น ห้ามมีตัวอักษรอธิบายอื่นผสมเด็ดขาดเด็ดขาด! ตามฟอร์แมตนี้:
                {{
                    "date": "YYYY-MM-DD",
                    "time": "ระบุเวลาตามที่ผู้ใช้พิมพ์ เช่น 21:00 น. หรือ 3 ทุ่ม",
                    "event": "ชื่อกิจกรรมสั้นๆ"
                }}
                """
                
                print("🤖 [AI]: แบ็คลี่กำลังแอบแกะข้อความฝากตารางงานให้คุณ...")
                response = await client.aio.models.generate_content(
                    model="chat",
                    contents=prompt,
                )
                
                # แปลงผลลัพธ์ JSON ของ AI กลับมาเป็น Object ฝั่ง Python
                import json
                raw_text = (response.text or "").strip().replace("```json", "").replace("```", "")
                result = json.loads(raw_text)
                
                if result.get("date") and result.get("event"):
                    # 📅 กันเหนียวอีกชั้น: normalize วันที่ที่ AI ส่งกลับมาให้เป็น YYYY-MM-DD จริงๆ เสมอ
                    # (เผื่อ AI ตอบเป็น 'วันนี้'/'พรุ่งนี้' ดิบๆ แทนที่จะคำนวณวันที่ให้ตามที่สั่งในพรอมต์)
                    normalized_date = _normalize_schedule_date(result["date"], today_now)

                    # โหลดและเซฟเข้าสู่ user_memory ผ่านฟังก์ชันเดิมของคุณ
                    user_data = load_user_data()
                    if "schedules" not in user_data:
                        user_data["schedules"] = []
                        
                    new_job = {
                        "id": secrets.token_hex(4),
                        "date": normalized_date,
                        "time": result.get("time", "ไม่ระบุเวลา"),
                        "owner_id": message.author.id,
                        "event": result["event"]
                    }
                    user_data["schedules"].append(new_job)
                    save_user_data(user_data)
                    
                    await message.reply(
                        f"🛸 ล็อกเป้าลงปฏิทินเรียบร้อยคัป!\n"
                        f"📌 กิจกรรม: **{result['event']}**\n"
                        f"📅 วันที่: **{normalized_date}**\n"
                        f"⏰ เวลา: **{result['time']}**\n"
                        f"เดี๋ยวพอถึงวัน แบ็คลี่บินตามเข้าห้องเสียงเมื่อไหร่ จะเปิดไมค์เตือนให้ทันทีเลยคัปพ้ม! 🫡"
                    )
                else:
                    await message.reply("❌ โถ่ แบ็คลี่อ่านประโยคนี้แล้วแกะวันที่หรือกิจกรรมไม่ชัดเจน รบกวนพิมพ์บอก วันที่ เวลา และชื่องานให้ชัดขึ้นอีกนิดน้าคัป")
                    
            except Exception as e:
                print(f"❌ AI แกะแชทฝากงานพัง: {e}")
                await message.reply("❌ แบ็คลี่มึนตึ้บ ระบบสมองกลฝากตารางงานผ่านแชทแอบงอแงชั่วคราวคัปพ้ม!")
            return

    # ==========================================
    #  คำสั่งดีเทคคำ (fallback): แบ็คลี่ เรียก @เพื่อน (ส่งเข้า DM ส่วนตัว)
    # ------------------------------------------
    # 🔗 คนละความสามารถกับ "ชวน" ด้านล่าง (ซึ่งบอทวาร์ปเข้าห้องเสียงไปตื๊อเอง) โดยเจตนา
    # "เรียก" แค่ส่ง DM มีปุ่มตอบรับ/ปฏิเสธ + ลิงก์ห้องเสียงให้กดเอง บอทไม่วาร์ปตามไปหา
    # เพื่อให้ AI Command Router แยกสองความสามารถนี้ออกจากกันได้แม่นยำขึ้น ตอนนี้ทั้งคู่
    # ถูกแยกเป็นฟังก์ชันกลางคนละตัว (execute_dm_call / execute_warp_invite) และมีคำสั่ง
    # slash แยกกันคนละตัว (/call_member กับ /invite_voice) ที่คำอธิบายเขียนแยกความต่างไว้
    # ชัดเจน ให้ AI เลือกเรียกฟังก์ชันที่ตรงกับเจตนาจริงๆ ของผู้ใช้
    # ==========================================
    if "เรียก" in lower_content and is_message_addressed_to_bagley(lower_content):
        target_user, _ = resolve_target_member(
            message,
            remove_keywords=["แบ็คลี่", "bagley", "คุณ", "หน่อย", "เรียก"]
        )

        if target_user:
            ctx = await bot.get_context(message)
            await execute_dm_call(ctx, message.author, target_user)
            return

    # ==========================================
    #  คำสั่งดีเทคคำ (fallback): แบ็คลี่ ชวน @เพื่อน หน่อย (วาร์ปไปตื๊อในห้องเสียง)
    # ------------------------------------------
    # 🔗 คนละความสามารถกับ "เรียก" ด้านบน (ซึ่งแค่ส่ง DM ไม่วาร์ปตามไปหา) โดยเจตนา
    # เรียกใช้ execute_warp_invite() ตัวเดียวกับที่ /invite_voice และ AI Command Router
    # ใช้ (มีล็อกกันวาร์ปซ้ำในตัวแล้ว) แทนการ reimplement ลอจิกซ้ำเองในนี้
    # ==========================================
    if "ชวน" in lower_content and "หน่อย" in lower_content and ("แบ็คลี่" in lower_content or "bagley" in lower_content):
        if message.guild is None:
            await message.reply("คำสั่งนี้ต้องใช้ในห้องแชทของเซิร์ฟเวอร์เท่านั้นครับ!")
            return

        # 👥 ดึงคนสั่ง และคนที่จะให้ไปชวน
        host_member = message.author
        target_member, _ = resolve_target_member(
            message,
            remove_keywords=["แบ็คลี่", "bagley", "ชวน", "คุณ", "หน่อย"]
        )
        target_guild_for_invite = message.guild

        # 🆕 [ข้ามเซิร์ฟ] ถ้าหาไม่เจอในเซิร์ฟนี้ ลองค้นข้ามทุกเซิร์ฟที่บอทอยู่ด้วย (เฉพาะระบบ "ชวน"
        # เท่านั้น เพราะแค่วาร์ปไปพูดตื๊อ ไม่ใช่คำสั่งจัดการสมาชิกที่กระทบสิทธิ์)
        if not target_member:
            raw_name_match = regex_lib.sub(
                r"(แบ็คลี่|bagley|ชวน|คุณ|หน่อย)", "", message.content, flags=regex_lib.IGNORECASE
            ).strip()
            if raw_name_match:
                cross_member = find_voice_member_across_guilds(
                    raw_name_match, exclude_ids={bot.user.id, host_member.id}
                )
                if cross_member:
                    target_member = cross_member
                    target_guild_for_invite = cross_member.guild

        if not target_member:
            await message.reply("❌ คุณต้องพิมพ์ชื่อเพื่อนหรือแท็ก @ชื่อเพื่อนที่จะให้ผมไปชวนด้วยสิคัปพ้ม เช่น `แบ็คลี่ ชวน ชื่อเพื่อน หน่อย` น้า")
            return

        ctx = await bot.get_context(message)
        await execute_warp_invite(ctx, host_member, target_member, target_guild=target_guild_for_invite)
        return

    # ==========================================
    # ⚡🔄🔇🛡️🎵🗣️ [ส่วนที่ 8-13 เดิม: คำสั่งจัดการห้องเสียง/กลุ่ม/ปาร์ตี้/mute-deaf/
    #   สแกนโปรไฟล์/มิวสิกบอท/YT check/ล่าม-TTS/diagnostic ผ่าน keyword]
    #
    # 🤖 [ย้ายไปใช้ AI Command Router แทนแล้ว — ดู 'ด่านที่ 5' ด้านบนของ on_message]
    # บล็อกนี้เคย reimplement คำสั่งซ้ำกับ /kick_voice /move /group_move /create_party
    # /mute_sleep /unmute_me /unmute_member /deaf_work /undeaf_me /undeaf_member
    # /profile_scan /shutdown /sync /forget /guard_room /join /play /skip /queue /stop
    # /leave /yt_check /gather /tts /diagnostic ด้วย if/elif keyword matching เอง
    # ตอนนี้ AI Router (ai_command_router.py) สแกนคำสั่งเหล่านี้อัตโนมัติจาก bot.commands
    # และให้ AI function calling ตีความเจตนา + ดึงพารามิเตอร์ให้แทน จึงลบโค้ดซ้ำออก
    # ถ้าต้องการดูโค้ดเดิมอ้างอิง ดูจาก git history / ไฟล์ backup ก่อนแก้ไขนี้
    # ==========================================
# ==========================================
# 📸 [ส่วนที่ 10: ระบบสแกนรูปภาพด้วยสมองกล AI]
# ==========================================
    if any(keyword in message.content for keyword in ["ภาพอะไร", "รูปอะไร", "ดูรูปนี้หน่อย"]) or message.attachments:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if message.guild and not any(keyword in lower_content for keyword in bot_keywords):
            pass # ถ้าอยู่ในเซิร์ฟเวอร์แล้วไม่ได้เรียกชื่อบอท จะปล่อยผ่านไปเช็คคำสั่งอื่นด้านล่าง
        else:
            has_image = False
            target_message = message

            if message.attachments:
                if any(message.attachments[0].filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                    has_image = True
            elif message.reference:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    if replied_msg.attachments and any(replied_msg.attachments[0].filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                        has_image = True
                        target_message = replied_msg
                except:
                    pass

            if has_image:
                is_dm = isinstance(message.channel, discord.DMChannel)
                user_msg_clean = message.content.strip()

                if is_dm and not user_msg_clean:
                    await message.channel.send(say("image_ask_what"))
                    return

                await message.channel.send(say("image_analyzing"))
                
                if message.guild:
                    try:
                        await bagley_speak(message.guild, say("image_analyzing"))
                    except Exception as tts_start_err:
                        print(f"TTS Start Error: {tts_start_err}")

                try:
                    image_url = target_message.attachments[0].url
                    user_question = user_msg_clean if user_msg_clean else "ช่วยอธิบายรูปภาพนี้ให้ฟังหน่อยครับ"
                    
                    author_id = message.author.id

                    prompt = f"""
{persona.CORE}
งานนี้: อธิบาย/วิเคราะห์สิ่งที่เห็นในรูปจริงๆ ห้ามมโนสิ่งที่ไม่มีในรูป ตอบสั้นถ้าไม่ได้ถามละเอียด

ข้อมูลบุคคลที่คุณกำลังวิเคราะห์รูปภาพให้ในตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {get_realtime_name(message.author.id, message.author.display_name)}
- สถานะสำคัญ: สมาชิกในเซิร์ฟเวอร์

โจทย์: จงวิเคราะห์รูปภาพที่แนบมานี้ และตอบคำถามของคุณอย่างชาญฉลาด ช่างสังเกต แฝงอารมณ์ขันและมีความกวนโอ๊ยอย่างมีระดับ
คำถามจากคุณ: {user_question}
"""
                    img_bytes = await http_get_bytes(image_url)
                    img = Image.open(io.BytesIO(img_bytes))
                    
                    response = await client.aio.models.generate_content(
                        model="chat", 
                        contents=[prompt, img]
                    )
                    ai_text = (response.text or "").strip()
                    
                    if not ai_text:
                        ai_text = f"หึๆ ภาพนี้มองปุ๊บก็รู้ปั๊บเลยครับ! แต่ระบบส่งข้อมูลผมมันเอ๋อนิดหน่อย สรุปมันคือภาพที่ดีครับ! 🤠✨"

                    # 🖼️ [ใหม่] จำสิ่งที่วิเคราะห์ได้จากรูปนี้ไว้ ผูกกับ message.id ของ "ข้อความที่มีรูปจริงๆ"
                    # (target_message อาจเป็นข้อความที่ถูกตอบกลับมา ไม่ใช่ message ปัจจุบันเสมอไป) เพื่อให้ระบบ
                    # Free Chat ทั่วไปดึงไปใช้ต่อได้ทีหลัง ถ้ารูปนี้ยังอยู่ใน 10 ข้อความล่าสุดของห้องตอนนั้น
                    _remember_image_caption(target_message.id, ai_text[:300])
                        
                    await message.channel.send(ai_text)
                    
                    if message.guild:
                        try:
                            await bagley_speak(message.guild, ai_text)
                        except Exception as tts_err:
                            print(f"TTS Error: {tts_err}")
                    return

                except Exception as e:
                    await message.channel.send(f"โอ๊ะ มีข้อผิดพลาดในการส่งภาพให้สมองวิเคราะห์ครับ: {e}")
                    return
                
    lower_content = message.content.lower()
    bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]

    # ==========================================
    # 🎨 ระบบวาดรูปภาพ
    # ==========================================
    if any(keyword in message.content for keyword in ["วาดรูป", "เจนภาพ", "วาดภาพ"]):
        # ถ้าอยู่ในเซิร์ฟเวอร์ แล้วไม่ได้เรียกชื่อบอท จะปล่อยผ่านไปเช็คคำสั่งอื่นด้านล่าง
        if message.guild and not any(keyword in lower_content for keyword in bot_keywords):
            pass 
        else:
            user_msg_clean = message.content
            
            # 🧹 1. เคลียร์คำสั่งแบบคอมโบสำหรับในกลุ่ม (ชื่อบอท + คีย์เวิร์ด)
            for kw in ["แบ็คลี่ วาดรูป", "แบ็คลี่ เจนภาพ", "แบ็คลี่ วาดภาพ", "bagley วาดรูป", "bagley เจนภาพ", "bagley วาดภาพ"]:
                user_msg_clean = user_msg_clean.replace(kw, "")
            
            # 🧹 2. เคลียร์คีย์เวิร์ดเดี่ยวๆ สำหรับใน DM
            for kw in ["วาดรูป", "เจนภาพ", "วาดภาพ"]:
                user_msg_clean = user_msg_clean.replace(kw, "")
                
            # 🧹 3. เคลียร์ชื่อบอทโดดๆ
            for kw in bot_keywords:
                user_msg_clean = user_msg_clean.replace(kw, "")
                
            prompt = user_msg_clean.strip()

            # 🚨 ตรวจสอบกรณีพิมพ์แค่คำสั่ง แต่ไม่มีข้อความบรีฟต่อท้าย
            if not prompt:
                await message.reply("คุณต้องสั่งด้วยน้าว่าอยากให้วาดรูปอะไร เช่น `วาดรูป แมวอ้วนกินพิซซ่า` ครับ! 🍕")
                return

            # 🎨 ส่งข้อมูลไปให้ฟังก์ชันกลางเสกภาพทำงานทันที
            await generate_and_send_image(message, prompt)
            return

    # ==========================================
    # ส่วนที่ 11: ระบบจดจำข้อมูลส่วนตัว/วันเกิด
    # 🔧 [ปรับปรุง] เดิมบล็อกนี้ดักคำว่า "จำไว้ว่า" ตรงๆ แล้วยิงเข้า execute_remember_logic ทันที
    # ทำให้ข้อความอย่าง "จำไว้ว่าห้ามพูดคำหยาบ" หรือ "จำไว้ว่าพรุ่งนี้มีสอบ" ถูกเข้าใจผิดเป็นการบันทึก
    # ชื่อเล่นไปหมด ตอนนี้ข้อความที่เอ่ยถึงแบ็คลี่ตรงๆ ("จำไว้ว่า...") จะถูกดักจับ + แยกหมวดหมู่ (AI)
    # ตั้งแต่ต้นทางที่ bagley_rules.maybe_learn_from_message() แล้ว (ดูใกล้ต้น on_message) — ถ้าเป็น
    # เคสข้อมูลส่วนตัวจริงๆ จะเรียก execute_remember_logic ให้ตรงนั้นเลย จึงไม่ต้องมีบล็อกซ้ำตรงนี้อีก
    # ==========================================

    # ==========================================
    # 🌐 [ส่วนที่ 12: ระบบแปลภาษาคู่ขนาน และ ระบบแชทอัจฉริยะ]
    # ==========================================
    # ดักจับคำสั่งแปลภาษาหลัก ๆ จากทั่วโลก (ไทย, อังกฤษ, เกาหลี, จีน, ญี่ปุ่น)
    translation_keywords = ["แปล", "translate", "주세요", "번역", "翻", "翻訳"]
    
    if any(word in lower_content for word in translation_keywords):
        is_dm = message.guild is None
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_mentioned = any(keyword in lower_content for keyword in bot_keywords)
        
        if not is_dm and not is_mentioned:
            pass 
        else:
            if message.reference:
                try:
                    referenced_msg = await message.channel.fetch_message(message.reference.message_id)
                    text_to_translate = referenced_msg.content
                    user_request = message.content

                    prompt = (
                        "You are Bagley, an expert multilingual translator assistant.\n"
                        "Your task is to translate the text inside 'Text to Translate' based on the user's input.\n\n"
                        "INSTRUCTIONS:\n"
                        "1. Analyze the 'User Request' to detect what language the user is speaking or requesting (e.g., 'แปลหน่อย' -> Thai, 'translate' -> English, '주세요' or '번역' -> Korean, '翻訳' -> Japanese, '翻' -> Chinese).\n"
                        "2. Translate the entire 'Text to Translate' into that detected target language so the requester can understand it completely.\n"
                        "3. Respond with ONLY the final translated text. Do not add any introductory phrases, quotes, or explanations.\n\n"
                        f"User Request: {user_request}\n"
                        f"Text to Translate: {text_to_translate}"
                    )

                    response = await client.aio.models.generate_content(
                        model="chat",
                        contents=prompt
                    )
                    answer = response.text
                    
                    await message.reply(f"🌐 **Translation Result:**\n{answer}")
                    return
                    
                except discord.NotFound:
                    print("❌ [Bagley] ไม่พบข้อความที่อ้างอิงถึง อาจถูกลบไปแล้ว")
                except Exception as e:
                    print(f"❌ [Bagley] เกิดข้อผิดพลาดในระบบแปลภาษาคู่ขนาน: {e}")

    # 💾 [ระบบตรวจสอบความจำที่เคยถูกสอน (Teach Memory) / คุยเล่น Free Chat] ───
    is_sqlite_triggered = False

    if message.guild is not None:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        # 🌟 [ปรับปรุง]: ถ้ามาจาก Webhook เสียงของคุณชะอม ให้เปิดระบบดักความจำทันทีโดยไม่ต้องง้อคีย์เวิร์ด
        if is_from_my_webhook or any(keyword in lower_content for keyword in bot_keywords):
            is_sqlite_triggered = True
    else:
        is_sqlite_triggered = True

    matched_response = None

    if is_sqlite_triggered:
        cursor.execute("SELECT keyword, response FROM teach_memory")
        all_teachings = cursor.fetchall()
        for keyword, response_text in all_teachings:
            if keyword in lower_content:
                matched_response = response_text
                break

    # ==========================================
    # 🔥 [ส่วนที่ A: จัดการคำสอนดึงจาก Database]
    # ==========================================
    if matched_response:
        if message.guild is not None:
            await message.reply(say("loading"), delete_after=2.0)

        async with message.channel.typing():
            try:
                author_id = message.author.id

                bagley_prompt = f"""
{persona.BRIEF}
งานนี้: นำ 'ข้อความดิบ' ที่ได้รับไปเรียบเรียงใหม่ในสไตล์การพูดของคุณ โดยห้ามบิดเบือนหรือเปลี่ยนความหมายเดิม ตอบสั้นกระชับ

ข้อมูลบุคคลที่คุณกำลังคุยด้วยตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {get_realtime_name(message.author.id, message.author.display_name)}

โจทย์: จงนำเนื้อหาข้อความดิบนี้: '{matched_response}' มาเรียบเรียงใหม่ให้เป็นคำพูดสไตล์กวนโอ๊ยอย่างมีระดับตามแบบฉบับของคุณครับ!
"""
                response = await client.aio.models.generate_content(
                    model="chat",
                    contents=bagley_prompt
                )
                bagley_styled_text = (response.text or "").strip()
                if not bagley_styled_text:
                    bagley_styled_text = f"หึๆ เรื่องนี้คุณเคยสอนผมไว้ในคลังสมองแล้วนี่นา! คำตอบคือ: {matched_response} ครับ! 🤠✨"
            except Exception as e:
                print(f"🚨 Teach AI DM/Guild Error: {e}")
                bagley_styled_text = f"ฮั่นแน่! เรื่องนี้คุณเคยสอนผมไว้ในสมองกลแล้ว! ตอบเลยว่า: {matched_response} ครับ! 🤠"

            await message.reply(bagley_styled_text)
            
            # 🗣️ ระบบส่งเสียงพูดสำหรับข้อความที่ดึงมาจากฐานข้อมูลความจำ
            # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
            if message.guild and message.guild.voice_client:
                try:
                    clean_voice_text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', bagley_styled_text)
                    await bagley_speak(message.guild, clean_voice_text)
                except Exception as tts_err:
                    print(f"🚨 Teach Memory TTS Error: {tts_err}")
        return

    # ==========================================
    # 💬 [ส่วนที่ B: ระบบคุยเล่น Free Chat ทั่วไป]
    # ==========================================
    user_question = message.content.lower().replace("แบ็คลี่", "").replace("bagley", "").strip()
    user_question = user_question.replace(f'<@{bot.user.id}>', '').strip()

    is_bot_called = False
    if message.guild is not None:
        # 🌟 [ปรับปรุง]: ถ้าเป็น Webhook ของชะอม หรือมีการเรียกชื่อบอท ให้เปิดสวิตช์คุยเล่นทันทีคัป!
        if (
            is_from_my_webhook
            or any(k in lower_content for k in ["แบ็คลี่", "bagley"])
            or bot.user.mentioned_in(message)
            # 💬 ถ้าเป็นการตอบกลับ (reply) ข้อความใดๆ ของแบ็คลี่ก่อนหน้า (ทั้งทักขึ้นเอง และตอบใครไว้ก่อน)
            # ให้ถือว่าถูกเรียกด้วย ไม่ต้องพิมพ์ชื่อแบ็คลี่ในข้อความที่ reply มาเลย เหมือนพฤติกรรมใน DM
            # จะได้รับรู้และตอบกลับได้เลย (ระบบข้างล่างจะพูดออกเสียงให้เองอยู่แล้วถ้าบอทอยู่ในห้องเสียง)
            or await is_reply_to_bagley_message(message)
        ):
            is_bot_called = True

    if message.guild is None or is_bot_called:
        # 🌟 [ปรับปรุง]: เพิ่ม 'and not is_from_my_webhook' ตรงนี้ เพื่อไม่ให้บอทส่งข้อความถามซ้ำเวลาระบบเสียงส่งมาเป็นคำสั้น ๆ
        if message.guild is not None and not user_question and not is_from_my_webhook:
            await message.reply(say("name_only_call"), delete_after=5.0)
            return

        if message.guild is not None:
            await message.reply(say("loading"), delete_after=2.0)

        async with message.channel.typing():
            try:
                messages = []
                # 📅 [แก้บั๊ก] ถ้าข้อความในประวัติเป็นของ "เมื่อวาน" หรือก่อนหน้า (คนละวันกับข้อความ
                # ปัจจุบัน ตามเวลาไทย) ไม่นับรวมเข้า "10 ข้อความล่าสุด" — history() คืนข้อความจากใหม่ไปเก่า
                # เรียงตามเวลา ดังนั้นพอเจอข้อความที่ข้ามวันไปแล้วก็หยุดดึงต่อได้เลย (ที่เหลือเก่ากว่านี้ทั้งหมด)
                # กันไม่ให้ AI เอาบทสนทนาของวันก่อนมาปนกับวันนี้ จนสับสนว่า "วันนี้"/"เมื่อวาน" คือวันไหนกันแน่
                today_bkk = message.created_at.astimezone(bangkok_tz).date()
                async for msg in message.channel.history(limit=30):
                    if msg.created_at.astimezone(bangkok_tz).date() != today_bkk:
                        break
                    messages.append(msg)
                    if len(messages) >= 10:
                        break
                messages.reverse()
                
                chat_log = ""
                for msg in messages:
                    # 🎙️ [แก้บั๊ก] กันไม่ให้ข้อความปัจจุบันซ้ำ ถ้าดันติดมาใน history() แล้ว (กรณีพิมพ์ปกติ)
                    # เพราะด้านล่างเราจะเติมข้อความปัจจุบันต่อท้ายเองอยู่แล้วเสมอ
                    if msg.id == message.id:
                        continue

                    speaker = "แบ็คลี่" if msg.author.id == bot.user.id else get_realtime_name(msg.author.id, msg.author.display_name)

                    # 🖼️ [ใหม่] ถ้าข้อความนี้มีรูปภาพแนบมาด้วย ให้แนบคำบรรยายรูปเข้าไปในบรรทัดนี้ด้วย
                    # เอาจากแคชก่อน (ถ้าเคยวิเคราะห์ไว้แล้วจากระบบแคปชั่นเงียบๆ หรือระบบสแกนรูปเต็มรูปแบบ)
                    # ถ้ายังไม่เคยมี ให้แคปสดตอนนี้เลย (จำกัดแค่ 10 ข้อความล่าสุด ไม่หนักเกินไป) แล้วเก็บแคชไว้
                    # ด้วย เพื่อให้ Free Chat "จำ" รูปที่คนส่งไปก่อนหน้าได้ ไม่ใช่แค่ระบบชวนคุยเองเท่านั้น
                    image_note = ""
                    img_attachment = next(
                        (a for a in msg.attachments if a.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))),
                        None,
                    )
                    if img_attachment:
                        caption = _get_cached_image_caption(msg.id)
                        if caption is None:
                            caption = await get_quick_image_caption(img_attachment.url)
                            _remember_image_caption(msg.id, caption)
                        if caption:
                            image_note = f" [แนบรูปภาพมาด้วย — ในรูปคือ: {caption}]"

                    if msg.content.strip() or image_note:
                        chat_log += f"[{speaker}]: {msg.clean_content}{image_note}\n"

                # 🎙️ [แก้บั๊ก] เติมข้อความปัจจุบันต่อท้าย chat_log เองเสมอ แทนที่จะพึ่งพา
                # message.channel.history() อย่างเดียว เพราะคำสั่งเสียงที่มาจาก Voice Relay
                # (VoiceRelayMessage) ไม่ใช่ข้อความจริงที่เคยถูกโพสต์ลง Discord เลยไม่ติดมาใน
                # history() ทำให้ AI มองไม่เห็นว่าคุณเพิ่งพูดอะไร แล้วดันไปหยิบหัวข้อเก่าจาก
                # ประวัติแชทข้างบนมาตอบแทน (บั๊กนี้เกิดเฉพาะตอนใช้เสียง เพราะตอนพิมพ์ข้อความ
                # จะถูกบันทึกลง Discord ก่อน on_message ทำงาน จึงติดมาใน history() อยู่แล้ว)
                chat_log += f"[{get_realtime_name(message.author.id, message.author.display_name)}]: {message.clean_content}\n"

                author_id = message.author.id

                # 🧠 ความจำระยะยาว + อารมณ์ + ความสนิท (ทั้งหมดไม่เรียก AI เพิ่ม ยกเว้นรอผลเรียนรู้ที่รันขนานอยู่)
                _just_learned = []
                if _learn_task is not None:
                    try:
                        _just_learned = await asyncio.wait_for(asyncio.shield(_learn_task), timeout=3.0) or []
                    except Exception:
                        _just_learned = []
                _gid = message.guild.id if message.guild else None
                _speaker_name = get_realtime_name(message.author.id, message.author.display_name)
                _memory_block = bagley_knowledge.build_memory_block(
                    speaker_id=message.author.id, speaker_name=_speaker_name, guild_id=_gid,
                    query=user_question,
                    mentioned_ids=[m.id for m in message.mentions if not m.bot],
                    just_learned=_just_learned,
                )
                _extra = _memory_block + humanize.familiarity_block(message.author.id, _gid) + humanize.mood_block(_gid)

                free_chat_prompt = persona.chat_prompt(
                    speaker=f"คุณ {_speaker_name}",
                    chat_log=chat_log,
                    rules_block=bagley_rules.format_rules_for_prompt(),
                    activities=_describe_member_activities(message.guild),
                    extra=_extra,
                )
                _t0 = _time.time()
                response = await client.ask(free_chat_prompt, tier="chat", temperature=0.9, effort="low", max_tokens=900)
                bagley_styled_text = (response.text or "").strip()
                # ⏱️ หน่วงจังหวะให้เหมือนคนพิมพ์ (ถ้าโมเดลตอบเร็วเกินไป) อยู่ใน typing indicator เดิม
                await humanize.pace(_t0, bagley_styled_text)
                if not bagley_styled_text:
                    bagley_styled_text = say("chat_empty")

            except Exception as e:
                print(f"🚨 Free Chat AI Error: {e}")
                bagley_styled_text = say("ai_down")

            await message.reply(bagley_styled_text)
            
            # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
            if message.guild and message.guild.voice_client:
                clean_voice_text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', bagley_styled_text)
                await bagley_speak(message.guild, clean_voice_text)
        return

    # ==========================================
    # 🗣️ [ส่วนที่ 13: ระบบอ่านแชทคนในห้องเสียง (ล่าม TTS)]
    # ==========================================
    if state.is_tts_enabled and not state.is_playing_music and not message.content.startswith('!'):
        if message.guild and message.author.voice:
            vc = message.guild.voice_client
            
            if vc and vc.channel == message.author.voice.channel:
                if not vc.is_playing():
                    text = message.clean_content.strip()
                    if text:
                        try:
                            _tts_path = await tts_synth(clean_for_speech(text), voice="th-TH-PremwadeeNeural")
                            if not vc.is_playing():
                                vc.play(discord.FFmpegPCMAudio(_tts_path, executable=FFMPEG_PATH))
                        except: 
                            pass

    await bot.process_commands(message)
