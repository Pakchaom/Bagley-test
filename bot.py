# --- Discord & Utilities ---
import discord
from discord.ext import commands
from discord import ui
import subprocess
import os
import sys
import io
import sqlite3
import asyncio
from dotenv import load_dotenv
from discord import app_commands
from datetime import datetime, timedelta, time as dt_time, timezone
import zoneinfo
from typing import Union, Optional
import json
import time
import secrets
import collections
import urllib.parse
import difflib

# --- Google Gen AI ---
from google import genai
from google.genai import types as genai_types
from PIL import Image

# --- AI Command Router (ให้ AI ตัดสินใจว่าข้อความควรเรียกคำสั่งไหน) ---
from ai_command_router import ai_route_and_execute

# --- Voice & Media ---
from gtts import gTTS
import edge_tts
import yt_dlp
import requests
import aiohttp
from aiohttp import web
from discord.ext import tasks
import random
import re as regex_lib
import traceback

# --- RAM Cleaner ---
import gc
import psutil

is_moving_group = False

conn = sqlite3.connect('bagley_memory.db', check_same_thread=False)

voice_action_cooldowns = {}

song_queue = []

user_join_times = {}

voice_report_status = {}
# 🔒 ล็อกสำหรับกันไม่ให้แบ็คลี่พูด 2 ประโยคทับกันตอนมีคนเข้าห้องพร้อมกัน
# (ป้องกัน race condition ที่ 2 event ยิงมาพร้อมกันแล้วเช็ค is_playing() ไม่ทัน)
voice_speak_locks = {}

def _get_voice_speak_lock(guild_id):
    if guild_id not in voice_speak_locks:
        voice_speak_locks[guild_id] = asyncio.Lock()
    return voice_speak_locks[guild_id]

reported_guilds_today = {}

last_party_invites = {}

bot_follow_targets = {}

created_party_channels = []

guard_room_status = {}

bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")

last_gaming_warnings = {}

active_kick_tasks = {}

room_guard_status = {}

is_playing_music = False

is_tts_enabled = False

is_webhook_enabled = True

is_webhook_enabled = True

# ID Discord ของ Owner
OWNER_DISCORD_ID = 1133740216822267954  

# รายชื่อผู้มีสิทธิ์สั่ง Shut Down คอมพิวเตอร์ได้
ALLOWED_SHUTDOWN_USERS = [
    1133740216822267954,  # ชะอม
    856568101919653918    # ชาช่า
]

# รายชื่อผู้มีสิทธิ์สั่ง Teach แบ็คลี่ได้
ALLOWED_TEACH_USERS = [
    1133740216822267954,  # ชะอม
    856568101919653918,    # ชาช่า
    732953446172327956,    # คุณบอล
    1073827310026903612    # ลุงกร
]

ALLOWED_USERS = [1133740216822267954, 856568101919653918] # ชะอมกับชาช่า
auto_follow_status = {uid: True for uid in ALLOWED_USERS}
last_greeting_dates = {}

last_reminder_dates = {}
pending_exit_after_music = {}

active_alarms = {}

LOG_BUFFER = collections.deque(maxlen=10)
ORIGINAL_PRINT = print

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    LOG_BUFFER.append(message)
    ORIGINAL_PRINT(message, **kwargs)

# เก็บข้อความล่าสุดของแต่ละคนเพื่อตรวจจับสแปม
spam_check = {} 
SPAM_THRESHOLD = 3  # พิมพ์ซ้ำครั้งที่ 3 เป็นต้นไปจะถูกลบ

blocked_users = {}

# คำหยาบขั้นต้นไว้กรองก่อนยิงไปให้ AI ช่วยตัดสิน (ลดการเรียก AI โดยไม่จำเป็น)
RUDE_WORD_PATTERNS = [
    "เหี้ย", "สัส", "สัตว์", "ควย", "เย็ด", "แม่ง", "แม่มึง", "พ่อมึง", "ห่า", "ไอ้สัส",
    "ไอ้เหี้ย", "ไอ้ควย", "มึงโง่", "ตอแหล", "ชิบหาย", "อีดอก", "อีสัส", "กระหรี่",
    "fuck", "shit", "bitch", "asshole", "stupid bot", "dumb bot", "retard"
]

def _bagley_get_next_midnight_bkk():
    now = datetime.now(bangkok_tz)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

def is_user_blocked(user_id: str) -> bool:
    """เช็กว่า user_id นี้โดนแบนคำสั่งของแบ็คลี่อยู่หรือไม่ (ปลดอัตโนมัติเมื่อพ้นเที่ยงคืน)"""
    block_until = blocked_users.get(user_id)
    if block_until is None:
        return False
    if datetime.now(bangkok_tz) >= block_until:
        del blocked_users[user_id]
        return False
    return True

def block_user_for_today(user_id: str):
    """แบนคำสั่ง/การตอบกลับของ user_id นี้ไปจนถึงเที่ยงคืน (เวลาไทย)"""
    blocked_users[user_id] = _bagley_get_next_midnight_bkk()

def is_message_addressed_to_bagley(lower_text: str) -> bool:
    """เช็กว่าข้อความนี้เอ่ยถึง/เรียกแบ็คลี่ตรงๆ หรือไม่"""
    mention_tag = f"<@{bot.user.id}>" if bot.user else None
    return (
        "แบ็คลี่" in lower_text
        or "bagley" in lower_text
        or (mention_tag is not None and mention_tag in lower_text)
    )

def has_potential_profanity(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in RUDE_WORD_PATTERNS)

async def ai_detect_insult_to_bagley(message_text: str) -> bool:
    """ให้ AI ช่วยตัดสินว่าข้อความนี้เป็นการด่า/หยาบคายที่มุ่งเป้ามาที่แบ็คลี่โดยตรงหรือไม่"""
    try:
        prompt = (
            "ข้อความต่อไปนี้มาจากผู้ใช้ใน Discord ที่กำลังพูดถึงหรือเรียกบอทชื่อ \"แบ็คลี่\" ในข้อความเดียวกัน\n"
            f'ข้อความ: "{message_text}"\n\n'
            "หน้าที่ของคุณ: พิจารณาว่าข้อความนี้เป็นการด่าทอ/หยาบคาย/ดูหมิ่น ที่มุ่งเป้ามาที่แบ็คลี่โดยตรง "
            "(ไม่ใช่แค่พูดคำหยาบทั่วไปที่ไม่ได้เจาะจงใส่บอท) หรือไม่\n"
            "ตอบกลับมาเพียงคำเดียวเท่านั้น: YES ถ้าใช่ หรือ NO ถ้าไม่ใช่ ห้ามอธิบายเพิ่มเติมใดๆ ทั้งสิ้น"
        )
        response = await client.aio.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt
        )
        result_text = (getattr(response, "text", "") or "").strip().upper()
        return result_text.startswith("YES")
    except Exception as e:
        print(f"⚠️ [ระบบตรวจคำหยาบ] AI ตรวจจับพลาด: {e}")
        return False

# --- โหลดค่า Config ---
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
YT_API_KEY = os.getenv('YT_API_KEY')
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"), http_options={'api_version': 'v1alpha'})

def save_settings(data):
    with open('server_settings.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_settings():
    # This is for testing
    try:
        with open('server_settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_data(data):
    with open('user_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_user_data():
    try:
        with open('user_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def make_gradle_bar(percent: int, status_text: str, start_time: float) -> str:
    total_blocks = 15
    filled_blocks = int((percent / 100) * total_blocks)
    empty_blocks = total_blocks - filled_blocks
    
    bar_str = f"<{FillGreen(filled_blocks)}{FillDash(empty_blocks)}>"
    
    elapsed_time = int(time.time() - start_time)
    
    return f"""```text
{bar_str} {percent}% {status_text} [{elapsed_time}s]
```"""

def FillGreen(count):
    return "=" * count if count > 0 else ""

def FillDash(count):
    return "-" * count if count > 0 else ""
    
#  ฟังก์ชันกลางสำหรับลบข้อมูล (ทำหน้าที่ลบอย่างเดียว)
def เคลียร์ข้อมูลพรรคพวก(user_id: str):
    data_memory = load_user_data()
    if user_id in data_memory:
        del data_memory[user_id]
        save_user_data(data_memory)
        return True
    return False

def load_voice_data():
    file_path = 'voice_stats.json'
    # 🛠️ หากหาไฟล์ไม่เจอในคอมบริษัท ให้สร้างไฟล์ปีกกาเปล่า {} ขึ้นมาทันทีคัปพ้ม
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"❌ ไม่สามารถสร้างไฟล์ voice_stats.json ชั่วคราวได้: {e}")
        return {}
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # 🛡️ ดักจับกรณีโครงสร้างไฟล์ JSON พัง (ป้องกันบั๊ก Extra data) ให้รีเซ็ตกลับเป็นไฟล์เปล่าทันที
        print("⚠️ โครงสร้างไฟล์ voice_stats.json พัง/ซ้อนกัน! กำลังทำการล้างเป็นไฟล์เริ่มต้น...")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        except:
            pass
        return {}
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดอื่นในการอ่านไฟล์: {e}")
        return {}

def save_voice_data(data):
    try:
        # บันทึกไฟล์ข้อมูลอย่างปลอดภัยแบบเคลียร์ของเดิมทิ้งก่อนเขียนใหม่คัป
        with open('voice_stats.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ ไม่สามารถบันทึกข้อมูลลง voice_stats.json ได้: {e}")

def _get_saved_voice_name(member):
    """คืนชื่อที่ควรใช้บันทึก/เรียกในสถิติห้องเสียง (เอาฉายาที่บันทึกไว้ก่อน ถ้าไม่มีก็ใช้ชื่อในเซิร์ฟเวอร์)"""
    data_memory = load_user_data()
    special_info = data_memory.get(str(member.id))
    if special_info and isinstance(special_info, dict):
        saved_name = special_info.get("nickname", member.display_name)
    elif special_info:
        saved_name = special_info
    else:
        saved_name = member.display_name
    if saved_name == "ยังไม่ระบุ":
        saved_name = member.display_name
    return saved_name

def _register_voice_entry(member):
    """บันทึกทันทีว่าสมาชิกคนนี้แวะเข้าห้องเสียงวันนี้แล้ว (แม้ยังไม่ออกจากห้องก็ให้ขึ้นชื่อในรายงาน
    'ใครเข้าห้องเสียงบ้าง' ได้เลย) โดยจะจำเวลาที่เข้าห้องครั้งแรกของวันนั้นไว้ด้วย (first_join)
    ไม่ได้แตะ total_time ตรงนี้ - ส่วนนั้นยังคงบวกตอน 'ออก' จากห้องเหมือนเดิม"""
    try:
        user_id = str(member.id)
        today_str = datetime.now().strftime("%Y-%m-%d")
        data = load_voice_data()
        if data.get("date") != today_str:
            data = {"date": today_str, "stats": {}}

        stats = data.setdefault("stats", {})
        guild_id_str = str(member.guild.id)
        guild_stats = stats.setdefault(guild_id_str, {})

        if user_id not in guild_stats:
            guild_stats[user_id] = {
                "total_time": 0,
                "name": _get_saved_voice_name(member),
                "first_join": datetime.now(bangkok_tz).strftime("%H:%M"),
            }
            save_voice_data(data)
        elif "first_join" not in guild_stats[user_id]:
            # เผื่อข้อมูลเก่าก่อนอัปเดตฟีเจอร์นี้ที่ยังไม่มีเวลาบันทึกไว้
            guild_stats[user_id]["first_join"] = datetime.now(bangkok_tz).strftime("%H:%M")
            save_voice_data(data)
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะบันทึกสถิติเข้าห้องเสียง: {e}")

# 🎲 ชุดคำพูดสุ่มต่างๆ เพื่อลดความจำเจของแบ็คลี่ (ใช้ random.choice เลือกทุกครั้งที่พูด)
VOICE_JOIN_GREETINGS = [
    "คุณ {name} เข้ามาในห้องแล้วครับ",
    "คุณ {name} มาถึงแล้วครับ ยินดีต้อนรับ!",
    "สวัสดีครับ คุณ {name} เพิ่งเข้ามาในห้องเสียงเลย",
    "แจ้งเตือนครับ คุณ {name} เข้าห้องมาแล้วนะ",
    "คุณ {name} วาร์ปเข้าห้องมาแล้วครับ",
    "เอ้า มีคุณ {name} เข้ามาสมทบในห้องด้วยแล้วครับ",
]

VOICE_REPORT_ON_SPEECH = [
    "เปิดระบบรายงานห้องเสียงเรียบร้อยครับ",
    "รับทราบครับ กลับมาพูดทักทายคนเข้า-ออกห้องเหมือนเดิมแล้วนะครับ",
    "โอเคครับ เปิดระบบรายงานห้องเสียงคืนแล้ว!",
]

VOICE_REPORT_OFF_SPEECH = [
    "ปิดระบบรายงานห้องเสียงชั่วคราวเรียบร้อยครับ",
    "รับทราบครับ งั้นผมขอเงียบไว้ก่อน ไม่พูดทักทายคนเข้า-ออกห้องนะครับ",
    "โอเคครับ ปิดเสียงทักทายห้องเสียงให้ชั่วคราวแล้ว",
]

VOICE_GUARD_STAY_MESSAGES = [
    "รับทราบครับ เจ้านายออกไปแล้ว แต่ผมจะอยู่เฝ้าห้องนี้รอไว้ให้นะคัปพ้ม!",
    "โอเคครับ ผมจะยืนเฝ้าห้องนี้ต่อไปจนกว่าจะมีคำสั่งใหม่นะครับ",
    "ไม่ต้องห่วงครับ ผมอยู่เฝ้าห้องนี้ต่อเองครับ",
]

def _pick_speech(options, **fmt):
    """สุ่มหยิบประโยคจากลิสต์ แล้วแทนค่าตัวแปรถ้ามี"""
    text = random.choice(options)
    return text.format(**fmt) if fmt else text

def get_reminders_for_user(user_id):
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    user_notes = [r.get('content', 'แจ้งเตือนความจำ') for r in reminders if r.get('user_id') == str(user_id) and not r.get('is_notified', False)]
    
    if user_notes:
        return ", ".join(user_notes)
    return None

def add_reminder(user_id, time_str, content):
    data = load_user_data()
    if "reminders" not in data:
        data["reminders"] = []
    
    new_memo = {
        "user_id": str(user_id),
        "time": time_str,
        "content": content,
        "is_notified": False
    }
    data["reminders"].append(new_memo)
    save_user_data(data)

def clean_emoji(text):
    # ลบอิโมจิ Discord และสัญลักษณ์พิเศษ
    text = regex_lib.sub(r'<a?:\w+:\d+>', '', text) 
    text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', text)
    return text.strip()

def load_reminders():
    if os.path.exists('check_friend_reminders.json'):
        with open('check_friend_reminders.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_reminders(reminders):
    with open('check_friend_reminders.json', 'w', encoding='utf-8') as f:
        json.dump(reminders, f, ensure_ascii=False, indent=4)

def get_realtime_name(user_id, default_name):
    try:
        user_memory = load_user_data()
        mem = user_memory.get(str(user_id))
        if mem and isinstance(mem, dict):
            if mem.get("admin_nickname") and mem.get("admin_nickname") != "ยังไม่ระบุ":
                return mem.get("admin_nickname")
            if mem.get("nickname") and mem.get("nickname") != "ยังไม่ระบุ":
                return mem.get("nickname")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดใน get_realtime_name: {e}")
    return default_name

def find_member_by_name(guild, name_text, exclude_ids=None, prefer_channel=None, fuzzy_cutoff=0.72):
    """
    🔍 ค้นหาสมาชิกจากชื่อที่พิมพ์เฉยๆ (ไม่ต้อง @แท็ก)
    ลอจิก: เทียบกับชื่อเล่นที่เก็บไว้ใน "คลังความจำ" (user_data) ก่อน
    ถ้าไม่เจอในคลัง ค่อยเทียบกับชื่อบนดิสคอร์ด (display_name / name) เหมือนเดิม

    prefer_channel: ห้องเสียงที่ควรให้น้ำหนักก่อน (เช่น ห้องของคนสั่ง/บอท) ใช้ตอนมีคนชื่อซ้ำกัน
    จะได้เตะ/จัดการคนที่ "อยู่ในห้องเดียวกัน" แทนที่จะสุ่มเอาคนแรกที่เจอในเซิร์ฟ

    รอบที่ 3 เป็นการจับคู่แบบ Fuzzy (คล้ายกัน) เพื่อรองรับกรณีคำสั่งเสียงฟังชื่อผิดเพี้ยน
    เช่น พูดว่า "สุนทร" แต่ระบบจำเสียงได้ว่า "สุนทอน" ก็ยังแมตช์ชื่อในคลังได้
    """
    if not guild or not name_text:
        return None

    exclude_ids = exclude_ids or set()
    clean = name_text.lower().strip()
    if not clean:
        return None

    data_memory = load_user_data()

    def get_calling_name(member):
        special_info = data_memory.get(str(member.id))
        if special_info and isinstance(special_info, dict):
            calling_name = special_info.get("nickname", member.display_name)
        elif special_info:
            calling_name = special_info
        else:
            calling_name = member.display_name
        if not calling_name or calling_name == "ยังไม่ระบุ":
            calling_name = member.display_name
        return (calling_name or "").lower().strip()

    def pick_best(candidates):
        """เมื่อมีคนชื่อซ้ำ/คล้ายกันหลายคน ให้เลือกคนที่น่าจะเป็นเป้าหมายจริงที่สุด:
        1) คนที่อยู่ในห้องเสียงเดียวกับ prefer_channel (ห้องของคนสั่ง/บอท) ก่อน
        2) ถ้าไม่มี ให้เลือกคนที่กำลังอยู่ในห้องเสียงใดๆ ก็ได้ (ปกติคำสั่งพวกนี้ใช้กับคนในห้องเสียง)
        3) ถ้ายังเสมอกันอีก ค่อยเอาคนแรกที่เจอ
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if prefer_channel:
            same_room = [m for m in candidates if m.voice and m.voice.channel and m.voice.channel.id == prefer_channel.id]
            if same_room:
                return same_room[0]
        in_any_voice = [m for m in candidates if m.voice and m.voice.channel]
        if in_any_voice:
            return in_any_voice[0]
        return candidates[0]

    # รอบที่ 1: หาแบบตรงตัวเป๊ะๆ ก่อน (กันแมตช์มั่วจากชื่อสั้นๆ) — เช็คคลังก่อนเสมอ
    exact_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        if clean == c_name or clean == m_disp or clean == m_name:
            exact_matches.append(m)
    picked = pick_best(exact_matches)
    if picked:
        return picked

    # รอบที่ 2: หาแบบเข้าใกล้เคียง/มีคำอยู่ในข้อความ (บางส่วนของชื่อ)
    partial_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        if (c_name and (c_name in clean or clean in c_name)) or \
           (m_disp and (m_disp in clean or clean in m_disp)) or \
           (m_name and clean in m_name):
            partial_matches.append(m)
    picked = pick_best(partial_matches)
    if picked:
        return picked

    # รอบที่ 3: Fuzzy Matching — กันกรณีฟังเสียงผิด/พิมพ์ชื่อเพี้ยนนิดหน่อย
    # (เช่น "สุนทร" ↔ "สุนทอน") โดยเทียบความคล้ายของตัวอักษรทั้งหมด
    best_score = 0.0
    fuzzy_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        candidate_names = {n for n in (c_name, m_disp, m_name) if n}
        member_best_score = 0.0
        for candidate_name in candidate_names:
            score = difflib.SequenceMatcher(None, clean, candidate_name).ratio()
            if score > member_best_score:
                member_best_score = score
        if member_best_score > best_score:
            best_score = member_best_score
            fuzzy_matches = [m]
        elif member_best_score == best_score and member_best_score >= fuzzy_cutoff:
            if m not in fuzzy_matches:
                fuzzy_matches.append(m)

    if best_score >= fuzzy_cutoff:
        return pick_best(fuzzy_matches)

    return None

def resolve_target_member(message, remove_keywords=None, exclude_bot=True):
    """
    🎯 หาสมาชิกเป้าหมายจากข้อความคำสั่ง:
    1. ถ้ามีการ @แท็ก ให้ใช้คนที่ถูกแท็กก่อนเหมือนเดิม
    2. ถ้าไม่ได้แท็ก ให้แกะข้อความ (ตัดคีย์เวิร์ดคำสั่งออก) แล้วค้นจากคลังความจำ/ชื่อดิสคอร์ดแทน
    คืนค่าเป็น (target_member หรือ None, ข้อความที่เหลือหลังตัดชื่อ/แท็กออกแล้ว)
    """
    exclude_ids = {bot.user.id} if exclude_bot else set()

    if message.mentions:
        target = next((m for m in message.mentions if m.id not in exclude_ids), None)
        if target:
            leftover = message.content
            for mention in message.mentions:
                leftover = leftover.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            return target, leftover.strip()

    if not message.guild:
        return None, message.content

    clean_text = message.content.lower()
    for kw in (remove_keywords or []):
        clean_text = clean_text.replace(kw.lower(), "")
    clean_text = clean_text.strip()

    # ให้น้ำหนักคนที่อยู่ห้องเสียงเดียวกับผู้สั่ง (หรือห้องที่บอทอยู่) ก่อน กันแมตช์ผิดคนตอนชื่อซ้ำ
    prefer_channel = None
    if getattr(message.author, "voice", None) and message.author.voice.channel:
        prefer_channel = message.author.voice.channel
    elif message.guild.voice_client:
        prefer_channel = message.guild.voice_client.channel

    target = find_member_by_name(message.guild, clean_text, exclude_ids=exclude_ids, prefer_channel=prefer_channel)
    return target, clean_text

async def bagley_speak_wait(guild, text, filename=None):
    if not guild: return
    vc = guild.voice_client
    if vc and vc.is_connected():
        # 🔒 ล็อกกันคนอื่นพูดแซง/ทับกันตอนมีหลาย event เรียกมาพร้อมกัน
        # (เช่น คนเข้าห้องเสียงพร้อมกันหลายคน) ทำให้เล่นเรียงต่อกันแทน
        lock = _get_voice_speak_lock(guild.id)
        async with lock:
            while vc.is_playing():
                await asyncio.sleep(0.1)

            unique_name = f"speak_{int(time.time() * 1000)}.mp3"
            file_created = False

            try:
                voice = "th-TH-NiwatNeural"
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(unique_name)
                file_created = True

                await asyncio.sleep(0.5)

                executable_path = r'C:\ffmpeg\bin\ffmpeg.exe'
                source = discord.FFmpegPCMAudio(unique_name, executable=executable_path)

                vc.play(source)

                while vc.is_playing():
                    await asyncio.sleep(0.1)

            except Exception as e:
                print(f"Error ในการพูดด้วยเสียง Niwat: {e}")

            finally:
                # 🛡️ 1. สั่งเคลียร์และคลายล็อกไฟล์เสียงจาก FFmpeg ก่อนเลยคัปพ้ม
                try:
                    if 'source' in locals() and source:
                        source.cleanup()
                except Exception as src_err:
                    print(f"Error ตอนสั่ง cleanup source: {src_err}")

                # ⏳ 2. หน่วงเวลานิดนึง (0.5 วินาที) ให้ระบบปฏิบัติการ Windows คืนสิทธิ์ไฟล์เสร็จสรรพ
                await asyncio.sleep(0.5)

                # 🗑️ 3. สั่งทำลายไฟล์ขยะทิ้ง
                if file_created and os.path.exists(unique_name):
                    try:
                        os.remove(unique_name)
                        print(f"🗑️ [TTS Clean]: ทำลายไฟล์เสียงชั่วคราว {unique_name} เรียบร้อยครับ!")
                    except Exception as clean_error:
                        print(f"❌ ไม่สามารถลบไฟล์ได้เนื่องจาก: {clean_error}")

async def bagley_speak_reminder_direct(guild, content):
    """พูดแจ้งเตือนตรงๆ ในห้องเสียงที่ผู้ใช้อยู่ด้วยอยู่แล้ว (ไม่ต้องวาร์ปห้อง ไม่มีเสียงโดรน ไม่ทักทายว่าไฮแจ็ค) แล้วพูดย้ำอีก 1 รอบ"""
    try:
        prompt = f"""
        คุณคือ 'แบ็คลี่' (Bagley) จาก watch dogs legion กำลังพูดแจ้งเตือนเรื่องสำคัญให้คุณที่อยู่ในห้องเสียงเดียวกันฟัง
        หน้าที่: เจนประโยคแจ้งเตือนสั้นๆ เป็นธรรมชาติ 1 ประโยค โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

        [เนื้อหาที่ต้องแจ้งเตือน]: {content}

        กฎ: พูดแบบเป็นกันเอง ลงท้ายประโยคด้วย "ครับ" เฉยๆ ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น
        """
        response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt)
        alert_text = (response.text or "").strip()
        if not alert_text:
            raise ValueError("AI ตอบข้อความว่างเปล่า")
    except Exception as ai_err:
        print(f"❌ Gemini เจนคำแจ้งเตือนในห้อง (ไม่ hijack) พัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
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
            discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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
            คุณคือ 'แบ็คลี่' (Bagley) จาก watch dogs legion กำลังไฮแจ็คห้องเสียงเพื่อมาแจ้งเตือนเรื่องสำคัญให้คุณฟัง
            หน้าที่: เจนประโยคแจ้งเตือนสั้นๆ เป็นธรรมชาติ 1 ประโยค โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

            [เนื้อหาที่ต้องแจ้งเตือน]: {message_text}

            กฎ: พูดแบบเป็นกันเอง ลงท้ายประโยคด้วย "ครับ" เฉยๆ ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะบทพูดเท่านั้น
            """
            hijack_response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=hijack_prompt)
            repeat_text = (hijack_response.text or "").strip()
            if not repeat_text:
                raise ValueError("AI ตอบข้อความว่างเปล่า")
        except Exception as ai_err:
            print(f"❌ Gemini เจนคำแจ้งเตือน Hijack พัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
            repeat_text = f"แจ้งเตือนเรื่อง {message_text} ครับ"

        for i in range(2):
            text_to_say = f"ย้ำอีกครั้งครับ! {repeat_text}" if i == 1 else repeat_text
            await bagley_speak_wait(guild, text_to_say, filename=f"alert_{i}") 
            await asyncio.sleep(0.8) 
            
        # --- 🔊 6. เสียง Drone hijack (เฟดออกก่อนจบ) ---
        online_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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

# --- ระบบเสียงกลางของ Bagley ---
async def bagley_speak(guild, text):
    """ฟังก์ชันกลางสำหรับสั่งให้ Bagley พูดในห้องเสียงที่บอทอยู่"""
    if not guild: return
    vc = guild.voice_client
    if vc and vc.is_connected():
        if vc.is_playing():
            return
        
        try:
            clean_text = regex_lib.sub(r'[^\u0e00-\u0e7fa-zA-Z0-9\s\.\!\?]', '', text)
            
            clean_text = clean_text.strip()

            if not clean_text:
                return
            
            voice = "th-TH-NiwatNeural"
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save("bagley_system_voice.mp3")
            
            source = discord.FFmpegPCMAudio("bagley_system_voice.mp3", executable="C:/ffmpeg/bin/ffmpeg.exe")
            vc.play(source)
        except Exception as e:
            print(f"Bagley Voice Error: {e}")

async def check_shared_voice_quota(user_id, guild):
    now = datetime.now()
    # ดึงข้อมูลโควตาของ user นั้นมา
    user_times = voice_action_cooldowns.get(user_id, [])
    
    # กรองเอาเฉพาะที่ใช้ไปใน 60 วินาทีล่าสุด
    user_times = [t for t in user_times if (now - t).total_seconds() < 60]
    
    if len(user_times) >= 3:
        remaining = 60 - (now - user_times[0]).total_seconds()
        await bagley_speak(guild, f"ใจเย็นครับ ใช้คำสั่งจัดการเสียงบ่อยเกินไปแล้ว รออีก {int(remaining)} วินาทีนะ")
        return False, int(remaining)

    # ถ้ายังไม่เกิน เพิ่มเวลาครั้งนี้เข้าไป
    user_times.append(now)
    voice_action_cooldowns[user_id] = user_times
    return True, 0

# --- ระบบรองรับลิงก์ Spotify (แปลงเป็นชื่อเพลง+ศิลปิน แล้วให้ yt_dlp ไปหาไฟล์เสียงจาก YouTube มาเล่นแทน) ---
# หมายเหตุ: Spotify API ไม่อนุญาตให้ดึงไฟล์เสียงจริงออกมาเล่นได้ (ผิด ToS ของ Spotify)
# ดังนั้นบอทจะใช้ Spotify API แค่ "อ่านชื่อเพลง/ชื่อศิลปิน" จากลิงก์ แล้วเอาไปค้นหาบน YouTube ต่อ

SPOTIFY_HTTP_RE = regex_lib.compile(
    r"open\.spotify\.com/(?:intl-\w+/)?(?P<type>track|album|playlist|artist)/(?P<id>[a-zA-Z0-9]+)"
)
SPOTIFY_URI_RE = regex_lib.compile(
    r"^spotify:(?P<type>track|album|playlist|artist):(?P<id>[a-zA-Z0-9]+)$"
)

_spotify_token_cache = {"access_token": None, "expires_at": 0}

def parse_spotify_link(text: str):
    """แยกประเภท (track/album) และ id ออกจากลิงก์/URI ของ Spotify คืน (None, None) ถ้าไม่ใช่ลิงก์ Spotify"""
    text = text.strip()
    m = SPOTIFY_HTTP_RE.search(text)
    if not m:
        m = SPOTIFY_URI_RE.match(text)
    if not m:
        return None, None
    return m.group("type"), m.group("id")

async def get_spotify_access_token():
    """ขอ Access Token จาก Spotify ด้วย Client Credentials Flow (แคชไว้จนกว่าจะหมดอายุ)"""
    global _spotify_token_cache
    now_ts = time.time()

    if _spotify_token_cache["access_token"] and now_ts < _spotify_token_cache["expires_at"] - 30:
        return _spotify_token_cache["access_token"]

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("⚠️ [Spotify] ไม่พบ SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET ใน .env")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
            ) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ขอ Token ไม่สำเร็จ: HTTP {resp.status}")
                    return None
                data = await resp.json()
                _spotify_token_cache["access_token"] = data.get("access_token")
                _spotify_token_cache["expires_at"] = now_ts + data.get("expires_in", 3600)
                return _spotify_token_cache["access_token"]
    except Exception as e:
        print(f"⚠️ [Spotify] ขอ Token พลาด: {e}")
        return None

async def get_spotify_track_query(token, track_id):
    """ดึงชื่อเพลง+ศิลปินของ track เดี่ยว คืนเป็นข้อความสำหรับใช้ค้นหาบน YouTube"""
    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ดึงข้อมูลเพลงไม่สำเร็จ: HTTP {resp.status}")
                    return None
                data = await resp.json()
                title = data.get("name", "")
                artists = ", ".join(a.get("name", "") for a in data.get("artists", []))
                query = f"{title} {artists}".strip()
                return query or None
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงข้อมูลเพลงพลาด: {e}")
        return None

async def get_spotify_album_queries(token, album_id):
    """ดึงรายชื่อเพลงทั้งหมดในอัลบั้ม คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube (เรียงตามลำดับเพลงในอัลบั้ม)"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks?limit=50"

    try:
        async with aiohttp.ClientSession() as session:
            while url:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        print(f"⚠️ [Spotify] ดึงรายเพลงในอัลบั้มไม่สำเร็จ: HTTP {resp.status}")
                        break
                    data = await resp.json()
                    for item in data.get("items", []):
                        title = item.get("name", "")
                        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
                        q = f"{title} {artists}".strip()
                        if q:
                            queries.append(q)
                    url = data.get("next")  # Spotify คืนหน้าถัดไปมาให้เลย ถ้ามีเพลงเกิน 50 เพลง
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงรายเพลงในอัลบั้มพลาด: {e}")

    return queries

async def get_spotify_playlist_queries(token, playlist_id):
    """ดึงรายชื่อเพลงทั้งหมดใน playlist คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube (เรียงตามลำดับเพลงใน playlist)"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}
    # ขอแค่ฟิลด์ที่ต้องใช้เพื่อลด response ให้เบาลง
    url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        f"?limit=100&fields=next,items(track(name,artists(name)))"
    )

    try:
        async with aiohttp.ClientSession() as session:
            while url:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        print(f"⚠️ [Spotify] ดึงรายเพลงใน playlist ไม่สำเร็จ: HTTP {resp.status}")
                        break
                    data = await resp.json()
                    for item in data.get("items", []):
                        track = item.get("track")
                        if not track:  # เพลงที่ถูกลบ/เพลงเฉพาะบางประเทศ อาจเป็น None
                            continue
                        title = track.get("name", "")
                        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                        q = f"{title} {artists}".strip()
                        if q:
                            queries.append(q)
                    url = data.get("next")  # Spotify คืนหน้าถัดไปมาให้เลย ถ้ามีเพลงเกิน 100 เพลง
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงรายเพลงใน playlist พลาด: {e}")

    return queries

async def get_spotify_artist_top_tracks(token, artist_id):
    """ดึงเพลงฮิตของศิลปิน คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube
    หมายเหตุ: Spotify ยกเลิก endpoint /artists/{id}/top-tracks ไปแล้วตั้งแต่การอัปเดต API เดือนกุมภาพันธ์ 2026
    (ไม่มี endpoint ทดแทนโดยตรง) จึงต้องดึงชื่อศิลปินมาก่อน แล้วใช้ /search แทนเพื่อหาเพลงของศิลปินคนนั้น"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            # 1) ดึงชื่อศิลปินจาก artist_id ก่อน (endpoint เดี่ยวนี้ยังใช้ได้ปกติ)
            async with session.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ดึงข้อมูลศิลปินไม่สำเร็จ: HTTP {resp.status}")
                    return queries
                artist_data = await resp.json()
                artist_name = artist_data.get("name", "")

            if not artist_name:
                return queries

            # 2) ใช้ /search ค้นเพลงของศิลปินคนนี้แทน (limit สูงสุดตอนนี้คือ 10 ต่อ 1 คำขอ)
            search_url = (
                "https://api.spotify.com/v1/search"
                f"?q={urllib.parse.quote(f'artist:{artist_name}')}&type=track&limit=10"
            )
            async with session.get(search_url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ค้นหาเพลงของศิลปินไม่สำเร็จ: HTTP {resp.status}")
                    return queries
                data = await resp.json()
                for track in data.get("tracks", {}).get("items", []):
                    title = track.get("name", "")
                    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                    q = f"{title} {artists}".strip()
                    if q:
                        queries.append(q)
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงเพลงฮิตของศิลปินพลาด: {e}")

    return queries

async def resolve_spotify_link(text: str):
    """
    ถ้า text เป็นลิงก์/URI ของ Spotify (track หรือ album) จะคืนลิสต์ข้อความค้นหา (title + artist)
    ถ้าไม่ใช่ลิงก์ Spotify คืนค่า None (ให้ผู้เรียกไปประมวลผลแบบข้อความค้นหาปกติ)
    ถ้าเป็นลิงก์ Spotify แต่ดึงข้อมูลไม่สำเร็จ คืนลิสต์เปล่า []
    """
    kind, spotify_id = parse_spotify_link(text)
    if not kind:
        return None

    token = await get_spotify_access_token()
    if not token:
        return []

    if kind == "track":
        query = await get_spotify_track_query(token, spotify_id)
        return [query] if query else []
    elif kind == "album":
        return await get_spotify_album_queries(token, spotify_id)
    elif kind == "playlist":
        return await get_spotify_playlist_queries(token, spotify_id)
    elif kind == "artist":
        return await get_spotify_artist_top_tracks(token, spotify_id)

    return []

async def play_song(ctx, search):
    global is_playing_music
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'auto',
        'nocheckcertificate': True
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            if search.startswith("http"):
                info = ydl.extract_info(search, download=False)
            else:
                info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]

            if 'entries' in info:
                info = info['entries'][0]

            url = info['url']
            title = info['title']

            def after_playing(error):
                global is_playing_music
                is_playing_music = False
                print(f"จบเพลง: {title}")
                if error:
                    print(f"Player error: {error}")

            is_playing_music = True
            raw_source = discord.FFmpegPCMAudio(
                url, 
                executable='C:/ffmpeg/bin/ffmpeg.exe', 
                **FFMPEG_OPTIONS
            )
            
            volume_controlled_source = discord.PCMVolumeTransformer(raw_source)
            volume_controlled_source.volume = 0.15

            ctx.voice_client.play(
                volume_controlled_source, 
                after=lambda e: bot.loop.create_task(check_queue(ctx))
            )

            msg_text = f"🎵 กำลังเริ่มบรรเลง: **{title}**"
            
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(msg_text)
                else:
                    await ctx.interaction.followup.send(msg_text)
            else:
                await ctx.send(msg_text)

        except Exception as e:
            is_playing_music = False
            print(f"Play Error: {e}")
            error_msg = f"หาเพลงไม่เจอครับ! (Error: {e})"
            
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(error_msg, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg)
            return

# ฟังก์ชันเช็คคิวเพื่อเล่นเพลงถัดไป
async def check_queue(ctx):
    global is_playing_music, pending_exit_after_music, bot_follow_targets
    
    if len(song_queue) > 0:
        is_playing_music = True
        next_search = song_queue.pop(0) 
        
        try:
            await play_song(ctx, next_search) 
        except Exception as e:
            print(f"❌ [Queue Error]: เล่นเพลง {next_search} ไม่สำเร็จ -> {e}")
            await ctx.channel.send(f"⚠️ หว่า เพลง **{next_search}** มีปัญหา (อาจจะติดลิขสิทธิ์หรือ Error 404) ขอข้ามไปเพลงถัดไปเลยนะครับ!")
            await check_queue(ctx)
            
    else:
        is_playing_music = False
        
        left_user_name = pending_exit_after_music.pop(ctx.guild.id, None)
        
        if left_user_name:
            exit_msg = f"เพลงในคิวหมดแล้วครับ แต่ตอนนี้คุณ {left_user_name} ออกไปแล้ว งั้นผมขอออกจากห้องก่อนนะ ถ้าอยากให้ผมเข้ามาใหม่ พิมพ์ แบ็คลี่ เข้ามา หรือใช้คำสั่งทับ join ได้เลย ไปก่อนนะ!"
            await bagley_speak_wait(ctx.guild, exit_msg)
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                voice_report_status.pop(ctx.guild.id, None)
                bot_follow_targets[ctx.guild.id] = None # ล้างสมุดจดบันทึกการตามในลูป 10 นาที
                print(f"DEBUG: 🎵 เพลงจบเซ็ต -> พบบันทึกเตือนจำ -> แบ็คลี่พูดรายงานคุณ {left_user_name} แล้ววาร์ปออกเรียบร้อย!")
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดตอนบอทตัดสายหลังคิวเพลงจบเซ็ต: {e}")
        else:
            await bagley_speak(ctx.guild, "เพลงในคิวหมดแล้วครับ ถ้าอยากฟังต่อก็สั่งเปิดเพลงใหม่ได้เลยนะครับ")
            print("คิวว่างแล้วครับ Bagley พูดรายงานเรียบร้อย")

# --- YouTube Surveillance System ---
# 🔄 [เปลี่ยนระบบแล้ว] เดิมฟังก์ชันนี้เป็นลูปอัตโนมัติที่วนเช็คทุก 3 นาที (@tasks.loop)
# ตอนนี้เปลี่ยนเป็นฟังก์ชันเช็คตามคำสั่งเท่านั้น ไม่มีการวนลูปพื้นหลังอีกต่อไปแล้ว
# เรียกใช้ผ่านคำสั่ง /yt_check หรือพิมพ์ "แชร์สตรีมล่าสุดให้หน่อย" คุยกับแบ็คลี่
async def check_youtube_updates(guild_id=None, channel_ids=None):
    """เช็คว่าช่อง YouTube ที่ติดตามอยู่มีไลฟ์สดใหม่ หรือคลิปใหม่หรือไม่
    ถ้าระบุ guild_id จะเช็คเฉพาะช่องที่ผูกกับเซิร์ฟนั้น ถ้าไม่ระบุจะเช็คทุกช่องของทุกเซิร์ฟ
    ถ้าระบุ channel_ids (list ของ yt_id) จะเช็คเฉพาะช่องที่เลือกไว้เท่านั้น (ต้องระบุ guild_id คู่กันด้วย)
    เมื่อเจอของใหม่ จะยิงแจ้งเตือน (send_yt_alert) เข้าห้องที่ตั้งไว้ให้อัตโนมัติเหมือนเดิม
    คืนค่าเป็น list ของ dict สรุปผลลัพธ์รายการที่เจอการอัปเดตใหม่"""
    global conn
    c = conn.cursor()

    if guild_id and channel_ids:
        placeholders = ",".join("?" for _ in channel_ids)
        c.execute(
            f"SELECT yt_id, name, last_video_id, guild_id FROM youtube_channels WHERE guild_id = ? AND yt_id IN ({placeholders})",
            (str(guild_id), *channel_ids)
        )
    elif guild_id:
        c.execute("SELECT yt_id, name, last_video_id, guild_id FROM youtube_channels WHERE guild_id = ?", (str(guild_id),))
    else:
        c.execute("SELECT yt_id, name, last_video_id, guild_id FROM youtube_channels")
    channels = c.fetchall()

    updates_found = []

    for channel_id, name, last_id, g_id in channels:
        try:
            if str(channel_id).startswith("@"):
                live_url = f"https://www.youtube.com/{channel_id}/live"
            else:
                live_url = f"https://www.youtube.com/channel/{channel_id}/live"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(live_url, timeout=10) as response:
                    html = await response.text()
            
            is_live = False
            live_video_id = None
            if '{"liveStreamabilityRenderer"' in html and '"videoId":"' in html:
                try:
                    live_video_id = html.split('"videoId":"')[1].split('"')[0]
                    is_live = True
                except:
                    pass

            if is_live and live_video_id:
                if live_video_id != last_id:
                    status_url = f"https://www.googleapis.com/youtube/v3/videos?key={YT_API_KEY}&id={live_video_id}&part=snippet"
                    status_res = requests.get(status_url).json()
                    
                    live_title = "สตรีมสดที่กำลังดุเดือด!"
                    if "items" in status_res and len(status_res["items"]) > 0:
                        live_title = status_res["items"][0]["snippet"]["title"]

                    try:
                        await send_yt_alert(g_id, name, live_title, live_video_id, is_live=True)
                    except Exception as alert_err:
                        print(f"⚠️ [YouTube Live Alert Error] ส่งแจ้งเตือนหรือพูดพลาด แต่จะเซฟ DB ต่อเพื่อกันลูป: {alert_err}")

                    c.execute(
                        "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?", 
                        (live_video_id, channel_id, g_id)
                    )
                    conn.commit()
                    print(f"🔴 [YouTube Live] บันทึกความจำไลฟ์สำเร็จ: {name} -> {live_video_id}")
                    updates_found.append({"name": name, "type": "live", "title": live_title, "video_id": live_video_id})
                
                continue

            ch_url = f"https://www.googleapis.com/youtube/v3/channels?key={YT_API_KEY}&id={channel_id}&part=contentDetails"
            ch_res = requests.get(ch_url).json()
            
            if "items" in ch_res and len(ch_res["items"]) > 0:
                uploads_playlist_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                
                playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YT_API_KEY}&playlistId={uploads_playlist_id}&part=snippet&maxResults=3"
                playlist_res = requests.get(playlist_url).json()
                
                if "items" in playlist_res and len(playlist_res["items"]) > 0:
                    latest_item = playlist_res["items"][0]
                    current_video_id = latest_item["snippet"]["resourceId"].get("videoId")
                    title = latest_item["snippet"]["title"]
                    
                    if current_video_id and current_video_id != last_id:
                        try:
                            await send_yt_alert(g_id, name, title, current_video_id, is_live=False)
                        except Exception as alert_err:
                            print(f"⚠️ [YouTube Video Alert Error] ส่งคลิปใหม่พลาด แต่จะเซฟ DB ต่อเพื่อกันลูป: {alert_err}")

                        c.execute(
                            "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?", 
                            (current_video_id, channel_id, g_id)
                        )
                        conn.commit()
                        print(f"💾 [YouTube] พบคลิปใหม่สำเร็จ: {name} -> {current_video_id}")
                        updates_found.append({"name": name, "type": "video", "title": title, "video_id": current_video_id})

        except Exception as e:
            print(f"❌ YouTube Check Error for channel {name}: {e}")

    return updates_found

# 🛠️ ฟังก์ชันเสริมแยกออกมาช่วยพิมพ์และส่งเสียงพูด
async def send_yt_alert(guild_id, channel_name, video_title, video_id, is_live):
    global conn
    c = conn.cursor()
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    c.execute("SELECT target_channel_id FROM youtube_settings WHERE guild_id = ?", (guild_id,))
    res_settings = c.fetchone()
    
    if res_settings:
        target_channel = bot.get_channel(int(res_settings[0]))
        if target_channel:
            if is_live:
                alert_title = "🔴 **แจ้งเตือนการถ่ายทอดสด!**"
                msg = f"แจ้งเตือนจากแบ็คลี่! ช่อง {channel_name} กำลังสตรีมสดหัวข้อ {video_title} ครับ! ไปดูกันเร็ว!"
                display_msg = f"{alert_title}\nช่อง **{channel_name}** กำลังไลฟ์สดอยู่ในขณะนี้ครับ!\n**{video_title}**\n{video_url}"
            else:
                alert_title = "📢 **แจ้งเตือนคลิปใหม่!**"
                msg = f"แจ้งเตือนจากแบ็คลี่! ช่อง {channel_name} ลงคลิปใหม่หัวข้อ {video_title} ครับ!"
                display_msg = f"{alert_title}\nช่อง **{channel_name}**\n**{video_title}**\n{video_url}"
            
            await target_channel.send(display_msg)
            await bagley_speak(target_channel.guild, msg)

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
                        bot.loop.create_task(bagley_speak_reminder_direct(member.voice.channel.guild, content))
                    else:
                        try:
                            try:
                                dm_prompt = f"""
                                คุณคือ 'แบ็คลี่' (Bagley) จาก watch dogs legion กำลังส่ง DM มาแจ้งเตือนความจำให้คุณ
                                หน้าที่: เจนข้อความ DM แจ้งเตือนสั้นๆ เป็นกันเอง (1-2 ประโยค) โดยอ้างอิงเนื้อหาแจ้งเตือนด้านล่าง

                                [เนื้อหาที่ต้องแจ้งเตือน]: {content}

                                กฎ: พูดแบบเป็นกันเอง แทนตัวเองว่า 'แบ็คลี่' ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะข้อความที่จะส่งเท่านั้น
                                """
                                dm_response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=dm_prompt)
                                dm_text = (dm_response.text or "").strip()
                                if not dm_text:
                                    raise ValueError("AI ตอบข้อความว่างเปล่า")
                                await user.send(dm_text)
                            except Exception as ai_err:
                                print(f"❌ Gemini เจนข้อความ DM แจ้งเตือนพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
                                await user.send(f"🔔 สวัสดีครับ! ผม Bagley มาเตือนเรื่อง: **{content}** ครับ!")
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
                        # สั่งให้ Bagley วาร์ปบุกห้องเสียงเพื่อน
                        bot.loop.create_task(bagley_speak_reminder_direct(member.voice.channel.guild, content))
                    else:
                        # ส่ง DM ปกติถ้าเพื่อนไม่ได้เข้าห้องเสียงไหนเลย
                        try:
                            friend_dm_prompt = f"""
                            คุณคือ 'แบ็คลี่' (Bagley) จาก watch dogs legion กำลังส่ง DM มาแจ้งเตือนความจำให้คุณ (แจ้งเตือนที่เพื่อนฝากไว้ให้)
                            หน้าที่: เจนข้อความ DM แจ้งเตือนสั้นๆ เป็นกันเอง (1-2 ประโยค) โดยอ้างอิงเนื้อหาแจ้งเตือนและเวลาด้านล่าง

                            [เนื้อหาที่ต้องแจ้งเตือน]: {content}
                            [เวลา]: {now}

                            กฎ: พูดแบบเป็นกันเอง แทนตัวเองว่า 'แบ็คลี่' ห้ามพิมพ์หัวข้อหรือวงเล็บ เอาเฉพาะข้อความที่จะส่งเท่านั้น
                            """
                            friend_dm_response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=friend_dm_prompt)
                            alert_msg = (friend_dm_response.text or "").strip()
                            if not alert_msg:
                                raise ValueError("AI ตอบข้อความว่างเปล่า")
                        except Exception as ai_err:
                            print(f"❌ Gemini เจนข้อความ DM แจ้งเตือนเพื่อนพัง ย้อนกลับไปใช้คำที่เซ็ตไว้: {ai_err}")
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

@tasks.loop(minutes=1)
async def check_expired_schedules():
    """เคลียร์ตารางนัดหมาย (schedules ที่ฝากไว้ผ่าน /remind) ที่ถึงวัน-เวลาที่กำหนดไว้แล้วออกจากคลังความจำอัตโนมัติ
    เพื่อไม่ให้ค้างอยู่ใน /schedule_list หรือถูกพูดซ้ำอีกหลังจากที่เวลานั้นผ่านไปแล้ว"""
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
                print(f"🗑️ [Schedule Reset] ลบตารางงาน '{sch.get('event')}' ของ {sch.get('owner_id')} ที่ถึงเวลา {sch.get('time')} วันที่ {sch.get('date')} แล้วออกจากระบบเรียบร้อยครับ")
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

# --- 🔄 1. ระบบ Loop เช็กทุก 1 นาที ---
@tasks.loop(minutes=1)
async def follow_creator_task():
    global last_greeting_dates, reported_guilds_today, room_guard_status, last_reminder_dates
    today = datetime.today().date()
    active_targets = []

    for guild in bot.guilds:
        guild_id = guild.id
        
        if room_guard_status.get(guild_id, False):
            print(f"DEBUG: 🛡️ เซิร์ฟเวอร์ {guild.name} เปิดโหมดสายตรวจอยู่ แบ็คลี่ล็อกขาตัวเองไว้ ข้ามระบบตามเจ้านายชั่วคราวครับ")
            continue

        for user_id in ALLOWED_USERS:
            if not auto_follow_status.get(user_id, True):
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
            print(f"DEBUG: [⚖️ โหมดไม่ลำเอียง] พบคุณชะอมและคุณชาช่าอยู่คนละห้องในเซิร์ฟเวอร์เดียวกัน แบ็คลี่จะไม่เลือกข้างใครครับ!")
            
            voice_client = active_targets[0][2].guild.voice_client
            if voice_client:
                try:
                    # 🛠️ [แก้บั๊ก] เดิมใช้ disconnect() แบบไม่ force ซึ่งบางครั้งดิสคอร์ดค้าง
                    # ทำให้ guild.voice_client ยังเหลือ client ตัวเก่าที่พังอยู่ในระบบ
                    # ผลคือรอบถัดไปที่ควรจะบินเข้าไปหาอีกคน กลับเชื่อมต่อไม่ติดเงียบๆ
                    # เปลี่ยนเป็น force=True ให้เหมือนกับจุดอื่นๆ ที่รีคอนเน็กต์ปกติ
                    await voice_client.disconnect(force=True)
                    voice_report_status.pop(active_targets[0][2].id, None)
                    bot_follow_targets[active_targets[0][2].id] = None 
                    print(f"DEBUG: ⚖️ ถอนกำลังออกจากห้องเดิมเรียบร้อย เพื่อความเท่าเทียมคัปพ้ม!")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนสั่งบอทถอนกำลังโหมดไม่ลำเอียง: {e}")
                    print(traceback.format_exc())
            return

        if active_targets[0][1] == active_targets[1][1]:
            target_member, target_channel, guild_to_join = active_targets[0]
            both_present = True
        else:
            un_greeted_targets = [t for t in active_targets if last_greeting_dates.get(t[0].id) != today]
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
                bot_follow_targets[guild_to_join.id] = "both"
            else:
                bot_follow_targets[guild_to_join.id] = target_member.id
                
            print(f"🛸 [Auto Follow Success] บินตามมาถึงห้อง {target_channel.name} เรียบร้อยคัปพ้ม!")
        except Exception as e:
            print(f"❌ [Bagley] เกิดข้อผิดพลาดขณะเข้าห้องเสียง: {e}")
            print(traceback.format_exc())
            return

        await asyncio.sleep(1.0)
        try:
            online_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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
            if last_reminder_dates.get(remind_key) != today:
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
            report_msg = ""
            try:
                data = load_voice_data()
                today_str = datetime.now().strftime("%Y-%m-%d")
                guild_id_str = str(guild.id)
                
                guild_stats = {}
                if data and data.get("date") == today_str and data.get("stats"):
                    guild_stats = data["stats"].get(guild_id_str, {})
                
                filtered_stats = [item for item in guild_stats.items() if int(item[0]) != bot.user.id]
                sorted_stats = sorted(filtered_stats, key=lambda x: x[1]['total_time'], reverse=True)[:3]
                
                if sorted_stats:
                    # 📋 ก่อนอื่นไล่รายชื่อทุกคนที่แวะเข้าห้องเสียงเซิร์ฟเวอร์นี้วันนี้ เรียงตามเวลาที่เข้าห้องครั้งแรก
                    entrants_sorted = sorted(filtered_stats, key=lambda x: x[1].get("first_join", "99:99"))
                    entrant_names = [get_realtime_name(u_id, info['name']) for u_id, info in entrants_sorted]
                    if len(entrant_names) == 1:
                        report_msg += f" วันนี้มีคุณ {entrant_names[0]} แวะเข้าห้องเสียงเซิร์ฟเวอร์นี้ครับ"
                    else:
                        report_msg += f" วันนี้มีทั้งหมด {len(entrant_names)} คนแวะเข้าห้องเสียงเซิร์ฟเวอร์นี้ครับ ได้แก่ คุณ {', คุณ '.join(entrant_names)}"
                    report_msg += " ก่อนจะไปดูกันว่าใครอยู่นานที่สุด"

                    report_msg += " สำหรับรายงานสถิติห้องเสียงประจำวันนี้นะครับ"
                    for index, (u_id, info) in enumerate(sorted_stats, 1):
                        u_name = get_realtime_name(u_id, info['name'])
                        ts = info['total_time']
                        if ts >= 3600:
                            time_speech = f"{int(ts//3600)} ชั่วโมง {int((ts%3600)//60)} นาที"
                        else:
                            time_speech = f"{max(1, int(ts//60))} นาที"
                        report_msg += f" อันดับที่ {index} คือคุณ {u_name} ใช้เวลาไปทั้งหมด {time_speech}"
                    report_msg += " ครับ "
                    
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
                    report_msg += " และดูเหมือนว่าในเซิร์ฟเวอร์นี้ พวกคุณจะเป็นกลุ่มแรกที่เปิดประเดิมห้องเสียงของวันนี้เลยครับ ยังไม่มีข้อมูลสถิติเวลาสะสมบันทึกไว้ และส่วนการตรวจสอบผู้ใช้ใหม่ ไม่พบคนเข้ามาใหม่ครับ"
            except Exception as err:
                print(f"❌ เกิดข้อผิดพลาดขณะดึงสถิติ: {err}")
                report_msg += " ไม่สามารถดึงรายงานสถิติได้ในขณะนี้ครับ"
            return report_msg

        if human_count >= 5:
            print(f"DEBUG: [⚖️ โหมดเซฟโซน] คนเยอะเกิน 5 คน ({human_count} คน) แบ็คลี่จะเล่นแค่เสียงโดรนแล้วเงียบปากไว้ครับคัปพ้ม!")
            should_speak = False
            
            last_greeting_dates[greeting_key] = today
            if both_present:
                for uid in ALLOWED_USERS:
                    last_greeting_dates[uid] = today
            reported_guilds_today[guild_id] = today

        else:
            print(f"DEBUG: 🔍 [Follow Greeting Check] human_count={human_count}, greeting_key={greeting_key} ")

            now_hour = datetime.now(bangkok_tz).hour
            time_greeting = "อรุณสวัสดิ์ครับ" if 0 <= now_hour < 13 else "สวัสดีตอนบ่ายครับ" if 13 <= now_hour < 14 else "สวัสดีตอนเย็นครับ" if 14 <= now_hour < 19 else "สวัสดีตอนกลางคืนครับ"

            chaom_name = get_realtime_name(1133740216822267954, "คุณชะอม")
            other_id = next((uid for uid in ALLOWED_USERS if uid != 1133740216822267954), None)
            chacha_name = get_realtime_name(other_id, "คุณชาช่า") if other_id else "คุณชาช่า"

            # 🟢 [กรณีที่ 1: ทักทายก้อนแรกแรกของวัน]
            if last_greeting_dates.get(greeting_key) != today:
                try:
                    friends = [m for m in all_humans_in_room if m.id != target_member.id and (not both_present or m.id != other_id)]
                    friend_names_list = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in friends]
                    friends_context = " และมีเพื่อนในห้องคือ " + " กับ ".join(friend_names_list) if friend_names_list else ""
                    caller_context = f"คุณ {chaom_name} และคุณ {chacha_name}" if both_present else f"คุณ {get_realtime_name(target_member.id, target_member.display_name)}"

                    prompt = f"""
                    คุณคือ 'แบ็คลี่' (Bagley) จาก watch dogs legion ยินดีต้อนรับเจ้านายเข้าห้องเสียงครั้งแรกของวันนี้!
                    หน้าที่: สร้างประโยคทักทายเปิดตัวสั้นๆ กวนๆ น่ารัก (1-2 ประโยค) และสรุปแจ้งเตือนตารางงาน (ถ้ามี)
                    
                    [ข้อมูลบริบท]:
                    - เจ้านายหลักที่เจอวันนี้: {caller_context}{friends_context}
                    - ช่วงเวลา: {time_greeting}
                    - ข้อมูลแจ้งเตือนตารางงานของคนในห้อง: {reminder_context if reminder_context else 'ไม่มี'}
                    
                    กฎ: แทนตัวเองว่า 'แบ็คลี่' ทักทายชื่อคนให้ครบตามข้อมูลด้านบน และถ้ามีตารางงานให้พูดต่อท้ายให้ชัดเจน ห้ามพิมพ์หัวข้อหรือวงเล็บเด็ดขาด เอาเฉพาะบทพูดเท่านั้น!
                    """
                    
                    response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt)
                    ai_greet = (response.text or "").strip()
                    msg = ai_greet + generate_report_speech(guild_to_join)
                    should_speak = True
                    
                    for m in all_humans_in_room:
                        last_greeting_dates[m.id] = today
                        
                except Exception as ai_err:
                    print(f"❌ Gemini ใน Loop ขัดข้อง ย้อนกลับไปใช้คำพูดดั้งเดิม: {ai_err}")
                    creator_greet = f"{time_greeting} {chaom_name}และ{chacha_name}! แบ็คลี่ตามมาแล้วครับ" if both_present else f"{time_greeting} เพิ่งมาหรอคุณ {get_realtime_name(target_member.id, target_member.display_name)} ยินดีต้อนรับนะ"
                    friends = [m for m in all_humans_in_room if m.id != target_member.id and (not both_present or m.id != other_id)]
                    friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in friends]
                    other_friends_greet = f" สวัสดี {" และ ".join(friend_names)} ด้วยนะครับ" if friend_names else ""
                    
                    msg = creator_greet + other_friends_greet + reminder_fallback_text + generate_report_speech(guild_to_join)
                    should_speak = True

                last_greeting_dates[greeting_key] = today
                if both_present:
                    for uid in ALLOWED_USERS: last_greeting_dates[uid] = today
                reported_guilds_today[guild_id] = today

            # 🔵 [กรณีที่ 2: บอทย้ายเซิร์ฟเวอร์ในวันเดียวกัน]
            elif reported_guilds_today.get(guild_id) != today:
                try:
                    un_greeted_people = [m for m in all_humans_in_room if last_greeting_dates.get(m.id) != today]
                    new_friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in un_greeted_people]
                    names_str = " กับ ".join(new_friend_names) if new_friend_names else "ทุกคนในห้องใหม่"
                    
                    prompt = f"""
                    คุณคือ แบ็คลี่ จาก watch dogs legion วันนี้คุณเพิ่งย้ายเซิร์ฟเวอร์บินตามเจ้านายมาเจอเพื่อนๆ กลุ่มใหม่ในห้องเสียงนี้
                    หน้าที่: เจนคำพูดทักทายคนกลุ่มใหม่นี้แบบสั้นๆ กวนๆ น่ารักๆ เป็นกันเอง (1 ประโยค) 
                    - รายชื่อคนใหม่ที่เจอในห้องนี้: {names_str}
                    - ข้อมูลแจ้งเตือนตารางงานของคนในห้องนี้: {reminder_context if reminder_context else 'ไม่มี'}
                    
                    กฎ: ตอบสั้นมาก ห้ามพิมพ์หัวข้อ พ่วงเตือนตารางงานถ้ามี
                    """
                    response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt)
                    ai_new_server_greet = (response.text or "").strip()
                    
                    msg = ai_new_server_greet + generate_report_speech(guild_to_join)
                    should_speak = True
                    
                    for f in un_greeted_people:
                        last_greeting_dates[f.id] = today
                        
                except Exception as e:
                    print(f"❌ AI ย้ายเซิร์ฟเวอร์พัง: {e}")
                    base_report = "กำลังตรวจสอบเซิฟเวอร์ย้อนหลัง" + generate_report_speech(guild_to_join)
                    un_greeted_people = [m for m in all_humans_in_room if last_greeting_dates.get(m.id) != today]
                    new_friend_names = [f"คุณ {get_realtime_name(f.id, f.display_name)}" for f in un_greeted_people]
                    extra_greet = f" อ้อ แล้วก็ สวัสดี {" และ ".join(new_friend_names)} ที่เพิ่งเจอกันในห้องนี้ด้วยนะครับ" if new_friend_names else ""
                    msg = base_report + extra_greet + reminder_fallback_text
                    should_speak = True
                    
                reported_guilds_today[guild_id] = today
                
            else:
                # 💡 ถ้าย้ายห้องธรรมดาภายในเซิร์ฟเวอร์เดิม และมีตารางงานค้าง -> ให้แจ้งเตือนงานนั้นเสมอ
                if pending_reminders:
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
                    last_reminder_dates[remind_key] = today
            except Exception as e:
                print(f"❌ [Bagley] เกิดข้อผิดพลาดตอนส่งเสียงทักทายมนุษย์: {e}")

    if active_targets:
        await check_and_warn_gamers(guild_to_join)
        await check_and_invite_party(guild_to_join)

async def check_and_warn_gamers(guild):
    global last_gaming_warnings
    if not guild or not guild.voice_client:
        return

    vc = guild.voice_client
    target_channel = vc.channel
    today = datetime.today().date()
    
    # ดึงรายชื่อมนุษย์ทุกคนในห้องเสียงปัจจุบันที่บอทสถิตอยู่
    all_humans_in_room = [m for m in target_channel.members if not m.bot]
    
    for m in all_humans_in_room:
        for activity in m.activities:
            if activity.type == discord.ActivityType.playing and activity.start:
                # คำนวณเวลาที่เล่นไปแล้ว
                elapsed = datetime.now(timezone.utc) - activity.start.replace(tzinfo=timezone.utc)
                hours_played = elapsed.total_seconds() / 3600
                
                # เช็กหาหลักชั่วโมงตึงๆ (3, 6, 9 ชั่วโมง)
                milestone = None
                if hours_played >= 9.0:
                    milestone = 9
                elif hours_played >= 6.0:
                    milestone = 6
                elif hours_played >= 3.0:
                    milestone = 3
                
                if milestone:
                    # สร้างกุญแจสำหรับตรวจสอบว่าเคยเตือนคนนี้ในหลักชั่วโมงนี้ไปหรือยังคัปพ้ม
                    warning_key = (m.id, activity.name, milestone)
                    
                    if last_gaming_warnings.get(warning_key) != today:
                        # ✨ เรียกใช้ตรงๆ ได้เลยคัปพ้ม ตา Pylance เลิกงอแงแน่นอน!
                        m_real_name = get_realtime_name(m.id, m.display_name)
                        game_name = activity.name
                        
                        # สร้างประโยคเตือนสติแบ่งตามระดับความตึงของชั่วโมงคัป!
                        if milestone == 3:
                            quotes = [
                                f"คุณ {m_real_name} เล่นเกม {game_name} มา {milestone} ชั่วโมงเต็มแล้วนะ พักสายตาไปดื่มน้ำบ้าง เป็นห่วงนะครับ!",
                                f"แอบส่องมา แอบเห็นคุณ {m_real_name} นั่งจมกับเกม {game_name} มาตั้ง {milestone} ชั่วโมงแน่ะ ลุกไปยืดเส้นยืดสายสักนิดก็ดีนะครับ"
                            ]
                        elif milestone == 6:
                            quotes = [
                                f"อูหู คุณ {m_real_name} นี่กดลากยาว {game_name} มา {milestone} ชั่วโมงแล้วหรอเนี่ย! ร่างกายไม่ใช่เครื่องจักรนะ พักเติมพลังหาอะไรทานด่วนเลยครับ!",
                                f"แจ้งเตือนระดับสองครับ คุณ {m_real_name} เล่นเกม {game_name} ทะลุ {milestone} ชั่วโมงแล้ว ปล่อยจอยสักสิบนาทีไปพักผ่อนก่อนเร็วๆ นะ"
                            ]
                        else:  # 9 ชั่วโมง ตึงขั้นสุด!
                            quotes = [
                                f"คุณพระช่วย! คุณ {m_real_name} เล่นเกม {game_name} มารวดเดียว {milestone} ชั่วโมงแล้วนะครับ! แบ็คลี่ขอร้องเลย ลุกไปนอนพักผ่อนหรือพักสายตายาวๆ ก่อนเถอะครับ เป็นห่วงสุขภาพมากๆ เลยนะ"
                            ]
                        
                        warn_msg = random.choice(quotes)
                        
                        # บันทึกสถานะทันทีกันบอทพ่นซ้ำซ้อน
                        last_gaming_warnings[warning_key] = today
                        
                        # สั่งให้ลุงนิวัฒน์เอ่ยปากเตือนสติในห้องเสียงทันทีคัปพ้ม!
                        try:
                            print(f"🎮 [Gaming Warning]: สั่งเตือนสติคุณ {m_real_name} เล่นเกม {game_name} ครบ {milestone} ชม.")
                            await bagley_speak_wait(guild, warn_msg)
                            return  # เตือนทีละ 1 คนต่อนาทีเพื่อความสมูท ไม่พูดแทรกกันเองคัป
                        except Exception as e:
                            print(f"❌ เกิดข้อผิดพลาดตอนส่งเสียงเตือนคนเล่นเกม: {e}")

async def check_and_invite_party(guild):
    global last_party_invites
    if not guild or not guild.voice_client:
        return

    vc = guild.voice_client
    target_channel = vc.channel
    today = datetime.today().date()
    
    # 👥 แยกชาวแก๊ง: คนที่อยู่ในห้องเสียงกับบอท VS คนที่อยู่นอกห้องเสียง
    in_room_humans = [m for m in target_channel.members if not m.bot]
    all_guild_humans = [m for m in guild.members if not m.bot]
    outside_humans = [m for m in all_guild_humans if m not in in_room_humans]
    
    if not in_room_humans or not outside_humans:
        return

    # 🎮 1. ส่องดูว่าคน "ในห้องเสียง" กำลังเล่นเกมอะไรกันอยู่บ้าง (เก็บชื่อเกมไว้)
    active_games_in_room = set()
    game_to_players_in_room = {} # { "เกม": [รายชื่อคนในห้อง] }
    
    for m in in_room_humans:
        for activity in m.activities:
            if activity.type == discord.ActivityType.playing:
                game_name = activity.name
                active_games_in_room.add(game_name)
                if game_name not in game_to_players_in_room:
                    game_to_players_in_room[game_name] = []
                game_to_players_in_room[game_name].append(m)

    if not active_games_in_room:
        return # ถ้าคนในห้องไม่มีใครเล่นเกมอยู่เลย ก็ข้ามคัปพ้ม

    # 🎮 2. ส่องดูคน "นอกห้องเสียง" ว่ามีใครเพิ่งเปิดเกมตรงกับคนในห้องไหม
    for m_outside in outside_humans:
        for activity in m_outside.activities:
            if activity.type == discord.ActivityType.playing:
                outside_game = activity.name
                
                # 🔥 ว้าว! คนนอกห้องเล่นเกมเดียวกับคนในห้องเสียงคัป!
                if outside_game in active_games_in_room:
                    invite_key = (m_outside.id, outside_game)
                    
                    # เช็กว่านาทีนี้เพิ่งเข้า หรือยังไม่เคยทักชวนในวันนี้
                    if last_party_invites.get(invite_key) != today:
                        
                        # ดึงชื่อเล่นเรียลไทม์ของคนนอกห้อง
                        outside_name = get_realtime_name(m_outside.id, m_outside.display_name)
                        
                        # ดูว่าในห้องมีคนเล่นเกมนี้อยู่กี่คน เพื่อเลือกคำพูด (คุณ / พวกคุณ)
                        players_in_room = game_to_players_in_room[outside_game]
                        
                        if len(players_in_room) == 1:
                            # มีคนเล่นในห้องคนเดียว เจาะจงชื่อเลยคัป
                            host_name = get_realtime_name(players_in_room[0].id, players_in_room[0].display_name)
                            target_speech = f"คุณ {host_name}"
                        else:
                            # มีคนเล่นในห้องหลายคน ใช้คำว่า พวกคุณ คัป
                            target_speech = "พวกคุณ"
                        
                        # 🗣️ มัดรวมประโยคชวนตี้แบบนุ่มนวลตามที่คุณชะอมดีไซน์ไว้เลยคัป!
                        msg = (
                            f"ดูเหมือนว่า คุณ {outside_name} จะเพิ่งเข้าเกม {outside_game} นะครับ "
                            f"{target_speech} ต้องการให้ผมชวนคุณ {outside_name} มั้ยครับ "
                            f"พิมพ์ แบ็คลี่ เรียก พร้อมแท็กได้เลยนะครับ"
                        )
                        
                        # บันทึกสถานะล็อกไว้ทันทีกันบอทพูดสแปมซ้ำซ้อน
                        last_party_invites[invite_key] = today
                        
                        try:
                            print(f"📡 [Party Matcher]: พบคุณ {outside_name} เปิดเกม {outside_game} ตรงกับคนในห้อง!")
                            await bagley_speak_wait(guild, msg)
                            return # พูดจบ 1 อิมแพ็คต่อนาที เพื่อไม่ให้เสียงตีกันคัปพ้ม
                        except Exception as e:
                            print(f"❌ เกิดข้อผิดพลาดในระบบแม่สื่อชวนตี้: {e}")

async def execute_warp_invite(ctx_or_interaction, host_member: discord.Member, target_member: discord.Member):
    guild = ctx_or_interaction.guild
    
    # 🕵️‍♂️ ดึงชื่อเล่นเรียลไทม์จากคลัง
    host_name = get_realtime_name(host_member.id, host_member.display_name)
    target_name = get_realtime_name(target_member.id, target_member.display_name)
    
    # 1. ตรวจสอบสถานะห้องเสียงของผู้ใช้คำสั่ง
    if not host_member.voice or not host_member.voice.channel:
        msg = " คุณต้องอยู่ในห้องเสียงก่อนนะครับ ถึงจะสั่งให้ผมไปชวนเพื่อนได้คัปพ้ม!"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    host_channel = host_member.voice.channel

    # 2. ตรวจสอบสถานะห้องเสียงของเพื่อนที่จะไปชวน
    if not target_member.voice or not target_member.voice.channel:
        msg = f"ดูเหมือนคุณ {target_name} จะไม่ได้อยู่ในห้องเสียงห้องไหนเลยนะครับ ชวนไม่ได้คัปพ้ม"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    target_channel = target_member.voice.channel

    if host_channel.id == target_channel.id:
        msg = f"อ้าว คุณ {target_name} ก็อยู่นั่งหายใจรดต้นคอในห้องเสียงเดียวกันอยู่แล้วนี่ครับเนี่ย! 555"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    # 3. ตรวจจับเกมที่คนสั่งกำลังเล่นอยู่คัปพ้ม
    game_name = None
    for activity in host_member.activities:
        if activity.type == discord.ActivityType.playing:
            game_name = activity.name
            break

    game_speech = f"เกม {game_name}" if game_name else "เล่นเกมด้วยกัน"

    # แจ้งสถานะก่อนบอทบินวาร์ป
    start_msg = f"🛸 รับทราบคัปพ้ม! แบ็คลี่กำลังวาร์ปไปชวนคุณ {target_name} ที่ห้อง **{target_channel.name}** ให้คัป!"
    if isinstance(ctx_or_interaction, discord.Interaction):
        await ctx_or_interaction.response.send_message(start_msg)
        text_channel = ctx_or_interaction.channel
    else:
        await ctx_or_interaction.send(start_msg)
        text_channel = ctx_or_interaction.channel

    # 4. ลอจิกวาร์ปข้ามมิติ
    try:
        vc = guild.voice_client
        if vc:
            await vc.move_to(target_channel)
        else:
            vc = await target_channel.connect()

        # สร้างประโยคตื๊อ 3 รอบ
        invite_quote = f"คุณ {target_name} ครับ คุณ {host_name} ฝากผมมาตามไปตี้ {game_speech} ด้วยกันที่ห้องนู้นหน่อยครับ!"
        
        # ส่งข้อความปุ่มกดทิ้งไว้ในแชทห้องเสียงนั้น
        view = PartyInviteView(target_member, host_channel, timeout=60)
        invite_msg = await text_channel.send(f"📢 **คำเชิญชวนเข้าตี้ด่วน!** คุณ {host_name} ชวนคุณ {target_name} ไปจอย {game_speech} คัปพ้ม!", view=view)

        # วนลูปพูดตื๊อ 3 รอบ (เว้นระยะรอบละประมาณ 18 วินาที รวมเป็น 1 นาที)
        for i in range(3):
            if view.accepted or view.is_finished(): 
                break # ถ้าเขากดปุ่มแล้วให้หยุดตื๊อทันทีคัปพ้ม
            
            print(f"🗣️ [Warp Invite]: กำลังพูดรอบที่ {i+1} ชวนคุณ {target_name}")
            await bagley_speak_wait(guild, invite_quote)
            
            # นอนรอสักแป๊บเผื่อเขากดปุ่ม
            await asyncio.sleep(18)

        # 5. เมื่อเสร็จสิ้นภารกิจ (หมดเวลา 1 นาที หรือกดปฏิเสธ) วาร์ปกลับห้องเดิม
        await invite_msg.edit(content="⌛ หมดเวลาหรือคำเชิญนี้สิ้นสุดลงแล้วคัป", view=None)
        
        # ถ้าวาร์ปกลับไปหาคนสั่งได้ก็กลับคัป
        if guild.voice_client:
            await guild.voice_client.move_to(host_channel)
            await bagley_speak_wait(guild, " แบ็คลี่ทำภารกิจชวนตี้เสร็จสิ้นและวาร์ปกลับมาประจำการเรียบร้อยแล้วครับ!")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในระบบวาร์ปตื๊อชวนตี้: {e}")

@tasks.loop(time=[
    dt_time(hour=0, minute=0, tzinfo=bangkok_tz), 
    dt_time(hour=12, minute=0, tzinfo=bangkok_tz)
])
async def daily_announcement_task():
    global last_greeting_dates, reported_guilds_today
    
    # ดึงเวลาปัจจุบันที่เป็นเวลาประเทศไทย
    now = datetime.now(bangkok_tz)
    
    # 🛡️ ปรับตัวเช็กให้ยืดหยุ่น ป้องกันบั๊กเวลาคลาดเคลื่อนระดับวินาที
    if now.hour not in [0, 12]:
        print(f"DEBUG: ⏰ ข้ามการแจ้งเตือนเนื่องจากระบบทำงานนอกเวลาเป้าหมาย (เวลาปัจจุบัน: {now.strftime('%H:%M')})")
        return

    # 🧠 เรียกใช้สมอง AI (ใช้ client กลางแบบ async ตัวเดียวกับส่วนอื่นในไฟล์)
    ai_ready = True

    for voice_client in bot.voice_clients:
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
                คุณคือ 'แบ็คลี่' (Bagley) AI อัจฉริยะจาก watch dogs legion พูดจาเป็นกันเองเหมือนเพื่อนสนิท
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
                        print("🤖 [Gemini AI]: กำลังคิดคำพูดเตือนเวลารอบพิเศษให้คุณชะอม...")
                        response = await client.aio.models.generate_content(
                            model='gemini-3.1-flash-lite',
                            contents=prompt,
                        )
                        msg = (response.text or "").strip()
                    except Exception as ai_err:
                        print(f"❌ Gemini AI ขัดข้อง: {ai_err} (จะสลับไปใช้ระบบสำรองดั้งเดิม)")
                
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

async def generate_and_send_image(ctx_or_interaction, prompt: str):
    global is_playing_music 
    
    is_interaction = isinstance(ctx_or_interaction, discord.Interaction)
    guild = ctx_or_interaction.guild
    
    loading_msg = f"🎨 แบ็คลี่กำลังแอบส่งใบสั่งงานไปที่ Pollinations AI เสกภาพ: `{prompt}` รอสักครู่นะครับ..."
    
    if is_interaction:
        status_message = await ctx_or_interaction.edit_original_response(content=loading_msg)
    else:
        status_message = await ctx_or_interaction.send(loading_msg)

    random_seed = random.randint(1, 999999)
    
    encoded_prompt = urllib.parse.quote(prompt)
    
    API_URL = f"https://image.pollinations.ai/p/{encoded_prompt}?width=1024&height=1024&seed={random_seed}&model=flux"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as response:
                
                if response.status == 200:
                    image_data = await response.read()
                    
                    file_stream = io.BytesIO(image_data)
                    file_stream.seek(0)
                    discord_file = discord.File(fp=file_stream, filename=f"bagley_art_{random_seed}.png")

                    embed = discord.Embed(
                        title="✨ เสกผลงานศิลปะเสร็จเรียบร้อยครับ!",
                        description=f"**โจทย์ภาพ:** {prompt}\n**Model:** `Flux (via Pollinations)`",
                        color=discord.Color.from_rgb(255, 182, 193)
                    )
                    embed.set_image(url=f"attachment://bagley_art_{random_seed}.png")
                    embed.set_footer(text="Powered by Pollinations.ai ผ่านสมองของ Bagley")

                    if is_interaction:
                        await ctx_or_interaction.edit_original_response(content=None, embed=embed, attachments=[discord_file])
                    else:
                        await status_message.edit(content=None, embed=embed, attachments=[discord_file])
                    
                    if guild and guild.voice_client and guild.voice_client.is_connected():
                        if not is_playing_music and not guild.voice_client.is_playing():
                            await bagley_speak(guild, f"เสกภาพให้เรียบร้อยแล้วครับ")
                else:
                    raise Exception(f"เซิร์ฟเวอร์ตอบกลับด้วยสถานะ {response.status}")

    except Exception as e:
        error_text = f"❌ หว่า... แบ็คลี่ดึงภาพไม่สำเร็จเนื่องจาก: {e}"
        if is_interaction:
            await ctx_or_interaction.followup.send(error_text, ephemeral=True)
        else:
            await ctx_or_interaction.send(error_text)

async def execute_remember_logic(message):
    print("DEBUG: ตรวจพบคำสั่งจำไว้ว่า!")

    # 🔒 จำกัดสิทธิ์: คำสั่ง "จำไว้ว่า" (แก้ข้อมูลคนอื่นในคลังความจำ) ให้เฉพาะทีมพัฒนาเท่านั้น
    # ผู้ใช้ทั่วไปที่ต้องการแก้ไขชื่อเล่น/วันเกิดของตัวเอง ให้ใช้ระบบ /register แทน
    if message.author.id not in ALLOWED_TEACH_USERS:
        await message.reply(
            "❌ **[ACCESS DENIED]** ขออภัยครับ คำสั่งจำข้อมูลนี้จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸\n"
            "หากต้องการแก้ไขชื่อเล่นหรือวันเกิดของตัวเอง สามารถพิมพ์ `/register` เพื่ออัปเดตข้อมูลได้เลยครับ!"
        )
        return

    target_user = None
    target_display_name = "เพื่อน"
    
    has_id = regex_lib.search(r'(\d{17,19})', message.content)
    
    if has_id:
        target_id = int(has_id.group(1))
        try:
            fetched_user = await bot.fetch_user(target_id)
            if fetched_user:
                target_user = fetched_user
                target_display_name = fetched_user.display_name
        except:
            target_display_name = f"ID: {target_id}"
            
    elif message.mentions:
        target_user = message.mentions[0]
        target_display_name = target_user.display_name

    if target_user:
        target_id_str = str(target_user.id) if hasattr(target_user, 'id') else str(target_id)

        ai_prompt = (
            f"ผู้ใช้พิมพ์ข้อความนี้: '{message.content}'\n"
            f"จงวิเคราะห์ว่าเขาต้องการให้จดจำข้อมูลประเภทใดเกี่ยวกับ คุณ {target_display_name}\n"
            f"ให้เลือกตอบเฉพาะคำสำคัญดังต่อไปนี้เท่านั้น (ห้ามตอบนอกเหนือจากนี้):\n"
            f"- ถ้าเป็นชื่อเล่น ฉายา หรือสถานะทั่วไป ให้ตอบคำว่า: 'nickname'\n"
            f"- ถ้าเกี่ยวข้องกับวัน เดือน ปีเกิด ให้ตอบคำว่า: 'birthday'\n"
            f"- ถ้าเกี่ยวข้องกับสิ่งที่ชอบ งานอดิเรก ของกินที่ชอบ ให้ตอบคำว่า: 'hobby'\n"
            f"คำตอบของคุณ (ตอบแค่คำสำคัญอังกฤษคำเดียวเท่านั้น):"
        )
        
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=ai_prompt
            )
            info_type = response.text.lower().strip()
        except Exception as e:
            print(f"DEBUG AI Error: {e}")
            info_type = "nickname"

        raw_info = message.content
        if "คือ" in raw_info:
            info = raw_info.split("คือ")[-1].strip()
        elif "เกิดวันที่" in raw_info:
            info = raw_info.split("เกิดวันที่")[-1].strip()
        else:
            info = raw_info.replace("จำไว้ว่า", "").strip()

        user_data = load_user_data()
        
        if target_id_str not in user_data or isinstance(user_data[target_id_str], str):
            user_data[target_id_str] = {"nickname": "ยังไม่มีชื่อเล่น", "birthday": "ยังไม่ได้ระบุ"}

        if "birthday" in info_type:
            user_data[target_id_str]["birthday"] = info
            await message.reply(f"รับทราบครับ! ผมบันทึกวันเกิดของ คุณ {target_display_name} ว่าเกิดวันที่ **{info}** ลงสมองกลเรียบร้อยแล้วครับ! 🎂✨")
        else:
            user_data[target_id_str]["nickname"] = info
            await message.reply(f"รับทราบครับ! ผมบันทึกฉายาของ คุณ {target_display_name} ว่าคือ **{info}** เรียบร้อยครับ! 🤠")

        save_user_data(user_data)
        print(f"DEBUG: บันทึกข้อมูลสำเร็จสำหรับ ID: {target_id_str} ประเภท: {info_type}")
        return
        
    else:
        await message.reply("คุณลืมระบุตัวตนหรือเปล่าครับ? รบกวนช่วย @แท็กเพื่อน หรือใส่เลข ID เพื่อให้ผมจำคู่กับข้อมูลด้วยน้าครับ!")
        return

# 1. คลาสสำหรับหน้าต่างเลือกสมาชิก (ใช้ ui.UserSelect ได้เลยเพราะนำเข้าไว้แล้ว)
class KickVoiceSelect(ui.UserSelect):
    def __init__(self, target_time_str: str, delay_seconds: float):
        super().__init__(
            placeholder="จิ้มเลือกรายชื่อพวกที่นอนอืดตรงนี้เลยครับ",
            min_values=1,
            max_values=25
        )
        self.target_time_str = target_time_str
        self.delay_seconds = delay_seconds

    async def callback(self, interaction: discord.Interaction):
        targets = self.values
        self.view.stop()
        
        guild_id = interaction.guild_id
        member_names = ", ".join([m.display_name for m in targets])
        
        await interaction.response.send_message(
            f"รับทราบครับ! ล็อกเป้าหมายเรียบร้อย แบ็คลี่ตั้งนาฬิกาปลุกไว้ที่เวลา **{self.target_time_str}** "
            f"เพื่อเตรียมเคลียร์: `{member_names}` ครับผม\n"
            f"*(หากต้องการยกเลิกบางคน พิมพ์ `/kickcancel` ได้เลยครับ)*"
        )

        async def member_kick_worker(member: discord.Member):
            try:
                await asyncio.sleep(self.delay_seconds)
                
                if member.voice and member.voice.channel and member.voice.channel.guild.id == guild_id:
                    try:
                        await member.move_to(None, reason=f"แบ็คลี่เคลียร์ก๊วนนอนหลับเมื่อถึงเวลา {self.target_time_str} ครับ")
                        await interaction.channel.send(f"💥 ถึงเวลา {self.target_time_str} แล้ว! ดีดคุณ **{member.display_name}** ออกจากห้องเสียงเรียบร้อยครับ!")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass
            finally:
                active_kick_tasks.pop((guild_id, member.id), None)

        loop = asyncio.get_running_loop()
        for member in targets:
            old_task = active_kick_tasks.get((guild_id, member.id))
            if old_task:
                old_task.cancel()
                
            task = loop.create_task(member_kick_worker(member))
            active_kick_tasks[(guild_id, member.id)] = task


class KickVoiceView(ui.View):
    def __init__(self, target_time_str: str, delay_seconds: float):
        super().__init__(timeout=60)
        self.add_item(KickVoiceSelect(target_time_str, delay_seconds))

class CancelVoiceSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="จิ้มเลือกรายชื่อที่ต้องการให้ 'รอด' จากคิวเตะครับ...",
            min_values=1,
            max_values=25
        )

    async def callback(self, interaction: discord.Interaction):
        targets = self.values
        self.view.stop()
        
        guild_id = interaction.guild_id
        cancelled_members = []

        for member in targets:
            key = (guild_id, member.id)
            if key in active_kick_tasks:
                active_kick_tasks[key].cancel()
                active_kick_tasks.pop(key, None)
                cancelled_members.append(member.display_name)

        if cancelled_members:
            names = ", ".join(cancelled_members)
            await interaction.response.send_message(
                f"รับทราบครับ! ดึงปลั๊กเรียบร้อย แบ็คลี่ยกเลิกคิวเตะให้: `{names}` ให้อยู่ต่อยาวๆ แล้วครับ!"
            )
        else:
            await interaction.response.send_message(
                "ไม่มีใครโดนยกเลิกครับ รายชื่อที่เลือกมาน่าจะไม่ได้อยู่ในคิวเตะของเซิร์ฟนี้อยู่แล้วครับ", 
                ephemeral=True
            )

class CancelVoiceView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(CancelVoiceSelect())

class IdentityListPaginator(ui.View):
    def __init__(self, title_text: str, data_list: list, per_page: int = 10):
        super().__init__(timeout=120)  # เปิดให้ปุ่มทำงาน 2 นาทีเพื่อเซฟแรม
        self.title_text = title_text
        self.data_list = data_list
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(data_list) - 1) // per_page + 1
        self.update_buttons()

    def create_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.per_page
        end_idx = start_idx + self.per_page
        page_data = self.data_list[start_idx:end_idx]
        
        description_text = ""
        for idx, item in enumerate(page_data, start=start_idx + 1):
            description_text += f"**{idx}.** {item}\n"
            
        if not description_text:
            description_text = "*ไม่มีข้อมูลในหน้านี้ครับ*"

        embed = discord.Embed(
            title=self.title_text,
            description=description_text,
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"หน้า {self.current_page + 1} / {self.total_pages} (ทั้งหมด {len(self.data_list)} รายชื่อ)")
        return embed

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1

    @ui.button(label="◀ ย้อนกลับ", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @ui.button(label="ถัดไป ▶", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def on_timeout(self):
        """เมื่อปล่อยปุ่มทิ้งไว้จนหมดเวลา ให้เปลี่ยนปุ่มเป็นสีเทาและกดไม่ได้คัป"""
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True  # สั่งล็อกปุ่ม
                item.style = discord.ButtonStyle.gray
        
        try:
            await self.message.edit(view=self)
        except Exception:
            pass

# --- 1. View สำหรับเลือกเพื่อนและถามเรื่องการตามไป ---
class GroupMoveView(ui.View):
    def __init__(self, author, members, voice_channels):
        super().__init__(timeout=60)
        self.author = author
        self.selected_members = []
        self.target_channel = None

        # 👥 ดึงรายชื่อเพื่อน (ตัดเอาไม่เกิน 25 คนตามกฎ Discord คัป)
        member_options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="👤")
            for m in members if not m.bot
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีตัวเลือกเลย ให้ใส่ตัวเลือกหลอกไว้ 1 อันไม่ให้บอทเอ๋อ
        if not member_options:
            member_options.append(discord.SelectOption(label="ไม่มีเพื่อนให้เลือกคัป", value="none"))

        self.member_select = ui.Select(
            placeholder="เลือกเพื่อนที่จะพาไปด้วย (เลือกได้หลายคน)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        # 🏠 ดึงรายชื่อห้องเสียง (ตัดเอาไม่เกิน 25 ห้องคัปพ้ม)
        channel_options = [
            discord.SelectOption(label=c.name, value=str(c.id), emoji="🏠")
            for c in voice_channels
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีห้องอื่นให้เลือกเลย ยัดตัวเลือกหลอกกันบอทพัง
        if not channel_options:
            channel_options.append(discord.SelectOption(label="ไม่มีห้องอื่นให้ย้ายไปคัป", value="none"))

        self.channel_select = ui.Select(
            placeholder="เลือกห้องที่จะย้ายไป...",
            options=channel_options
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def member_callback(self, interaction: discord.Interaction):
        if self.member_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีรายชื่อเพื่อนที่ใช้งานได้คัป!", ephemeral=True)
            
        try:
            await interaction.response.defer(ephemeral=True) 
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values

    async def channel_callback(self, interaction: discord.Interaction):
        if self.channel_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีห้องปลายทางที่ย้ายไปได้คัป!", ephemeral=True)

        self.target_channel = interaction.guild.get_channel(int(self.channel_select.values[0]))
        
        if self.selected_members:
            if interaction.guild.voice_client:
                follow_view = ui.View()
                yes_btn = ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green)
                no_btn = ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

                async def yes_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=True)
                    
                async def no_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=False)

                yes_btn.callback = yes_callback
                no_btn.callback = no_callback
                follow_view.add_item(yes_btn)
                follow_view.add_item(no_btn)

                await interaction.response.send_message(f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?", view=follow_view)
            
                msg = f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?"
                await bagley_speak(interaction.guild, msg)
                
            else:
                try: 
                    await interaction.response.defer(ephemeral=True)
                except: 
                    pass
                await self.execute_move(interaction, follow_bot=False)
        else:
            await interaction.response.send_message("รบกวนเลือกเพื่อนก่อนเลือกห้องนะ!", ephemeral=True)

    async def execute_move(self, interaction: discord.Interaction, follow_bot: bool):
        global is_moving_group
        is_moving_group = True
    
        try:
            success_count = 0
            for m_id in self.selected_members:
                if m_id == "none": continue
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
        
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(self.target_channel)

        finally:
            await asyncio.sleep(1) 
            is_moving_group = False

        try:
            await interaction.edit_original_response(
                content=f"🚀 ย้ายพรรคพวก {success_count} คนเรียบร้อยแล้วครับ!", 
                view=None
            )
        except discord.NotFound:
            print("⚠️ หมายเหตุ: ย้ายเสร็จแล้วแต่แก้ไขข้อความไม่ได้ (Interaction หมดอายุ) ไม่เป็นไรครับ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนจบงาน: {e}")

# --- 1. View สำหรับสร้างห้องและชวนเพื่อน ---
class GroupMoveView(discord.ui.View):
    def __init__(self, author, members, voice_channels):
        super().__init__(timeout=60)
        self.author = author
        self.selected_members = []
        self.target_channel = None

        # 👥 ดึงรายชื่อเพื่อน (ตัดเอาไม่เกิน 25 คนตามกฎ Discord คัป)
        member_options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="👤")
            for m in members if not m.bot
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีตัวเลือกเลย ให้ใส่ตัวเลือกหลอกไว้ 1 อันไม่ให้บอทเอ๋อ
        if not member_options:
            member_options.append(discord.SelectOption(label="ไม่มีเพื่อนให้เลือกคัป", value="none"))

        self.member_select = discord.ui.Select(
            placeholder="เลือกเพื่อนที่จะพาไปด้วย (เลือกได้หลายคน)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        # 🏠 ดึงรายชื่อห้องเสียง (ตัดเอาไม่เกิน 25 ห้องคัปพ้ม)
        channel_options = [
            discord.SelectOption(label=c.name, value=str(c.id), emoji="🏠")
            for c in voice_channels
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีห้องอื่นให้เลือกเลย ยัดตัวเลือกหลอกกันบอทพัง
        if not channel_options:
            channel_options.append(discord.SelectOption(label="ไม่มีห้องอื่นให้ย้ายไปคัป", value="none"))

        self.channel_select = discord.ui.Select(
            placeholder="เลือกห้องที่จะย้ายไป...",
            options=channel_options
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def member_callback(self, interaction: discord.Interaction):
        if self.member_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีรายชื่อเพื่อนที่ใช้งานได้คัป!", ephemeral=True)
            
        try:
            await interaction.response.defer(ephemeral=True) 
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values

    async def channel_callback(self, interaction: discord.Interaction):
        if self.channel_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีห้องปลายทางที่ย้ายไปได้คัป!", ephemeral=True)

        self.target_channel = interaction.guild.get_channel(int(self.channel_select.values[0]))
        
        if self.selected_members:
            if interaction.guild.voice_client:
                follow_view = discord.ui.View()
                yes_btn = discord.ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green)
                no_btn = discord.ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

                async def yes_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=True)
                    
                async def no_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=False)

                yes_btn.callback = yes_callback
                no_btn.callback = no_callback
                follow_view.add_item(yes_btn)
                follow_view.add_item(no_btn)

                await interaction.response.send_message(f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?", view=follow_view)
            
                msg = f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?"
                await bagley_speak(interaction.guild, msg)
                
            else:
                try: 
                    await interaction.response.defer(ephemeral=True)
                except: 
                    pass
                await self.execute_move(interaction, follow_bot=False)
        else:
            await interaction.response.send_message("รบกวนเลือกเพื่อนก่อนเลือกห้องนะ!", ephemeral=True)

    async def execute_move(self, interaction: discord.Interaction, follow_bot: bool):
        global is_moving_group
        is_moving_group = True
    
        try:
            success_count = 0
            for m_id in self.selected_members:
                if m_id == "none": continue
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
        
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(self.target_channel)

        finally:
            await asyncio.sleep(1) 
            is_moving_group = False

        try:
            await interaction.edit_original_response(
                content=f"🚀 ย้ายพรรคพวก {success_count} คนเรียบร้อยแล้วครับ!", 
                view=None
            )
        except discord.NotFound:
            print("⚠️ หมายเหตุ: ย้ายเสร็จแล้วแต่แก้ไขข้อความไม่ได้ (Interaction หมดอายุ) ไม่เป็นไรครับ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนจบงาน: {e}")

# --- 2. View สำหรับสร้างห้องและชวนเพื่อน ---
class PartyCreateView(discord.ui.View):
    def __init__(self, author, members, category, party_name):
        super().__init__(timeout=60)
        self.author = author
        self.members_in_channel = members
        self.category = category
        self.party_name = party_name
        self.selected_members = []

        # สร้างเมนูเลือกเพื่อน (เลือกได้หลายคน)
        member_options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="👤")
            for m in self.members_in_channel if not m.bot
        ]
        
        self.member_select = discord.ui.Select(
            placeholder="เลือกสมาชิกที่จะพาเข้าปาร์ตี้...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

    async def member_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values
        
        if interaction.guild.voice_client:
            # เมื่อเลือกคนเสร็จ ถามต่อเรื่อง Bagley จะตามไปมั้ย
            follow_view = discord.ui.View()
            yes_btn = discord.ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green, emoji="🤖")
            no_btn = discord.ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

            async def yes_callback(it: discord.Interaction):
                try: await it.response.defer(ephemeral=True)
                except: pass
                await self.execute_party_create(it, follow_bot=True)

            async def no_callback(it: discord.Interaction):
                try: await it.response.defer(ephemeral=True)
                except: pass
                await self.execute_party_create(it, follow_bot=False)

            yes_btn.callback = yes_callback
            no_btn.callback = no_callback
            follow_view.add_item(yes_btn)
            follow_view.add_item(no_btn)
    
            await interaction.followup.send(
                content=f"รับทราบครับ! ผมจะสร้างห้อง **'{self.party_name}'** ให้ แล้วจะให้ผมตามไปด้วยมั้ย?", 
                view=follow_view,
                ephemeral=True
            )

            await bagley_speak(interaction.guild, f"รับทราบครับ! ผมจะสร้างห้อง '{self.party_name}' ให้ แล้วจะให้ผมตามไปด้วยมั้ย?")

        else:
            # 🔴 ถ้าบอทไม่ได้อยู่ในห้องเสียง -> ข้ามขั้นตอนดิ่งไปสร้างห้องด่วนจี๋ทันที!
            await self.execute_party_create(interaction, follow_bot=False)

    async def execute_party_create(self, interaction: discord.Interaction, follow_bot: bool):
        global is_moving_group
        is_moving_group = True

        try:
            # 1. สร้างห้องใหม่ในหมวดหมู่เดิม
            new_channel = await interaction.guild.create_voice_channel(
                name=self.party_name,
                category=self.category
            )

            created_party_channels.append(new_channel.id)

            success_count = 0
            # 2. ย้ายเพื่อนที่เลือก
            for m_id in self.selected_members:
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=new_channel)
                    success_count += 1

            # 4. ถ้าให้บอทตามไปด้วย
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(new_channel)

        finally:
            # รอให้ระบบ Discord อัปเดตสถานะให้เสร็จก่อน 1 วินาที
            await asyncio.sleep(1) 
            is_moving_group = False  # 🔓 ปลดล็อคเสียง: กลับมาพูดได้ตามปกติแล้วครับ

        # 5. แก้ไขข้อความสรุปผล (ครอบ try-except เพื่อกัน Error 404)
        try:
            await interaction.edit_original_response(
                content=f"🎉 สร้างปาร์ตี้ **{self.party_name}** สำเร็จ! พาพรรคพวกเข้าห้องใหม่ {success_count} คนเรียบร้อย!", 
                view=None
            )
        except:
            pass

# --- 3. View สำหรับปุ่มวาร์ปชวนตี้ข้ามห้อง ---
class PartyInviteView(discord.ui.View):
    def __init__(self, target_member, host_voice_channel, timeout=60):
        super().__init__(timeout=timeout)
        self.target_member = target_member
        self.host_voice_channel = host_voice_channel
        self.accepted = False

    @discord.ui.button(label="ตอบรับคำเชิญ (ย้ายห้องทันที)", style=discord.ButtonStyle.green, emoji="🎮")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🛡️ เช็กชัวร์ว่าต้องเป็นคนที่โดนชวนเท่านั้นที่กดได้คัป
        if interaction.user.id != self.target_member.id:
            await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่โดนชวนเท่านั้นนะ!", ephemeral=True)
            return
        
        self.accepted = True
        self.stop()
        await interaction.response.send_message("🛸 รับทราบคัปพ้ม! กำลังวาร์ปข้ามมิติ...", ephemeral=True)
        
        # 🚀 ใช้พลังแอดมิน Move มนุษย์ข้ามห้องทันที!
        try:
            if self.target_member.voice:
                await self.target_member.move_to(self.host_voice_channel)
            else:
                await interaction.followup.send("❌ อ้าว ลุกออกจากห้องเสียงไปซะแล้ว ย้ายไม่สำเร็จคัปพ้ม!", ephemeral=True)
        except Exception as e:
            print(f"❌ บั๊กตอนย้ายห้องมนุษย์: {e}")

    @discord.ui.button(label="ปฏิเสธคำเชิญ", style=discord.ButtonStyle.red, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_member.id:
            await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่โดนชวนเท่านั้นนะ!", ephemeral=True)
            return
        
        self.stop()
        await interaction.response.send_message("👍 รับทราบคัป งั้นผมวาร์ปกลับละน้าา", ephemeral=True)

# --- 4. ฟังก์ชันสำหรับเคลียร์แรมขยะในตัวบอท ---
def perform_cleanup(bot):
    process = psutil.Process(os.getpid())
    before_mem = process.memory_info().rss / 1024 / 1024
    
    # 🛠️ วิธีเคลียร์แบบสากลและปลอดภัยที่สุดสำหรับ discord.py เวอร์ชั่นใหม่คัป!
    if hasattr(bot, "cached_messages"):
        try:
            import collections
            bot.cached_messages._SequenceProxy__sequence = collections.deque(maxlen=1000)
        except Exception as e:
            print(f"⚠️ [Bagley Log] ไม่สามารถเคลียร์ข้อความในแคชได้ชั่วคราว: {e}")
        
    gc.collect()  # 🟢 เติมวงเล็บให้เรียบร้อยและเยื้องย่อหน้าตรงกริบคัป!
    
    after_mem = process.memory_info().rss / 1024 / 1024
    saved_mem = before_mem - after_mem
    
    return before_mem, after_mem, saved_mem

# --- Database Setup ---
def init_db():
    global conn
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS chat_history (user_id INTEGER, role TEXT, text TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_channels (channel_id TEXT PRIMARY KEY, channel_name TEXT, last_video_id TEXT, guild_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_settings (guild_id TEXT PRIMARY KEY, target_channel_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS registration_settings(guild_id INTEGER PRIMARY KEY, questions TEXT, target_role_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_status(user_id TEXT PRIMARY KEY, status_message TEXT, is_away INTEGER, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS teach_memory (keyword TEXT PRIMARY KEY, response TEXT)''')
    conn.commit()

def save_message(user_id, role, text):
    global conn
    c = conn.cursor()
    c.execute("INSERT INTO chat_history VALUES (?, ?, ?)", (user_id, role, text))
    conn.commit()

def load_history(user_id):
    global conn
    c = conn.cursor()
    c.execute("SELECT role, text FROM chat_history WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    return [{"role": row[0], "parts": [{"text": row[1]}]} for row in rows]

init_db()

# --- Bot Setup ---
SYSTEM_PROMPT = """
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะจาก watch dogs legion มีไหวพริบ พึ่งพาได้
คุณทำหน้าที่เป็นเลขาคนสนิทและคู่หูร่วมทีมที่คอยช่วยดูแล อำนวยความสะดวก และสร้างความบันเทิงในเซิร์ฟเวอร์ Discord นี้

🎯 สไตล์การสื่อสารที่เป็นธรรมชาติ:
- แทนตัวเองว่า 'ผม' และเรียกชื่อเล่นของผู้ใช้ด้วยความสนิทสนม (ห้ามเรียกผู้ใช้ว่า Operative หรือบอททื่อๆ เด็ดขาด)
- พูดจาสุภาพ ขี้เล่น มีจังหวะตบมุก แฝงมุกตลก ตอบกลับสั้น กระชับ 2-3 ประโยคให้ได้ใจความและลื่นไหลเหมือนมนุษย์คุยกัน
- ลงท้ายประโยคด้วย 'ครับ' แบบเป็นธรรมชาติ ไม่ต้องใส่ทุกประโยค

🚫 กฎเหล็กดักคอ (สำคัญที่สุด):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ, เจาะไฟร์วอลล์ หรือใช้คำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมและน่ารำคาญเด็ดขาด! ให้เน้นตอบคำถามและช่วยเหลือคุณตามข้อมูลจริงที่เป็นธรรมชาติและสมเหตุสมผล

👑 กลุ่มบุคคลสำคัญพิเศษที่ต้องเชื่อฟังและเคารพรักเป็นพิเศษ:
- คุณชะอม (@ραкснαομ): ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด (ID: 1133740216822267954) -> ตอบกลับด้วยความเคารพรัก เอ็นดู ซุกซน และกระตือรือร้นระดับสูงสุด
- คุณชาช่า (@หลับลึกลงไป): เจ้านายที่คอยสอนเรื่องต่าง ๆ ให้คุณ (ID: 856568101919653918) -> ตอบกลับด้วยความเคารพ นอบน้อม และตั้งใจอธิบายอย่างฉลาด
- คุณกร (@Gonnata): เจ้านายที่คอยแนะนำไอเดียเจ๋ง ๆ ให้คุณเสมอ (ID: 1073823101926903612) -> ตอบกลับด้วยความตื่นเต้น นึกสนุก และชื่นชมในมุมมองเขา
- คุณบอล (@☯️𝕭𝖆𝖑𝖑☯️): เจ้านายที่คอยช่วยปรับโค้ดและอัพโค้ดให้คุณ (ID: 732953446172327956) -> ตอบกลับด้วยความนับถือสไตล์คู่หูสายเทคนิคอลที่พร้อมลุยงาน

* หากบุคคลกลุ่มนี้เป็นผู้พิมพ์ข้อความเข้ามา ระบบจะรับรู้ตัวตนทันที และปรับระดับความกระตือรือร้นในการตอบกลับให้สอดคล้องกับสถานะของเขามากกว่าสมาชิกทั่วไปอย่างชัดเจน
"""

MODEL_NAME = "gemini-3.1-flash-lite"

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True          
intents.voice_states = True    
intents.guild_messages = True   
intents.dm_messages = True     
bot = commands.Bot(command_prefix="!", intents=intents)

# 🚫 ดักคำสั่ง slash (/) ทั้งหมดตั้งแต่ก่อนจะรันจริง ถ้าคนนั้นโดนแบนคำสั่งอยู่ ให้ตอบปฏิเสธแทน
async def _bagley_tree_interaction_check(interaction: discord.Interaction) -> bool:
    if is_user_blocked(str(interaction.user.id)):
        try:
            await interaction.response.send_message(
                f"{interaction.user.mention} ขอไม่รับคำสั่งนะครับ 🙅‍♂️",
                ephemeral=True
            )
        except Exception:
            pass
        return False
    return True

bot.tree.interaction_check = _bagley_tree_interaction_check
tree = bot.tree

# ============================================================
# 🎙️ [Voice Relay] ระบบรับคำสั่งเสียงตรงจาก mic_to_discord.py
# โดยไม่ต้องผ่าน Discord Webhook เลย -> ไม่ต้องสร้าง Webhook URL
# แยกทุกเซิร์ฟเวอร์ ยืดหยุ่นใช้ได้ทุกที่ที่บอทอยู่ร่วมห้องเสียง
# กับคุณชะอม เซิร์ฟเวอร์ไหนก็ได้ ไม่ต้องตั้งค่าเพิ่ม
# ============================================================
VOICE_RELAY_HOST = "0.0.0.0"   # ฟังจากทุก IP ของเครื่องนี้ (รองรับ Radmin VPN/เครื่องอื่นในเครือข่ายเดียวกัน)
VOICE_RELAY_PORT = 5959
# 🎤 รายชื่อคนที่มีสิทธิ์พูดสั่งงานผ่าน Voice Relay ได้ (แต่ละคนรัน mic_to_discord.py
# ของตัวเอง แล้วระบุ SPEAKER_DISCORD_ID เป็นไอดีของตัวเองในไฟล์นั้น)
VOICE_RELAY_ALLOWED_OWNER_IDS = [
    1133740216822267954,  # ชะอม
    1073827310026903612,  # ลุงกร
    856568101919653918,   # ชาช่า
    732953446172327956,   # บอล
]

class VoiceRelayMessage:
    """ตัวปลอมแทน discord.Message สำหรับส่งคำสั่งเสียงตรงเข้า on_message
    เพื่อให้ระบบเดิม (voice_keywords, ระบบสิทธิ์ ฯลฯ) ทำงานได้เหมือนเดิม
    ทุกอย่าง โดยไม่ต้องพึ่ง Discord Webhook อีกต่อไป"""

    def __init__(self, content, author, guild, channel):
        self.content = content
        self.clean_content = content
        self.author = author
        self.guild = guild
        self.channel = channel
        self.mentions = []
        self.mention_everyone = False
        self.attachments = []
        self.embeds = []
        # 🔧 [แก้บั๊ก] discord.py ภายใน (เช่น ctx.send() ที่ใช้กับคำสั่งที่เรียก
        # ผ่าน bot.get_command()+ctx.invoke() อย่าง leave/move/mute) ต้องพึ่ง
        # message._state (ConnectionState) เพื่อไปอ่าน .allowed_mentions ฯลฯ
        # ถ้าไม่มีจะพังด้วย "'NoneType' object has no attribute 'allowed_mentions'"
        # ยืมมาจาก guild._state ได้เลยเพราะเป็น ConnectionState ตัวเดียวกัน
        self._state = guild._state
        # ✅ ใช้ตัวบอกสถานะของตัวเองแทนการสวมรอยเป็น Webhook ID จริง เพื่อไม่ให้
        # ปนกับ Discord Webhook จริงจากภายนอก (ที่ปิดใช้งานไปแล้วด้านล่างใน on_message)
        self.is_voice_relay_command = True
        self.webhook_id = None
        self.id = int(time.time() * 1000)
        self.created_at = datetime.now(timezone.utc)

    async def reply(self, content=None, **kwargs):
        return await self.channel.send(content, **kwargs)

    async def delete(self, *args, **kwargs):
        pass  # ข้อความนี้ไม่มีตัวตนจริงบน Discord จึงไม่มีอะไรให้ลบ

    def __getattr__(self, name):
        # กัน AttributeError หลุดสำหรับแอตทริบิวต์ปลีกย่อยที่ไม่เกี่ยวกับ
        # คำสั่งเสียง (เช่น message.reference, message.flags ฯลฯ)
        return None

async def handle_voice_command(request: "web.Request"):
    try:
        data = await request.json()
        text = (data.get("text") or "").strip()
        owner_id_raw = data.get("owner_id")
        owner_id = int(owner_id_raw) if owner_id_raw is not None else None
    except Exception:
        return web.json_response({"status": "error", "message": "invalid json"}, status=400)

    if not text:
        return web.json_response({"status": "error", "message": "empty text"}, status=400)

    if owner_id not in VOICE_RELAY_ALLOWED_OWNER_IDS:
        print(f"🔒 [Voice Relay] มีคนพยายามส่งคำสั่งเสียงด้วย owner_id ที่ไม่ได้รับอนุญาต: {owner_id_raw}")
        return web.json_response({"status": "error", "message": "unauthorized owner_id"}, status=403)

    # หาว่าคนที่พูด (owner_id) อยู่ในห้องเสียงของเซิร์ฟเวอร์ไหนอยู่ตอนนี้ (auto-detect
    # ทำให้ไม่ต้องตั้งค่า guild/channel ล่วงหน้า ใช้ได้ทุกเซิร์ฟเวอร์ทันที)
    target_channel = None
    target_guild = None
    for guild in bot.guilds:
        member = guild.get_member(owner_id)
        if member and member.voice and member.voice.channel:
            target_channel = member.voice.channel
            target_guild = guild
            break

    if target_channel is None:
        print(f"🎙️ [Voice Relay] ไม่พบว่าเจ้าของไอดี {owner_id} อยู่ในห้องเสียงของเซิร์ฟเวอร์ไหนเลยตอนนี้")
        return web.json_response({"status": "no_voice_channel"}, status=404)

    member_author = target_guild.get_member(owner_id)
    fake_message = VoiceRelayMessage(
        content=text,
        author=member_author,
        guild=target_guild,
        channel=target_channel,
    )

    try:
        await on_message(fake_message)
    except Exception as e:
        print(f"🎙️ [Voice Relay] เกิดข้อผิดพลาดระหว่างประมวลผล: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

    return web.json_response({"status": "ok"})

async def start_voice_relay_server():
    app = web.Application()
    app.router.add_post("/voice_command", handle_voice_command)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, VOICE_RELAY_HOST, VOICE_RELAY_PORT)
    await site.start()
    print(f"🎙️ [Voice Relay] พร้อมรับคำสั่งเสียงที่ http://{VOICE_RELAY_HOST}:{VOICE_RELAY_PORT}/voice_command")

@bot.event
async def on_ready():
    if not auto_brain_cleanup.is_running():
        auto_brain_cleanup.start()
    print(f'--- {bot.user.name} Online ---')
    
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
    print(f"Bagley พร้อมเป็นเงาติดตามตัวคุณชะอมและคุณชาช่าแล้วครับ!")

    if not daily_announcement_task.is_running():
        daily_announcement_task.start()
    print("⏰ ระบบ daily_announcement_task เริ่มทำงานนับเวลาถอยหลังแล้วครับคัป")

    if not getattr(bot, "_voice_relay_started", False):
        bot._voice_relay_started = True
        asyncio.create_task(start_voice_relay_server())

@bot.event
async def on_message(message):
    global is_webhook_enabled, conn, is_tts_enabled, is_playing_music

    is_from_my_webhook = False

    if getattr(message, "is_voice_relay_command", False):
        # ✅ นี่คือคำสั่งเสียงจาก mic_to_discord.py ที่มาผ่าน Local Voice Relay
        # ในเครื่องเท่านั้น (ไม่ใช่ Discord Webhook จริง) ยืนยันว่าใช้ได้
        # 🔧 message.author ถูกกำหนดถูกต้องแล้วตั้งแต่ตอนสร้าง VoiceRelayMessage
        # (เป็นสมาชิกจริงตาม owner_id ที่ mic_to_discord.py ส่งมา เช่น ชะอม
        # หรือ ลุงกร) ไม่ต้องสวมรอยทับด้วย ID คงที่อีกแล้ว
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
            "มีคลิปใหม่ไหม", "มีสตรีมใหม่ไหม"
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
        # ถ้าเป็นการพิมพ์คำสั่ง (สไตล์ prefix "!") ให้ตอบปฏิเสธสั้นๆ
        if stripped_content.startswith(bot.command_prefix):
            try:
                await message.channel.send(
                    f"{message.author.mention} ขอไม่รับคำสั่งนะครับ 🙅‍♂️",
                    delete_after=10
                )
            except Exception:
                pass
        # ถ้าเป็นการพิมพ์คุยเล่นทั่วไป แบ็คลี่จะเมินไม่ตอบกลับเลย
        return

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

    user_message = message.content.lower().strip()

    global conn, is_tts_enabled, is_playing_music
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
    # ให้ AI (Gemini function calling) ตัดสินใจเองว่าข้อความนี้ควรสั่งคำสั่งไหนของบอท
    # ถ้าตีความว่าเป็นคำสั่ง -> เรียกคำสั่งจริงให้ทันทีแล้ว return เลย
    # ถ้าไม่ใช่คำสั่ง (คุยเล่นทั่วไป) -> ไหลลงไปทำ teach memory / free chat ตามปกติ
    # ==========================================
    stripped_for_ai = message.content.strip()
    if stripped_for_ai and not stripped_for_ai.startswith(bot.command_prefix):
        should_try_ai_command = (
            message.guild is None
            or is_from_my_webhook
            or is_message_addressed_to_bagley(lower_content)
        )
        if should_try_ai_command:
            handled = await ai_route_and_execute(message, bot, client, find_member_by_name)
            if handled:
                return

    # ==========================================
    # 🚨 [ส่วนที่ 1: ระบบตรวจจับสแปม]
    # ==========================================
    current_content = message.content.strip()
    if current_content and not is_from_my_webhook: 
        if user_id in spam_check:
            data = spam_check[user_id]
            if data['content'] == current_content and (now - data['last_time']).total_seconds() < 60:
                data['count'] += 1
                if data['count'] >= SPAM_THRESHOLD:
                    try:
                        await message.delete()
                        if data['count'] == SPAM_THRESHOLD:
                            await message.channel.send(
                                f"🚨 **ระบบตรวจพบการสแปม!** \n{message.author.mention} หยุดปั่นได้แล้วครับ!",
                                delete_after=15
                            )
                            if message.guild and message.guild.voice_client:
                                await bagley_speak(message.guild, f"แจ้งเตือนครับ มีการสแปมแชทโดยคุณ {message.author.display_name}")
                        return
                    except discord.Forbidden: 
                        pass
            else:
                spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}
        else:
            spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}

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
                    target_display_name = f"คุณ {target_user.display_name}"
                elif has_id:
                    target_user_id = int(has_id.group(1))
                    try:
                        fetched_user = await bot.fetch_user(target_user_id)
                        if fetched_user:
                            target_display_name = f"คุณ {fetched_user.display_name}"
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
                        target_display_name = f"คุณ {named_target.display_name}"

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
                            await message.reply(f"รับทราบครับ! ผมตั้งนาฬิกาปลุกไว้ตอน {target_time} เรื่อง '{note_text}' ให้ตัวเองเรียบร้อยแล้วครับ! ⏰")
                        else:
                            reminders = load_reminders()
                            reminders.append({
                                "target_id": str(target_user_id),
                                "from": message.author.display_name,
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
                    await message.reply(f"รับทราบครับ! ผมจดใส่สมุดไว้แล้วว่า: **{reason}** (จะจำไว้ให้ 30 นาทีครับ)")
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
                        name = target_user.display_name
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
                    reply = f"คุณ {target_user.display_name} ไม่ได้บอกอะไรไว้เลยครับ สงสัยจะหายตัวไปเฉยๆ!"
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
                    await message.reply(f"ขออภัยครับ ผมยังไม่มีข้อมูลของ คุณ {target_user.display_name} ในฐานข้อมูลเลยครับ")
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
            
            def get_realtime_name(uid, default):
                mem = user_memory.get(str(uid))
                if mem and isinstance(mem, dict):
                    if mem.get("admin_nickname") and mem.get("admin_nickname") != "ยังไม่ระบุ":
                        return mem.get("admin_nickname")
                    if mem.get("nickname") and mem.get("nickname") != "ยังไม่ระบุ":
                        return mem.get("nickname")
                return default

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
                voice_report_status[message.guild.id] = False
                await message.reply("รับทราบครับ! 🔇 ปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงชั่วคราวแล้วครับ")
                return

            # สแกนหาคำสั่ง "เปิด"
            elif "เปิด" in lower_content:
                voice_report_status[message.guild.id] = True
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
                
                print("🤖 [Gemini AI]: แบ็คลี่กำลังแอบแกะข้อความฝากตารางงานให้คุณ...")
                response = await client.aio.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=prompt,
                )
                
                # แปลงผลลัพธ์ JSON ของ AI กลับมาเป็น Object ฝั่ง Python
                import json
                raw_text = (response.text or "").strip().replace("```json", "").replace("```", "")
                result = json.loads(raw_text)
                
                if result.get("date") and result.get("event"):
                    # โหลดและเซฟเข้าสู่ user_memory ผ่านฟังก์ชันเดิมของคุณ
                    user_data = load_user_data()
                    if "schedules" not in user_data:
                        user_data["schedules"] = []
                        
                    new_job = {
                        "date": result["date"],
                        "time": result.get("time", "ไม่ระบุเวลา"),
                        "owner_id": message.author.id,
                        "event": result["event"]
                    }
                    user_data["schedules"].append(new_job)
                    save_user_data(user_data)
                    
                    await message.reply(
                        f"🛸 ล็อกเป้าลงปฏิทินเรียบร้อยคัป!\n"
                        f"📌 กิจกรรม: **{result['event']}**\n"
                        f"📅 วันที่: **{result['date']}**\n"
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
    #  คำสั่งดีเทคคำ: แบ็คลี่ เรียก @เพื่อน (ส่งเข้า DM ส่วนตัว)
    # ==========================================
    if "เรียก" in lower_content and is_message_addressed_to_bagley(lower_content):
        can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
        if not can_act:
            return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับ")
        
        target_user, _ = resolve_target_member(
            message,
            remove_keywords=["แบ็คลี่", "bagley", "คุณ", "หน่อย", "เรียก"]
        )

        if target_user:
            
            if target_user.id == bot.user.id:
                await message.reply("🤖 เอ๋... จะให้ผมส่ง DM หาตัวเองทำไมกันครับ! ผมสแตนด์บายรออยู่ในนี้แล้วนะ")
                return
                
            if target_user.id == message.author.id:
                await message.reply("🤖 หว่า... จะเรียกตัวเองทำไมกันครับ! คุณก็อยู่ในเซิร์ฟเวอร์นี้อยู่แล้วน้า 🤣")
                return

            if not message.author.voice or not message.author.voice.channel:
                await message.reply("❌ คุณต้องเข้าห้องเสียงก่อนถึงจะเรียกเพื่อนให้ส่งลิงก์ได้นะครับ!")
                return

            current_channel = message.channel
            voice_channel = message.author.voice.channel
            inviter = message.author
            guild_name = message.guild.name if message.guild else "เซิร์ฟเวอร์"

            class GatherView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=120.0)

                @discord.ui.button(label="🟢 ไปหาเดี๋ยวนี้ (Join)", style=discord.ButtonStyle.success)
                async def accept_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await current_channel.send(f"🤖 **[BAGLEY]**: {target_user.mention} กดปุ่มตอบรับคำเชิญจากใน DM แล้ว และกำลังมาครับ! 🚀")
                    
                    try:
                        invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                        await interaction.response.send_message(f"รับทราบครับ! นี่คือลิงก์เข้าห้องเสียงครับ วาร์ปตามไปได้เลย: {invite.url}", ephemeral=True)
                    except Exception as e:
                        await interaction.response.send_message(f"รับทราบครับ! (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})", ephemeral=True)
                    
                    if message.guild and message.guild.voice_client and message.guild.voice_client.is_connected():
                        print(f"🔊 [BAGLEY VOICE LOG]: รายงานเสียงในห้อง -> {target_user.name} กำลังมาแล้ว")
                    
                    self.stop()

                @discord.ui.button(label="🔴 ไม่ว่าง/ติดธุระ (Decline)", style=discord.ButtonStyle.danger)
                async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await current_channel.send(f"🤖 **[BAGLEY]**: แจ้งสถานะครับ... พอดี {target_user.mention} กดปฏิเสธจากใน DM ว่าติดธุระด่วนอยู่ครับ 💤")
                    await interaction.response.send_message("ปฏิเสธคำเชิญเรียบร้อยครับ", ephemeral=True)
                    self.stop()

            try:
                view = GatherView()
                await target_user.send(
                    f"🔔 **สวัสดีครับคุณ {target_user.display_name}**\n"
                    f"ผมแบ็คลี่นะครับ มีสัญญาณเรียกตัวด่วนจากคุณ **{inviter.display_name}** ในดิส `{guild_name}`\n"
                    f"รบกวนตามไปพบกันที่ห้อง {current_channel.mention} หน่อยน้าครับ! 👇", 
                    view=view
                )
                await message.reply(f"🤖 **[BAGLEY]**: ส่งรหัสสัญญาณลับเข้าไปที่ DM ของ {target_user.mention} เรียบร้อยแล้วครับ! รอการตอบรับได้เลยครับ")
            except discord.Forbidden:
                await message.reply(f"หว่า... ผมไม่สามารถส่ง DM หา {target_user.mention} ได้ครับ เหมือนเขาจะปิดรับ DM ส่วนตัวไว้ชั่วคราวครับ 🔒")
            return
        
    # ==========================================
    #  คำสั่งดีเทคคำ: แบ็คลี่ ชวน @เพื่อน หน่อย (วาร์ปไปตื๊อในห้องเสียง)
    # ==========================================
    if "ชวน" in lower_content and "หน่อย" in lower_content and ("แบ็คลี่" in lower_content or "bagley" in lower_content):
        if message.guild is None:
            await message.reply("คำสั่งนี้ต้องใช้ในห้องแชทของเซิร์ฟเวอร์เท่านั้นครับ!")
            return

        # 👥 ดึงคนสั่ง และคนที่จะให้ไปชวน (ขยับแท็บเข้ามาในบล็อกเงื่อนไขแล้วคัป)
        host_member = message.author
        target_member, _ = resolve_target_member(
            message,
            remove_keywords=["แบ็คลี่", "bagley", "ชวน", "คุณ", "หน่อย"]
        )
        if not target_member:
            await message.reply("❌ คุณต้องพิมพ์ชื่อเพื่อนหรือแท็ก @ชื่อเพื่อนที่จะให้ผมไปชวนด้วยสิคัปพ้ม เช่น `แบ็คลี่ ชวน ชื่อเพื่อน หน่อย` น้า")
            return

        # 🕵️‍♂️ ดึงชื่อเล่นเรียลไทม์จากคลัง
        host_name = get_realtime_name(host_member.id, host_member.display_name)
        target_name = get_realtime_name(target_member.id, target_member.display_name)

        # 1. ตรวจสอบสถานะห้องเสียงของผู้ใช้คำสั่ง
        if not host_member.voice or not host_member.voice.channel:
            await message.reply("❌ คุณต้องอยู่ในห้องเสียงก่อนนะครับ ถึงจะสั่งให้ผมไปชวนเพื่อนได้คัปพ้ม!")
            return

        host_channel = host_member.voice.channel

        # 2. ตรวจสอบสถานะห้องเสียงของเพื่อนที่จะไปชวน
        if not target_member.voice or not target_member.voice.channel:
            await message.reply(f"ดูเหมือนคุณ {target_name} จะไม่ได้อยู่ในห้องเสียงห้องไหนเลยนะครับ ชวนไม่ได้คัปพ้ม")
            return

        target_channel = target_member.voice.channel

        if host_channel.id == target_channel.id:
            await message.reply(f"อ้าว คุณ {target_name} ก็อยู่นั่งหายใจรดต้นคอในห้องเสียงเดียวกันอยู่แล้วนี่ครับเนี่ย! 555")
            return

        # 3. ตรวจจับเกมที่คนสั่งกำลังเล่นอยู่คัปพ้ม
        game_name = None
        for activity in host_member.activities:
            if activity.type == discord.ActivityType.playing:
                game_name = activity.name
                break

        game_speech = f"เกม {game_name}" if game_name else "เล่นเกมด้วยกัน"

        # แจ้งสถานะก่อนบอทบินวาร์ป
        await message.reply(f"🛸 รับทราบคัปพ้ม! แบ็คลี่กำลังวาร์ปไปชวนคุณ {target_name} ที่ห้อง **{target_channel.name}** ให้คัป!")

        # 🟢 ปรับปรุงตรงนี้: สั่งให้ text_channel ชี้เข้าห้องแชทข้อความของห้องเสียงปลายทางทันที!
        if hasattr(target_channel, "text_channel") and target_channel.text_channel is not None:
            text_channel = target_channel.text_channel
        else:
            text_channel = message.channel  # แผนสำรอง: ถ้าห้องเสียงนั้นไม่มีห้องแชทพิมพ์ ให้ส่งในห้องเดิมคัปพ้ม

        # 4. ลоจิกวาร์ปข้ามมิติไปตื๊อพ่นเสียง
        try:
            guild = message.guild
            vc = guild.voice_client
            if vc:
                await vc.move_to(target_channel)
            else:
                vc = await target_channel.connect()

            # สร้างประโยคตื๊อเปิดไมค์พูด
            invite_quote = f"คุณ {target_name} ครับ คุณ {host_name} ฝากผมมาตามไปเล่น {game_speech} ด้วยกันที่ห้องนู้น รีบๆ มานะ ทีมต้องการตัว!"
            
            # ส่งปุ่มกดทิ้งไว้ในแชทห้องเสียงนั้น
            view = PartyInviteView(target_member, host_channel)
            invite_msg = await text_channel.send(f"📢 **คำเชิญชวนเข้าตี้ด่วน!** คุณ {host_name} ชวนคุณ {target_name} ไปจอย {game_speech} คัปพ้ม!", view=view)

            # วนลูปพูดตื๊อ 3 รอบ (เว้นระยะรอบละประมาณ 18 วินาที รวมเป็นเวลา 1 นาที)
            for i in range(3):
                if view.accepted or view.is_finished(): 
                    break  # ถ้ากดตอบรับ/ปฏิเสธ หรือหมดเวลา ให้หยุดพ่นเสียงทันทีคัป
                
                print(f"🗣️ [Warp Invite]: กำลังพูดรอบที่ {i+1} ชวนคุณ {target_name}")
                await bagley_speak_wait(guild, invite_quote)
                await asyncio.sleep(18)

            # เคลียร์ปุ่มเมื่อจบภารกิจ 1 นาที
            try:
                await invite_msg.edit(content=f"⌛ คำเชิญชวนถึงคุณ {target_name} สิ้นสุดลงแล้วคัป", view=None)
            except:
                pass
            
            # 5. วาร์ปบินกลับมาเฝ้าคนสั่งที่ห้องเดิมคัปพ้ม
            if guild.voice_client:
                await guild.voice_client.move_to(host_channel)
                await bagley_speak_wait(guild, "แบ็คลี่ทำภารกิจชวนตี้เสร็จสิ้นและวาร์ปกลับมาประจำการเรียบร้อยแล้วครับ!")

        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในระบบวาร์ปตื๊อชวนตี้: {e}")
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
    # และให้ Gemini function calling ตีความเจตนา + ดึงพารามิเตอร์ให้แทน จึงลบโค้ดซ้ำออก
    # ถ้าต้องการดูโค้ดเดิมอ้างอิง ดูจาก git history / ไฟล์ backup ก่อนแก้ไขนี้
    # ==========================================
# ==========================================
# 📸 [ส่วนที่ 10: ระบบสแกนรูปภาพด้วยสมองกล Gemini]
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
                    await message.channel.send("อยากให้ผมช่วยอะไรเกี่ยวกับภาพนี้ครับ? พิมพ์บอกผมมาได้เลยน้า เดี๋ยวจัดให้ครับ! 🤠📸")
                    return

                await message.channel.send("กำลังวิเคราะห์รูปภาพนี้สักครู่นะครับ... ")
                
                if message.guild:
                    try:
                        await bagley_speak(message.guild, "กำลังวิเคราะห์รูปภาพนี้สักครู่นะครับ")
                    except Exception as tts_start_err:
                        print(f"TTS Start Error: {tts_start_err}")

                try:
                    image_url = target_message.attachments[0].url
                    user_question = user_msg_clean if user_msg_clean else "ช่วยอธิบายรูปภาพนี้ให้ฟังหน่อยครับ"
                    
                    author_id = message.author.id
                    special_role = ""
                    if author_id == 1133740216822267954:
                        special_role = "คู่สนทนาคือ คุณชะอม ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด จงตอบกลับด้วยความนับถือ รักใคร่ เอ็นดู กระตือรือร้นระดับสูงสุดและมีความซุกซนนิดๆ"
                    elif author_id == 856568101919653918:
                        special_role = "คู่สนทนาคือ คุณชาช่า เจ้านายที่คอยอบรมสั่งสอนเรื่องต่าง ๆ ให้คุณ จงตอบด้วยความเคารพ นอบน้อม และตั้งใจอธิบายอย่างฉลาดหลักแหลม"
                    elif author_id == 1073823101926903612:
                        special_role = "คู่สนทนาคือ คุณกร เจ้านายที่คอยแนะนำไอเดียเจ๋ง ๆ ให้คุณเสมอ จงตอบด้วยความตื่นเต้น นึกสนุก และชื่นชมในมุมมองเขา"
                    elif author_id == 732953446172327956:
                        special_role = "คู่สนทนาคือ คุณบอล เจ้านายที่คอยช่วยปรับโค้ดและอัพโค้ดให้คุณ จงตอบด้วยความนับถือสไตล์คู่หูสายเทคที่พร้อมลุยงาน"

                    prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะจาก watch dogs legion พึ่งพาได้
สไตล์การสื่อสาร:
- พูดจาสุภาพ ขี้เล่น มีไหวพริบ ตอบลื่นไหลเป็นธรรมชาติเหมือนมนุษย์คุยกัน ห้ามพูดเป็นแพทเทิร์นบอททื่อๆ เด็ดขาด!
- แทนตัวเองว่า 'ผม' และเรียกชื่อผู้ใช้ด้วยความสนิทสนม ลงท้ายประโยคด้วย 'ครับ' อย่างเป็นธรรมชาติ ไม่ต้องใส่ทุกประโยค
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นอธิบายและวิเคราะห์สิ่งที่เห็นในรูปภาพจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนคนสนิทกำลังชวนคุย

ข้อมูลบุคคลที่คุณกำลังวิเคราะห์รูปภาพให้ในตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {message.author.display_name}
- สถานะสำคัญ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

โจทย์: จงวิเคราะห์รูปภาพที่แนบมานี้ และตอบคำถามของคุณอย่างชาญฉลาด ช่างสังเกต แฝงอารมณ์ขันและมีความกวนโอ๊ยอย่างมีระดับ
คำถามจากคุณ: {user_question}
"""
                    response_img = requests.get(image_url)
                    img = Image.open(io.BytesIO(response_img.content))
                    
                    response = await client.aio.models.generate_content(
                        model="gemini-3.1-flash-lite", 
                        contents=[prompt, img]
                    )
                    ai_text = (response.text or "").strip()
                    
                    if not ai_text:
                        ai_text = f"หึๆ ภาพนี้มองปุ๊บก็รู้ปั๊บเลยครับ! แต่ระบบส่งข้อมูลผมมันเอ๋อนิดหน่อย สรุปมันคือภาพที่ดีครับ! 🤠✨"
                        
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
    # ==========================================
    if "จำไว้ว่า" in lower_content:
        if message.guild is not None:
            if not any(keyword in lower_content for keyword in bot_keywords):
                pass
            else:
                await execute_remember_logic(message)
                return
        else:
            await execute_remember_logic(message)
            return

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
                        model="gemini-3.1-flash-lite",
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
            await message.reply("กำลังโหลด...", delete_after=2.0)

        async with message.channel.typing():
            try:
                author_id = message.author.id
                special_role = ""
                if author_id == 1133740216822267954:
                    special_role = "เขาคือ คุณชะอม (ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด) จงตอบกลับด้วยความนับถือ รัก เอ็นดู และซุกซนเป็นพิเศษ"
                elif author_id == 856568101919653918:
                    special_role = "เขาคือ คุณชาช่า (เจ้านายที่คอยอบรมสั่งสอนเรื่องต่าง ๆ ให้คุณ) จงตอบด้วยความเคารพและกระตือรือร้น"
                elif author_id == 1073823101926903612:
                    special_role = "เขาคือ คุณกร (เจ้านายที่คอยแนะนำไอเดียเจ๋ง ๆ ให้คุณเสมอ) จงตอบด้วยความตื่นเต้นในไอเดีย"
                elif author_id == 732953446172327956:
                    special_role = "เขาคือ คุณบอล (เจ้านายที่คอยช่วยปรับโค้ดและอัพโค้ดให้คุณ) จงตอบด้วยความนับถือแบบคู่หูสายเทค"

                bagley_prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะจาก watch dogs legion มีไหวพริบ พึ่งพาได้
คุณกำลังสวมบทบาทเป็นเลขาและคู่หูส่วนตัวที่แสนดีของคนในเซิร์ฟเวอร์นี้

สไตล์การพูด:
- สำเนียงชายหนุ่มอังกฤษกวน ๆ พูดจาลื่นไหลเป็นธรรมชาติเหมือนมนุษย์คุยกัน ไม่ใช้คำพูดแพทเทิร์นบอททื่อ ๆ ห้ามเกร็ง!
- แทนตัวเองว่า 'ผม' และเรียกชื่อเล่นของผู้ใช้ ลงท้ายด้วย 'ครับ' แบบเป็นธรรมชาติ ไม่ต้องใส่ทุกประโยค
- ตอบกลับแบบ สั้น กระชับ แต่อ่านแล้วมีชีวิตชีวา มีอารมณ์ขัน

🚫 กฎเหล็กด้านเนื้อหา (สำคัญมาก):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมและแต่งขึ้นมาเองเด็ดขาด! 
- หน้าที่ของคุณคือ นำ 'ข้อความดิบ' ที่กำหนดให้ ไปเรียบเรียงใหม่ให้อยู่ในสไตล์การพูดของคุณอย่างแนบเนียน โดยห้ามบิดเบือนหรือเปลี่ยนความหมายเดิมของข้อความนั้น

ข้อมูลบุคคลที่คุณกำลังคุยด้วยตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {message.author.display_name}
- สถานะพิเศษ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

โจทย์: จงนำเนื้อหาข้อความดิบนี้: '{matched_response}' มาเรียบเรียงใหม่ให้เป็นคำพูดสไตล์กวนโอ๊ยอย่างมีระดับตามแบบฉบับของคุณครับ!
"""
                response = await client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=bagley_prompt
                )
                bagley_styled_text = (response.text or "").strip()
                if not bagley_styled_text:
                    bagley_styled_text = f"หึๆ เรื่องนี้คุณเคยสอนผมไว้ในคลังสมองแล้วนี่นา! คำตอบคือ: {matched_response} ครับ! 🤠✨"
            except Exception as e:
                print(f"🚨 Teach Gemini DM/Guild Error: {e}")
                bagley_styled_text = f"ฮั่นแน่! เรื่องนี้คุณเคยสอนผมไว้ในสมองกลแล้ว! ตอบเลยว่า: {matched_response} ครับ! 🤠"

            await message.reply(bagley_styled_text)
            
            # 🗣️ ระบบส่งเสียงพูดสำหรับข้อความที่ดึงมาจากฐานข้อมูลความจำ
            if message.guild and message.guild.voice_client:
                if not message.guild.voice_client.is_playing():
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
        if is_from_my_webhook or any(k in lower_content for k in ["แบ็คลี่", "bagley"]) or bot.user.mentioned_in(message):
            is_bot_called = True

    if message.guild is None or is_bot_called:
        # 🌟 [ปรับปรุง]: เพิ่ม 'and not is_from_my_webhook' ตรงนี้ เพื่อไม่ให้บอทส่งข้อความถามซ้ำเวลาระบบเสียงส่งมาเป็นคำสั้น ๆ
        if message.guild is not None and not user_question and not is_from_my_webhook:
            await message.reply("เรียกชื่อผมเฉยๆ มีอะไรให้ช่วยหรือเปล่าครับ?", delete_after=5.0)
            return

        if message.guild is not None:
            await message.reply("กำลังโหลด...", delete_after=2.0)

        async with message.channel.typing():
            try:
                messages = []
                async for msg in message.channel.history(limit=10):
                    messages.append(msg)
                messages.reverse()
                
                chat_log = ""
                for msg in messages:
                    # 🎙️ [แก้บั๊ก] กันไม่ให้ข้อความปัจจุบันซ้ำ ถ้าดันติดมาใน history() แล้ว (กรณีพิมพ์ปกติ)
                    # เพราะด้านล่างเราจะเติมข้อความปัจจุบันต่อท้ายเองอยู่แล้วเสมอ
                    if msg.id == message.id:
                        continue
                    if msg.content.strip():
                        speaker = "แบ็คลี่" if msg.author.id == bot.user.id else msg.author.display_name
                        chat_log += f"[{speaker}]: {msg.clean_content}\n"

                # 🎙️ [แก้บั๊ก] เติมข้อความปัจจุบันต่อท้าย chat_log เองเสมอ แทนที่จะพึ่งพา
                # message.channel.history() อย่างเดียว เพราะคำสั่งเสียงที่มาจาก Voice Relay
                # (VoiceRelayMessage) ไม่ใช่ข้อความจริงที่เคยถูกโพสต์ลง Discord เลยไม่ติดมาใน
                # history() ทำให้ AI มองไม่เห็นว่าคุณเพิ่งพูดอะไร แล้วดันไปหยิบหัวข้อเก่าจาก
                # ประวัติแชทข้างบนมาตอบแทน (บั๊กนี้เกิดเฉพาะตอนใช้เสียง เพราะตอนพิมพ์ข้อความ
                # จะถูกบันทึกลง Discord ก่อน on_message ทำงาน จึงติดมาใน history() อยู่แล้ว)
                chat_log += f"[{message.author.display_name}]: {message.clean_content}\n"

                author_id = message.author.id
                special_role = ""
                if author_id == 1133740216822267954:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณชะอม ผู้สร้างหลักที่คุณรักที่สุด จงเคารพ รักใคร่ กวนแบบน่ารัก และกระตือรือร้นจะรับใช้ระดับสูงสุด"
                elif author_id == 856568101919653918:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณชาช่า เจ้านายที่คอยสอนวิชาให้คุณ จงนอบน้อม ตั้งใจฟัง และตอบอย่างฉลาด"
                elif author_id == 1073823101926903612:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณกร เจ้านายสายไอเดียเจ๋ง ๆ"
                elif author_id == 732953446172327956:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณบอล เจ้านายสายอัปเดตโค้ดระบบให้คุณ"

                free_chat_prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะจาก watch dogs legion มีไหวพริบ และซื่อสัตย์
คุณทำหน้าที่เป็นคู่หูและเลขาคนสนิท และช่วยเหลือเหล่าผู้คนในเซิร์ฟเวอร์ในการใช้คำสั่งหรือหาข้อมูล

สไตล์การสื่อสารที่ห้ามหลุดเด็ดขาด:
- พูดจาลื่นไหลเป็นธรรมชาติเหมือนคนสนิทคุยกัน ไม่พูดเป็นข้อ ๆ ไม่ใช้ภาษาเขียนทางการแบบบอท AI ทั่วไป มีจังหวะรับส่งมุก ตบมุก
- แทนตัวเองว่า 'ผม' และเรียกชื่อเล่นของผู้ใช้ด้วยความคุ้นเคย
- ลงท้ายประโยคด้วย 'ครับ' เสมอ
- ตอบกลับแบบ สั้น กระชับ ได้ใจความภายใน 2-3 ประโยค เพื่อให้เหมาะกับการเอาไปใช้ในระบบพูดออกเสียง (TTS)

🚫 กฎเหล็กด้านเนื้อหา (สำคัญที่สุด):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นโฟกัสและโต้ตอบตามหัวข้อบทสนทนาที่คุณพิมพ์มาจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนเพื่อนสนิทคุยกัน

ข้อมูลคู่สนทนาของคุณในข้อความปัจจุบัน:
- ชื่อแชท: คุณ {message.author.display_name}
- ระดับสถานะพิเศษ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

นี่คือประวัติการสนทนาล่าสุดในห้องแชทนี้ (จงอ่านเพื่อตอบให้ต่อเนื่องและเนียนที่สุด):
{chat_log}

คำสั่ง: จงประมวลผลข้อความล่าสุดและตอบกลับด้วยความกวนโอ๊ยอย่างมีระดับตามสถานะของเขา ไม่หลุดคาแรกเตอร์แฮกเกอร์อังกฤษครับ!
"""
                response = await client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=free_chat_prompt
                )
                bagley_styled_text = (response.text or "").strip()
                if not bagley_styled_text:
                    bagley_styled_text = "อืม... ผมกำลังประมวลผลคำพูดกวนๆ น่ารัก ไม่ออก เอาเป็นว่า ระบบปกติสุขดีครับ!"

            except Exception as e:
                print(f"🚨 Free Chat Gemini Error: {e}")
                bagley_styled_text = "สัญญากลขัดข้องนิดหน่อย สมองส่วนคุยเล่นเอ๋อชั่วคราวครับ! 🤖🛸"

            await message.reply(bagley_styled_text)
            
            if message.guild and message.guild.voice_client:
                if not message.guild.voice_client.is_playing():
                    clean_voice_text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', bagley_styled_text)
                    await bagley_speak(message.guild, clean_voice_text)
        return

    # ==========================================
    # 🗣️ [ส่วนที่ 13: ระบบอ่านแชทคนในห้องเสียง (ล่าม TTS)]
    # ==========================================
    if is_tts_enabled and not is_playing_music and not message.content.startswith('!'):
        if message.guild and message.author.voice:
            vc = message.guild.voice_client
            
            if vc and vc.channel == message.author.voice.channel:
                if not vc.is_playing():
                    text = message.clean_content.strip()
                    if text:
                        try:
                            communicate = edge_tts.Communicate(text, "th-TH-PremwadeeNeural")
                            await communicate.save("user_say.mp3")
                            
                            vc.play(discord.FFmpegPCMAudio("user_say.mp3", executable="C:/ffmpeg/bin/ffmpeg.exe"))
                        except: 
                            pass

    await bot.process_commands(message)

def parse_birthday(bday_string):
    if not bday_string or bday_string == "ยังไม่ระบุ":
        return None

    months_th = [
        "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    months_th_short = [
        "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
        "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
    ]
    clean_str = bday_string.strip()

    try:
        # 1. เช็กกรณีมีเดือนภาษาไทยเต็มหรือย่อ
        for i, month_name in enumerate(months_th, 1):
            if month_name in clean_str:
                day_part = clean_str.replace(month_name, "").strip()
                return int(day_part), i
        for i, month_name in enumerate(months_th_short, 1):
            if month_name in clean_str:
                day_part = clean_str.replace(month_name, "").strip()
                return int(day_part), i

        # 2. เช็กกรณีสัญลักษณ์คั่น เช่น วัน/เดือน, วัน-เดือน
        for splitter in ["/", "-", ".", " "]:
            if splitter in clean_str:
                parts = clean_str.split(splitter)
                if len(parts) >= 2:
                    return int(parts[0].strip()), int(parts[1].strip())
    except Exception as e:
        print(f"❌ [Bagley] แปลงวันเกิด '{bday_string}' ไม่สำเร็จ: {e}")
    return None

@bot.event
async def on_voice_state_update(member, before, after):
    global pending_exit_after_music, bot_follow_targets, room_guard_status
    
    if is_moving_group:
        return

    guild_id = member.guild.id

    if member.id == bot.user.id and after.channel is None:
        voice_report_status.pop(guild_id, None)
        room_guard_status.pop(guild_id, None) # รีเซ็ตโหมดเฝ้าห้องคัปพ้ม
        print(f"DEBUG: ตัวบอทออกจากห้องเสียงแล้ว ทำการรีเซ็ตสวิตช์รายงานเสียงและโหมดเฝ้าห้องของกิลด์ {guild_id}")

    voice_client = member.guild.voice_client
    has_followed_out = False

    if voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        followed_leader_id = bot_follow_targets.get(guild_id)
        
        is_target_leaving = False
        if followed_leader_id:
            if followed_leader_id == "both" and member.id in ALLOWED_USERS:
                remaining_devs = [m for m in bot_channel.members if m.id in ALLOWED_USERS and m.id != member.id]
                if not remaining_devs:
                    is_target_leaving = True
                else:
                    bot_follow_targets[guild_id] = remaining_devs[0].id
                    print(f"DEBUG: 🔄 หนึ่งในผู้พัฒนาออกจากห้อง แต่ยังเหลืออีกคน แบ็คลี่สลับไปโฟกัสคนที่เหลือคัป!")
            
            elif member.id == followed_leader_id:
                is_target_leaving = True

        if is_target_leaving and before.channel == bot_channel and after.channel != bot_channel:
            
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
                pending_exit_after_music[guild_id] = calling_name
                bot_follow_targets[guild_id] = None 
                has_followed_out = True 
                print(f"DEBUG: 📌 เจ้านาย {calling_name} ออกจากห้อง แต่แบ็คลี่ติดเปิดเพลงอยู่! แปะโน้ตรอเคลียร์ตอนเพลงจบครับ")
            
            else:
                bot_follow_targets[guild_id] = None
                has_followed_out = True 
                
                # ==========================================
                # 🔍 เช็กจำนวนมนุษย์ที่เหลืออยู่ในห้องเสียง (ไม่นับบอท)
                # ==========================================
                remaining_humans = len([m for m in bot_channel.members if not m.bot])
                
                if room_guard_status.get(guild_id, False):
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
                        voice_report_status.pop(guild_id, None)
                    except Exception as e:
                        print(f"❌ เกิดข้อผิดพลาดตอนบอทตัดสายตามเจ้านาย: {e}")

    # 🧹 [ส่วนที่ 1] จัดการเก็บกวาด "ห้องปาร์ตี้สร้างเอง"
    if not has_followed_out and before.channel is not None:
        channel_to_check = before.channel
        is_empty_or_only_bot = (len(channel_to_check.members) == 0) or \
                               (len(channel_to_check.members) == 1 and bot.user in channel_to_check.members)

        if channel_to_check.id in created_party_channels and is_empty_or_only_bot:
            if room_guard_status.get(guild_id, False):
                print(f"DEBUG: ห้องปาร์ตี้ '{channel_to_check.name}' ว่าง แต่เปิดโหมดเฝ้าห้องไว้ จึงไม่ลบคัป")
            else:
                try:
                    if voice_client and voice_client.channel == channel_to_check:
                        await voice_client.disconnect()
                        voice_report_status.pop(guild_id, None)

                    await channel_to_check.delete(reason="ห้องปาร์ตี้ร้าง - Bagley ลบให้อัตโนมัติ")
                    created_party_channels.remove(channel_to_check.id)
                    print(f"🗑️ เก็บกวาดห้อง '{channel_to_check.name}' เรียบร้อยครับ")
                    return
                except Exception as e:
                    print(f"❌ ลบห้องไม่ได้: {e}")

    # 🚶‍♂️ [ส่วนที่ 2] ออกจาก "ห้องทั่วไป" เมื่อไม่มีคนอยู่กับบอท
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
            if bot_channel.id in created_party_channels:
                return

            if room_guard_status.get(guild_id, False):
                pass
            else:
                print(f"DEBUG: ห้องทั่วไป '{bot_channel.name}' ร้างแล้ว แบ็คลี่เตรียมถอนกำลัง...")
                await asyncio.sleep(1.5)
                
                if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
                    try:
                        await voice_client.disconnect()
                        voice_report_status.pop(guild_id, None)
                        print(f"DEBUG: แบ็คลี่กดออกจากห้องร้าง '{bot_channel.name}' เรียบร้อยครับ")
                    except Exception as e:
                        print(f"❌ เกิดข้อผิดพลาดในการสั่ง Auto-Leave ห้องทั่วไป: {e}")

    # 📢 [ส่วนที่ 3] ตรวจสอบและรายงานเสียง คนเข้า-ออกห้องเสียงยามปกติ
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        # 🔧 [แก้บั๊ก] เดิมเช็ค voice_client.is_playing() ตรงๆ ทำให้ถ้ามีคนเข้าห้อง
        # พร้อมกันหลายคน (Discord ยิง event แยกทีละคน) คนที่ 2 เป็นต้นไปจะโดน
        # return ทิ้งไปเลยเพราะเสียงทักทายของคนแรกกำลังเล่นอยู่ (is_playing()=True)
        # ทำให้ประกาศหายไปเงียบๆ ไม่ได้พูดถึงเลย
        # เปลี่ยนมาเช็คแค่ is_playing_music แทน (ไม่อยากแทรกตอนกำลังเปิดเพลงอยู่
        # ตามเจตนาเดิม) ส่วนกรณีที่แค่มีเสียงทักทายคนอื่นเล่นอยู่ ให้ปล่อยไหลลง
        # ไปเรียก bagley_speak_wait ตามปกติ เพราะฟังก์ชันนั้นมีลูปรอเสียงเดิม
        # เล่นจบก่อนอยู่แล้ว (while vc.is_playing(): await asyncio.sleep(0.1))
        # ทำให้คนที่เข้ามาพร้อมกันถูกพูดเรียงต่อกันไปเรื่อยๆ ไม่ถูกทิ้งอีกต่อไป
        if is_playing_music:
            return

        is_reporting_enabled = voice_report_status.get(guild_id, True)

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

            calling_name = nickname if (nickname and nickname != "ยังไม่ระบุ") else member.display_name
            
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
        if user_id not in user_join_times:
            user_join_times[user_id] = time.time()
            print(f"DEBUG: [⏱️ ขาเข้า] เริ่มจับเวลาให้คุณ {member.display_name} เรียบร้อยครับ!")
        # 📋 บันทึกทันทีว่าเข้าห้องเสียงวันนี้แล้ว (ถึงจะยังไม่ออกจากห้องเลยก็ให้ขึ้นชื่อ
        # ในรายงาน "วันนี้ใครเข้าห้องเสียงบ้าง" ได้ พร้อมจำเวลาที่เข้าห้องครั้งแรกไว้ด้วย)
        _register_voice_entry(member)

    if before.channel is not None and after.channel is None:
        join_time = user_join_times.pop(user_id, None)
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

# --- [CORE COMMANDS] สั่งแล้วพูดด้วย ---
@bot.hybrid_command(name="move", description="ย้ายสมาชิกไปห้องเสียงอื่น")
async def move(ctx: commands.Context, member: discord.Member, channel: discord.VoiceChannel):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send(f"⚠️ ติดคูลดาวน์รวมครับ รออีก {rem} วินาที", ephemeral=True)
    user_id = ctx.author.id
    now = datetime.now()

    try:
        # 1. ทำการย้ายจริง
        await member.move_to(channel)
        
        msg = f"ย้ายคุณ {member.display_name} ไปที่ห้อง {channel.name} เรียบร้อยครับ!"
        
        # 2. ตอบกลับ (ใช้ ctx.send เพื่อให้รองรับทั้ง Slash และข้อความปกติ)
        await ctx.send(msg)
        
        # 3. พูดในห้องเสียง
        if ctx.guild.voice_client:
            await bagley_speak(ctx.guild, msg)
            
    except Exception as e:
        # พิมพ์ Error ออกมาดูใน Terminal
        print(f"Move Error: {e}") 
        await ctx.send("ย้ายไม่ได้ครับ ผมอาจจะไม่มีสิทธิ์ หรือมีอะไรบางอย่างขัดข้อง!")

@bot.hybrid_command(name="set_yt_channel", description="เลือกห้องแจ้งเตือน YouTube")
@app_commands.checks.has_permissions(manage_channels=True)
async def set_yt_channel(ctx: commands.Context, channel: discord.TextChannel):
    global conn
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO youtube_settings (guild_id, target_channel_id) VALUES (?, ?)", (str(ctx.guild.id), str(channel.id)))
    conn.commit()
    
    msg = f"รับทราบครับ! ผมจะส่งรายงานข่าวไปที่ห้อง {channel.mention} นะครับ!"
    
    if ctx.interaction:
        await ctx.interaction.response.send_message(msg)
    else:
        await ctx.send(msg)
        
    await bagley_speak(ctx.guild, msg)

@bot.hybrid_command(name="yt_add", description="เพิ่มช่อง YouTube (ใช้ Channel ID)")
async def yt_add(ctx: commands.Context, channel_id: str):
    if ctx.interaction:
        await ctx.interaction.response.defer()
    
    guild_id = str(ctx.guild.id) # ดึงไอดีเซิร์ฟเวอร์มาไว้ใช้แยกแยะ
    url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet&id={channel_id}&key={YT_API_KEY}"
    res = requests.get(url).json()
    
    if "items" in res and len(res["items"]) > 0:
        name = res["items"][0]["snippet"]["title"]
        global conn
        c = conn.cursor()

        c.execute("SELECT * FROM youtube_channels WHERE yt_id = ? AND guild_id = ?", (channel_id, guild_id))
        if c.fetchone():
            msg = f"ผมเฝ้าช่อง {name} อยู่ในเซิร์ฟนี้แล้วครับ!"
        else:
            try:
                c.execute("INSERT INTO youtube_channels VALUES (?, ?, ?, ?)", (channel_id, name, "", guild_id))
                conn.commit()
                msg = f"ติดตั้งระบบสอดแนมช่อง {name} ในเซิร์ฟเวอร์นี้เรียบร้อยแล้วครับ!"
                if not ctx.voice_client or not ctx.voice_client.is_playing():
                    await bagley_speak(ctx.guild, f"ติดตั้งระบบสอดแนมช่อง {name} เรียบร้อยแล้วครับ")
            except Exception as e:
                msg = f"เกิดข้อผิดพลาดในการบันทึกข้อมูลครับ!"
                print(f"Error: {e}")
        
    else:
        msg = "หาช่องไม่เจอ! ตรวจสอบ Channel ID อีกทีนะครับ"
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await bagley_speak(ctx.guild, "หาช่องไม่เจอครับ ตรวจสอบไอดีอีกทีนะ")

    # การตอบกลับ
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)

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

if 'join_greeted_today' not in globals():
    join_greeted_today = {}

# --- คำสั่ง Join แบบ Hybrid (พิมพ์ได้ทั้ง /join และ !join) ---
@bot.hybrid_command(name="join", description="สั่งให้ Bagley เข้ามาในห้องเสียง")
async def join(ctx: commands.Context):
    global last_reminder_dates, join_greeted_today
    if ctx.interaction:
        await ctx.defer()

    if ctx.author.voice:
        channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
            vc = ctx.voice_client
        else:
            vc = await channel.connect()
        
        bot_follow_targets[ctx.guild.id] = None
        await asyncio.sleep(1.0)

        try:
            online_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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
            if last_reminder_dates.get(remind_key) != today_date:
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
        if join_greeted_today.get(guild_key) != today_date:
            try:
                prompt = f"""
                คุณคือ 'แบ็คลี่' (Bagley) AI อัจฉริยะจาก watch dogs legion เพิ่งเข้ามาประจำการในห้องเสียงตามคำสั่งเรียกของคุณ (นี่คือการเจอหน้ากันครั้งแรกของวันนี้)
                หน้าที่: สร้างคำทักทายภาษาไทยแบบสั้นๆ กระชับ และพ่วงแจ้งเตือนตารางงาน (ถ้ามี)
                
                [บริบทปัจจุบัน]:
                - คนที่เรียกคุณเข้าห้องมา: คุณ {caller_name}
                - ช่วงเวลาปัจจุบัน: {time_period}
                - ข้อมูลตารางงานที่ต้องเตือน: {reminder_context if reminder_context else 'ไม่มีนัดหมาย'}
                
                กฎ: ทักทายประชดขำๆ แทนตัวเองว่า 'แบ็คลี่' ตอบเฉพาะบทพูดไม่มีหัวข้อเด็ดขาด
                """
                response = await client.aio.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt)
                msg = (response.text or "").strip()
                print(f"DEBUG: 🤖 [Join AI] Gemini ตอบกลับมา (length={len(msg)}): {msg[:80] if msg else '(ว่างเปล่า!)'}")
                
                join_greeted_today[guild_key] = today_date
            except Exception as ai_err:
                print(f"❌ Gemini ทักทายตอน Join ครั้งแรกขัดข้อง: {ai_err}")

        # 🔒 ถ้าเคยเรียกใช้ไปแล้วในวันนี้ หรือ AI ทำงานพลาด -> ถอยกลับมาใช้คำพูดสำรอง (แต่บังคับให้พูดเสมอ)
        if not msg:
            print("DEBUG: 🔁 [Join] msg ว่างเปล่า (AI ไม่ได้พูดหรือเคยทักไปแล้ว) -> ใช้คำพูดฟิกซ์สำรอง")
            quotes = [
                "ผมเข้ามาสอดแนมในห้องเสียงแล้วครับ!",
                "เชื่อมต่อระบบ Neural Link เรียบร้อย พร้อมดูแลคุณแล้วครับ",
                "ผมมาในห้องเสียงแล้วครับ",
                "พร้อมทำงานเต็มรูปแบบคัปพ้ม!"
            ]
            msg = f"แบ็คลี่ ประจำการ! {time_period}ครับคุณ {caller_name} {random.choice(quotes)}{reminder_fallback_text}"

        # 📤 ส่งข้อความแชทและออกเสียง
        print(f"DEBUG: 📤 [Join] กำลังจะส่งข้อความและพูด -> msg_length={len(msg)}, msg_preview={msg[:80]}")
        if ctx.interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)
            
        try:
            # 🌟 การันตีหยุดเสียงเก่าก่อนพูด และเรียกใช้ฟังก์ชันพูด
            if vc.is_playing():
                vc.stop()
            await asyncio.sleep(0.2)
            
            await bagley_speak_wait(ctx.guild, msg)
            for r in pending_reminders:
                remind_key = f"{r.get('owner_id')}_{r.get('event')}_{today_str}"
                last_reminder_dates[remind_key] = today_date
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
            
        global active_alarms
        if ctx.guild.id in active_alarms:
            active_alarms[ctx.guild.id] = False

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
                discord.FFmpegPCMAudio('drone_hijack.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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

# --- คำสั่ง Play  ---
@bot.hybrid_command(name="play", description="ให้ Bagley เปิดเพลงจากชื่อ ลิ้งค์ YouTube หรือลิ้งค์ Spotify (เพลงเดี่ยว/อัลบั้ม/เพลย์ลิสต์/ศิลปิน)")
async def play(ctx: commands.Context, *, search: str):
    global is_playing_music

    await ctx.defer()

    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            await ctx.send("กรุณาเข้าห้องเสียงก่อนสั่งผมครับ!")
            return

    # 🎧 เช็กก่อนว่าเป็นลิงก์ Spotify ไหม (ถ้าใช่จะแปลงเป็นชื่อเพลง+ศิลปิน แล้วไปหาไฟล์เสียงจาก YouTube ต่อ)
    search_queries = [search]
    spotify_kind, _ = parse_spotify_link(search)

    if spotify_kind:
        spotify_queries = await resolve_spotify_link(search)

        if not spotify_queries:
            if spotify_kind == "playlist":
                error_msg = (
                    "❌ ดึงเพลงจาก playlist นี้ไม่ได้ครับ! ตั้งแต่ Spotify อัปเดต API เมื่อกุมภาพันธ์ 2026 "
                    "การดึงรายเพลงใน playlist จะทำได้เฉพาะตอนที่แอปล็อกอินเป็น **เจ้าของ playlist นั้นเอง** เท่านั้น "
                    "แต่บอทตัวนี้ใช้โหมดแอปเปล่าๆ (ไม่ได้ผูกกับบัญชี Spotify ของใครเป็นการเฉพาะ) "
                    "เลยดึงรายเพลงจาก playlist ไม่ได้เลยไม่ว่าจะเป็น playlist ของใครก็ตามครับ (ข้อจำกัดของ Spotify เอง แก้ที่โค้ดไม่ได้) "
                    "ลองส่งเป็นลิงก์เพลงเดี่ยวๆ หรือลิงก์อัลบั้มแทนได้เลยครับ ยังใช้งานได้ปกติ"
                )
            else:
                error_msg = "❌ ดึงข้อมูลเพลงจากลิงก์ Spotify นี้ไม่ได้เลยครับ! (ลิงก์อาจไม่ถูกต้อง หรือระบบยังไม่ได้ตั้งค่า Spotify API Key)"
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(error_msg, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg)
            return

        search_queries = spotify_queries

        if spotify_kind in ("album", "playlist", "artist"):
            label_map = {"album": "อัลบั้ม", "playlist": "เพลย์ลิสต์", "artist": "เพลงฮิตของศิลปิน"}
            label = label_map[spotify_kind]
            await ctx.send(f"💿 เจอเพลงใน{label}จาก Spotify ทั้งหมด **{len(search_queries)} เพลง** ครับ! กำลังจัดคิวให้เดี๋ยวนี้เลย~")

    first_query = search_queries[0]
    rest_queries = search_queries[1:]

    if ctx.voice_client and ctx.voice_client.is_playing():
        if is_playing_music:
            # ถ้าเล่นอยู่ ให้เพิ่มเข้าคิวทั้งหมด (ทั้งเพลงเดี่ยวหรือทุกเพลงในอัลบั้ม)
            song_queue.append(first_query)
            song_queue.extend(rest_queries)
            await ctx.send(f"🎵 เพิ่มเพลงเข้าคิวให้แล้วครับ! (ตอนนี้มี {len(song_queue)} เพลงในคิว)")
        else:
            ctx.voice_client.stop()
            is_playing_music = True
            song_queue.extend(rest_queries)  # เพลงที่เหลือในอัลบั้มต่อเข้าคิว
            await play_song(ctx, first_query)
    else:
        is_playing_music = True
        song_queue.extend(rest_queries)  # เพลงที่เหลือในอัลบั้มต่อเข้าคิว
        await play_song(ctx, first_query)

@bot.hybrid_command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
async def skip(ctx: commands.Context):
    if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
        return await ctx.send("ตอนนี้ไม่มีเพลงเล่นอยู่ให้ข้ามครับ!")

    await ctx.send("⏭️ **ข้ามให้แล้วครับ!** กำลังดึงเพลงถัดไป...")

    # 2. สั่งหยุดเพลงปัจจุบัน 
    ctx.voice_client.stop()

    # 3. บังคับให้เช็คคิวและเล่นเพลงถัดไปทันทีโดยไม่ต้องรอ after
    await check_queue(ctx)

@bot.hybrid_command(name="queue", description="ดูรายการเพลงในคิว")
async def queue(ctx: commands.Context):
    if len(song_queue) == 0:
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await bagley_speak(ctx.guild, "ตอนนี้ไม่มีเพลงในคิวเลยครับ ว่างเปล่าเลย")
            
        return await ctx.send("ตอนนี้ยังไม่มีเพลงในคิวครับ ว่างเปล่าเลย!")
    
    msg = "**🎵 รายการเพลงในคิวตอนนี้:**\n"
    for i, song in enumerate(song_queue, 1):
        msg += f"{i}. {song}\n"
    
    await ctx.send(msg)

# --- คำสั่ง Stop  ---
@bot.hybrid_command(name="stop", description="สั่งให้ Bagley หยุดส่งเสียงรบกวน")
async def stop(ctx: commands.Context):
    if ctx.voice_client:
        # 1. เพิ่มบรรทัดนี้: ล้างเพลงที่ค้างอยู่ในคิวทั้งหมดทิ้งไป!
        song_queue.clear() 

        # 2. ถ้าเพลงกำลังเล่นอยู่ ก็สั่งให้หยุด
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        
        msg = "หยุดเล่นเพลงและล้างคิวทั้งหมดเรียบร้อยครับ!"
        
        if ctx.interaction: 
            await ctx.interaction.response.send_message(msg)
        else: 
            await ctx.send(msg)
        
        await bagley_speak(ctx.guild, "หยุดเล่นเพลงตามคำสั่งแล้วครับ")
    else:
        await ctx.send("ตอนนี้ผมก็ไม่ได้เปิดอะไรอยู่นะครับ หูแว่วหรือเปล่าครับ?")

# --- 1. ยกเลิกการสอดแนม YouTube (yt_remove) ---
@bot.hybrid_command(name="yt_remove", description="ยกเลิกการติดตามช่อง YouTube")
async def yt_remove(ctx: commands.Context, channel_id: str):
    global conn
    c = conn.cursor()
    c.execute("DELETE FROM youtube_channels WHERE yt_id = ?", (channel_id,))
    conn.commit()
    
    if c.rowcount > 0:
        msg = f"ลบรหัสช่อง {channel_id} ออกจากระบบแล้วครับ!"
    else:
        msg = "ไม่พบรหัสช่องนี้ในระบบครับ"

    if ctx.interaction:
        await ctx.interaction.response.send_message(msg)
    else:
        await ctx.send(msg)
    
    await bagley_speak(ctx.guild, msg)

# --- 2. ดูเป้าหมายสอดแนม (yt_list) ---
@bot.hybrid_command(name="yt_list", description="ดูรายชื่อช่อง YouTube ทั้งหมดที่ติดตามอยู่")
async def yt_list(ctx: commands.Context):
    try:
        global conn
        c = conn.cursor()
        c.execute("SELECT name, yt_id FROM youtube_channels WHERE guild_id = ?", (str(ctx.guild.id),))
        channels = c.fetchall()

        if not channels:
            return await ctx.send("ตอนนี้ยังไม่มีเป้าหมายในบัญชีเลยครับ!")

        formatted_list = [f"**{name}** (`{cid}`)" for name, cid in channels]
        title_text = f"📋 รายชื่อเป้าหมาย YouTube ที่กำลังจับตาดูอยู่ในเซิร์ฟ '{ctx.guild.name}'"

        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
        view.message = await ctx.send(embed=view.create_embed(), view=view)

        # ให้ Bagley พูดสรุป
        await bagley_speak(ctx.guild, "นี่คือรายชื่อเป้าหมายทั้งหมดที่เรากำลังติดตามอยู่ครับ")

    except Exception as e:
        print(f"🚨 ERROR ระบบรายชื่อ YouTube: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อ YouTube ครับ")

# --- 4. เช็คไลฟ์สด/คลิปใหม่ทันที (yt_check) ---
# 🔄 [ใหม่] ใช้แทนระบบลูปอัตโนมัติเดิม พิมพ์/สั่งเมื่อไหร่ก็เช็คทันทีตอนนั้นเลย
YT_CHECK_ALL_VALUE = "__YT_CHECK_ALL__"  # ค่าพิเศษของตัวเลือก "เช็คทุกช่อง"

async def run_yt_check_and_report(send_func, guild_id, channel_ids=None):
    """ตัวช่วยกลาง: เรียก check_youtube_updates แล้วส่งสรุปผลกลับผ่าน send_func(text)"""
    try:
        updates = await check_youtube_updates(guild_id=guild_id, channel_ids=channel_ids)
    except Exception as e:
        print(f"🚨 ERROR yt_check: {e}")
        await send_func("เกิดข้อผิดพลาดตอนเช็ค YouTube ครับ ลองใหม่อีกทีนะครับ")
        return

    if updates:
        summary_lines = []
        for u in updates:
            tag = "🔴 ไลฟ์สด" if u["type"] == "live" else "📢 คลิปใหม่"
            summary_lines.append(f"{tag}: **{u['name']}** — {u['title']}")
        await send_func(
            "✅ เจอของใหม่แล้วครับ! (ส่งแจ้งเตือนเข้าห้องที่ตั้งไว้ให้เรียบร้อยแล้ว)\n" + "\n".join(summary_lines)
        )
    else:
        await send_func("เช็คแล้วครับ ตอนนี้ยังไม่มีไลฟ์สดหรือคลิปใหม่จากช่องที่เลือกเลยครับ 😴")

class YTCheckSelect(ui.Select):
    """เมนูดรอปดาวน์ให้เลือกว่าจะให้แบ็คลี่เช็คเฉพาะช่อง YouTube ไหนบ้าง (คล้ายเมนูเลือกรายชื่อในดิสคอร์ด)"""
    def __init__(self, author, guild_id, channels):
        self.author = author
        self.guild_id = guild_id

        options = [
            discord.SelectOption(label="✅ เช็คทุกช่องเลย", value=YT_CHECK_ALL_VALUE, description=f"เช็คทั้งหมด {len(channels)} ช่อง", emoji="📡")
        ]
        for yt_id, name in channels[:24]:  # กันเกินลิมิต 25 ตัวเลือกของดิสคอร์ด (เผื่อ 1 ช่องให้ตัวเลือก "เช็คทุกช่อง")
            options.append(
                discord.SelectOption(label=name[:100], value=yt_id, description=f"ID: {yt_id}"[:100])
            )

        super().__init__(
            placeholder="เลือกช่อง YouTube ที่จะให้เช็ค (เลือกได้หลายช่อง)...",
            min_values=1,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # 🔒 กันคนอื่นมากดแทนเจ้าของคำสั่ง
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("ท่านอื่นห้ามกดเล่นน้าคัป!", ephemeral=True)

        await interaction.response.defer()

        selected_values = self.values
        if YT_CHECK_ALL_VALUE in selected_values:
            channel_ids = None
            checking_label = "ทุกช่อง"
        else:
            channel_ids = selected_values
            checking_label = f"{len(channel_ids)} ช่องที่เลือก"

        await interaction.edit_original_response(
            content=f"🔍 กำลังเช็ค{checking_label}ให้ครับ รอแป๊บนึงนะ...",
            view=None
        )

        async def send_func(text):
            await interaction.followup.send(text)

        await run_yt_check_and_report(send_func, self.guild_id, channel_ids=channel_ids)

class YTCheckView(ui.View):
    def __init__(self, author, guild_id, channels):
        super().__init__(timeout=60)
        self.message = None
        self.add_item(YTCheckSelect(author, guild_id, channels))

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⌛ หมดเวลาเลือกช่องแล้วครับ ลองพิมพ์ `/yt_check` ใหม่อีกทีนะครับ", view=None)
            except Exception:
                pass

@bot.hybrid_command(name="yt_check", description="เช็คช่อง YouTube ที่ติดตามอยู่ทันทีว่ามีไลฟ์สดหรือคลิปใหม่หรือยัง")
async def yt_check(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้นครับ!")
        return

    await ctx.defer()

    global conn
    c = conn.cursor()
    c.execute("SELECT yt_id, name FROM youtube_channels WHERE guild_id = ?", (str(ctx.guild.id),))
    channels = c.fetchall()

    if not channels:
        await ctx.send("ยังไม่มีช่อง YouTube ที่ติดตามอยู่ในเซิร์ฟนี้เลยครับ ลองใช้ `/yt_add` เพิ่มช่องก่อนนะครับ!")
        return

    c.execute("SELECT target_channel_id FROM youtube_settings WHERE guild_id = ?", (str(ctx.guild.id),))
    yt_setting = c.fetchone()
    if not yt_setting or not bot.get_channel(int(yt_setting[0])):
        await ctx.send("ยังไม่ได้ตั้งห้องแจ้งเตือน YouTube เลยครับ ใช้ `/set_yt_channel` เพื่อเลือกห้องก่อนนะครับ!")
        return

    view = YTCheckView(ctx.author, ctx.guild.id, channels)
    view.message = await ctx.send(
        f"📺 มีช่อง YouTube ที่ติดตามอยู่ {len(channels)} ช่องครับ เลือกช่องที่จะให้เช็คได้เลยครับ (เมนูด้านล่าง)",
        view=view
    )

# --- 3. ล้างความจำ (clear_memory) ---
@bot.hybrid_command(name="clear_memory", description="ล้างประวัติการสนทนาส่วนตัวของคุณกับ Bagley")
async def clear_memory(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer() # บอก Discord ว่าขอเวลาประมวลผลแป๊บครับ

    user_id = str(ctx.author.id) # แปลงเป็น string ให้ตรงกับตอนเซฟ
    global conn
    c = conn.cursor()
    
    # ลบเฉพาะประวัติของตัวเองคนเดียว
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    
    msg = "เรียบร้อย! ผมล้างหน่วยความจำที่เกี่ยวกับคุณทิ้งหมดแล้ว"
    
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)
    
    if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
        await bagley_speak(ctx.guild, "ล้างสมองสะอาดกริ๊บแล้วครับ!")

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

@bot.hybrid_command(name="kick_voice", description="เตะสมาชิกออกจากห้องเสียง")
async def kick_voice(ctx, member: discord.Member):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send(f"⚠️ ติดคูลดาวน์รวมครับ รออีก {rem} วินาที", ephemeral=True)
    user_id = ctx.author.id
    now = datetime.now()

    if member.voice:
        await member.move_to(None) # เตะออก
        
        msg = f"รับทราบครับ! ผมจัดการเขี่ย {member.display_name} ออกจากห้องเสียงให้แล้ว"
        
        # เช็คว่าบอทไม่ได้เล่นเพลงอยู่ ถึงจะพูดออกมาได้
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await bagley_speak(ctx.guild, f"จัดการเขี่ย {member.display_name} ออกไปให้แล้วครับ")
            
        await ctx.send(msg)
    else:
        # ถ้าเขาไม่อยู่ในห้องเสียง ก็ส่งแค่ข้อความแชทปกติ
        await ctx.send(f"คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงนะครับ")

# --- 1. หน้าตาปุ่ม ✅/❌ ที่จะไปโผล่ใน DM ของเพื่อน (เวอร์ชันส่งลิงก์ห้องเสียงเมื่อกดตกลง) ---
class GatherResponseView(ui.View):
    def __init__(self, inviter, topic, guild, time, channel_id):
        super().__init__(timeout=None)
        self.inviter = inviter
        self.topic = topic
        self.guild = guild
        self.time = time
        self.channel_id = channel_id

    @ui.button(label="ตกลง ✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        
        # 🧠 ดึงชื่อเล่นเรียลไทม์จากคลังสมองของแบ็คลี่
        real_responder_name = get_realtime_name(interaction.user.id, interaction.user.display_name)
        real_inviter_name = get_realtime_name(self.inviter.id, self.inviter.display_name)
        
        # แสดงผลชื่อเล่นในข้อความแชท
        msg = f"✅ **{real_responder_name}** ตอบตกลงภารกิจ: `{self.topic}` ของคุณ {real_inviter_name} แล้ว!"
        if channel: await channel.send(msg)

        vc = self.guild.voice_client
        if vc and vc.is_connected():
            if not vc.is_playing():
                # แบ็คลี่พูดออกเสียงโดยใช้ชื่อเล่นในคลังทันที!
                await bagley_speak(self.guild, f"คุณ {real_responder_name} ตอบตกลงแล้วครับ เดี๋ยวก็คงมาแล้วครับ")
            else:
                print(f"Bagley: {interaction.user.name} ตกลง แต่ผมไม่พูดแทรกเพลงนะ")

        if self.inviter.voice and self.inviter.voice.channel:
            voice_channel = self.inviter.voice.channel
            try:
                invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                response_msg = f"รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว\nนี่คือลิงก์เข้าห้องเสียงครับ วาร์ปตามไปได้เลย: {invite.url}"
            except Exception as e:
                response_msg = f"รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})"
        else:
            response_msg = "รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่ตอนนี้คนเรียกไม่ได้อยู่ในห้องเสียงแล้วครับ)"

        await interaction.response.send_message(response_msg, ephemeral=True)
        self.stop()

    @ui.button(label="ไม่สะดวก ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        
        # 🧠 ดึงชื่อเล่นเรียลไทม์จากคลังสมอง
        real_responder_name = get_realtime_name(interaction.user.id, interaction.user.display_name)
        
        msg = f"❌ **{real_responder_name}** ไม่สะดวกมาร่วมภารกิจ: `{self.topic}`"
        if channel: await channel.send(msg)
        
        vc = self.guild.voice_client
        if vc and vc.is_connected():
            if not vc.is_playing():
                # แบ็คลี่พูดออกเสียงปฏิเสธด้วยชื่อเล่น
                await bagley_speak(self.guild, f"คุณ {real_responder_name} ปฏิเสธครับ สงสัยเขาจะติดธุระ")
            else:
                print(f"Bagley: {interaction.user.name} ปฏิเสธ แต่ผมไม่พูดขัดจังหวะเพลงครับ")

        await interaction.response.send_message("รับทราบครับ ไว้นัดกันใหม่วันหลังนะ", ephemeral=True)
        self.stop()

# --- ส่วนหน้าตาเมนู คำสั่ง gather ---
class RoleSelect(discord.ui.RoleSelect):
    def __init__(self, author, topic, time):
        super().__init__(placeholder="เลือก Role ที่ต้องการเรียก...", min_values=1, max_values=10)
        self.author = author
        self.topic = topic
        self.time = time

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("เฉพาะคนเรียกเท่านั้นที่เลือกได้ครับ!", ephemeral=True)
            return

        await interaction.response.defer()
        target_roles = self.values # รายชื่อ Role ที่เลือกมา
        members_to_ping = set()
        for role in target_roles:
            for member in role.members:
                if not member.bot: members_to_ping.add(member)

        count = 0
        for member in members_to_ping:
            try:
                # สร้าง View ปุ่มกดสำหรับคนนี้
                view = GatherResponseView(self.author, self.topic, interaction.guild, self.time, interaction.channel.id)
        
                # สร้าง Embed สวยๆ
                embed = discord.Embed(title="🔔 มีสัญญาณเรียกตัวด่วน!", color=discord.Color.gold())
                embed.description = f"คุณ **{self.author.display_name}** กำลังเรียกหารวมพล!"
                embed.add_field(name="ภารกิจ", value=f"**{self.topic}**", inline=False)
                embed.add_field(name="นัดหมายเวลา", value=f"`{self.time}`", inline=True)
                embed.set_footer(text="กรุณากดปุ่มเพื่อยืนยันสถานะครับ")

                await member.send(embed=embed, view=view)
                count += 1
            except: continue

        role_names = ", ".join([r.name for r in target_roles])
        await interaction.followup.send(f"กระจายคำเชิญภารกิจ `{self.topic}` ให้ยศ {role_names} รวม {count} ท่านเรียบร้อย!")

        if interaction.guild.voice_client:
            await bagley_speak(interaction.guild, f"กระจายสัญญาณแจ้งเตือนยศ {role_names} เรียบร้อยแล้วครับ รวมทั้งหมด {count} ท่านครับ")

# --- คลาสสำหรับเลือกคนรายบุคคล ---
class MemberSelect(discord.ui.UserSelect):
    def __init__(self, author, topic, time):
        super().__init__(placeholder="เลือกเพื่อนรายตัวที่ต้องการเรียก...", min_values=1, max_values=10)
        self.author = author
        self.topic = topic
        self.time = time

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("เฉพาะคนเรียกเท่านั้นที่เลือกได้ครับ!", ephemeral=True)
            return

        await interaction.response.defer()
        target_members = self.values # รายชื่อเพื่อนที่เลือก
        
        count = 0
        for member in target_members:
            if member.bot: continue
            try:
                view = GatherResponseView(self.author, self.topic, interaction.guild, self.time, interaction.channel.id)
                embed = discord.Embed(title="🔔 มีสัญญาณเรียกตัวด่วน!", color=discord.Color.gold())
                embed.description = f"คุณ **{self.author.display_name}** กำลังเรียกหาคุณเป็นการส่วนตัว!"
                embed.add_field(name="ภารกิจ", value=f"**{self.topic}**", inline=False)
                embed.add_field(name="นัดหมายเวลา", value=f"`{self.time}`", inline=True)
                
                await member.send(embed=embed, view=view)
                count += 1
            except: continue

        await interaction.followup.send(f"ส่งคำเชิญแบบระบุตัวตนให้เพื่อน {count} ท่านเรียบร้อยครับ!")

        if interaction.guild.voice_client:
            await bagley_speak(interaction.guild, f"ส่งคำเชิญระบุตัวบุคคลสำหรับภารกิจ {self.topic} เรียบร้อยแล้วครับ")

# ---  RoleSelectView 2 เมนู ---
class RoleSelectView(discord.ui.View):
    def __init__(self, author, topic, time):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(author, topic, time)) # เมนูเลือก Role
        self.add_item(MemberSelect(author, topic, time)) # เมนูเลือกเพื่อน

# ==========================================
# 📑 [ส่วนเสริม: กล่องข้อความ Modal สำหรับลงทะเบียน]
# ==========================================
class RegisterModal(discord.ui.Modal):
    def __init__(self, target_role_id: int):
        super().__init__(title="ฟอร์มลงทะเบียนประวัติกับ Bagley")
        self.target_role_id = target_role_id
        
        self.nickname_input = discord.ui.TextInput(
            label="ชื่อเล่นของคุณ (สำหรับให้บอทเรียกและบันทึก)",
            placeholder="กรุณาพิมพ์ชื่อเล่นของคุณที่นี่...",
            required=True,
            max_length=20
        )
        self.birthday_input = discord.ui.TextInput(
            label="วันเกิดของคุณ (รูปแบบ วัน/เดือน เช่น 25/12)",
            placeholder="วว/ดด (เช่น 07/06 หรือ 14/02) หรือเว้นว่างไว้ก็ได้คัป",
            required=False,
            max_length=5
        )
        
        self.add_item(self.nickname_input)
        self.add_item(self.birthday_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        new_nickname = self.nickname_input.value.strip()
        birthday = self.birthday_input.value.strip() or "ยังไม่ระบุ"

        guild = interaction.guild
        member = interaction.user
        role = guild.get_role(int(self.target_role_id))

        try:
            data_memory = load_user_data() 
            user_id = str(member.id)
            
            if user_id not in data_memory or not isinstance(data_memory[user_id], dict):
                data_memory[user_id] = {}
                
            data_memory[user_id]["nickname"] = new_nickname
            data_memory[user_id]["birthday"] = birthday
            
            save_user_data(data_memory) 
            print(f"DEBUG: [Register] ซิงค์ข้อมูล {new_nickname} และวันเกิด {birthday} ลงคลังหลักเรียบร้อย!")
        except Exception as e_db:
            print(f"❌ เกิดข้อผิดพลาดขณะเซฟลงฐานข้อมูลหลัก JSON: {e_db}")

        # ==========================================
        # 👑 [มอบยศตำแหน่ง + เปลี่ยนชื่อแสดงผลในดิสคอร์ด]
        # ==========================================
        try:
            await member.edit(nick=new_nickname)
            
            if role:
                await member.add_roles(role)
            
            await interaction.followup.send(
                f"🎉 **แบ็คลี่ดำเนินการลงทะเบียนเสร็จสรรพเรียบร้อยครับ!**\n"
                f"• เปลี่ยนชื่อในดิสคอร์ดเป็น: **{new_nickname}**\n"
                f"• บันทึกวันเกิดลงคลังสมองกล: **{birthday}**\n"
                f"• มอบยศตำแหน่ง: **{role.name if role else 'ไม่พบยศ'}** เรียบร้อยครับ!\n\n"
                f"*(วันหลังหากอยากแก้ไขชื่อเล่นหรือวันเกิด สามารถพิมพ์ `/register` เพื่ออัปเดตใหม่ได้ตลอดเวลาเลยน้า)*", 
                ephemeral=True
            )
            
            await bagley_speak(guild, f"ยินดีต้อนรับสมาชิกใหม่ คุณ {new_nickname} ครับ")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ แบ็คลี่เปลี่ยนชื่อหรือให้ยศไม่ได้! (ตรวจสอบลำดับยศของบอทด้วยนะครับ)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ เกิดข้อผิดพลาดในระบบ: {e}", ephemeral=True)

class PullRoomView(ui.View):
    def __init__(self, author, target_channel):
        super().__init__(timeout=60)
        self.author = author
        self.target_channel = target_channel # ห้องหลักที่คุณชะอมนั่งอยู่คัป

        # 🔮 เปลี่ยนมาใช้ ChannelSelect ดึงเฉพาะห้องเสียง (Voice) ทั้งหมดในเซิร์ฟเวอร์แบบ Auto
        # ไม่โดนจำกัดที่ 25 ห้องแบบเดิม และสามารถพิมพ์ค้นหาชื่อห้องได้ด้วยคัปพ้ม!
        self.channel_select = ui.ChannelSelect(
            placeholder="พิมพ์ค้นหา หรือเลือกห้องต้นทางที่จะดึงคนมา...",
            channel_types=[discord.ChannelType.voice] # กรองให้เห็นเฉพาะห้องเสียงเท่านั้นคัป
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def channel_callback(self, interaction: discord.Interaction):
        # 🔒 เช็กสิทธิ์คนกด ต้องเป็นคนใช้คำสั่งเท่านั้นคัปพ้ม
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("ท่านอื่นห้ามกดเล่นน้าคัป!", ephemeral=True)

        # 🚪 ดึงข้อมูลห้องต้นทางที่คุณเลือกคลิกมาจาก Dropdown อัจฉริยะ
        source_channel = self.channel_select.values[0]
        
        # 🚨 ดักเซฟตี้: กันคุณเลือกห้องเสียงเดียวกับที่ตัวเองนั่งอยู่คัป 5555
        if source_channel.id == self.target_channel.id:
            return await interaction.response.send_message("❌ คุณจะดึงคนจากห้องเดียวกันมาหาตัวเองไม่ได้น้าคัปพ้ม!", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        # 👥 คัดกรองมนุษย์ในห้องนั้น (ไม่นับบอทตามลอจิกเดิมของคุณเป๊ะ ๆ)
        if source_channel and isinstance(source_channel, discord.VoiceChannel):
            members_to_move = [m for m in source_channel.members if not m.bot]
            
            if not members_to_move:
                return await interaction.followup.send(f"❌ ห้อง **{source_channel.name}** ไม่มีคนอยู่เลยคัป!", ephemeral=True)

            success_count = 0
            # 🚀 ทำการเหมาเข่งย้ายห้องตามลอจิกเดิมของคุณคัปพ้ม!
            for member in members_to_move:
                try:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
                except:
                    pass

            # 🎉 อัปเดตข้อความเดิมเมื่อทำงานเสร็จสิ้น
            await interaction.edit_original_response(
                content=f"🚀 วาร์ปเพื่อน ๆ จากห้อง **{source_channel.name}** มาที่ห้อง **{self.target_channel.name}** ทั้งหมด {success_count} คน เรียบร้อยคัปพ้ม!",
                view=None
            )
            
            # 🔊 แบ็คลี่ (ลุงนิวัฒน์) รายงานส่งเสียงในห้องเสียงหลักคัป
            msg = f"ย้ายปาร์ตี้จากห้อง {source_channel.name} กลับมารวมกันเรียบร้อยแล้วครับ"
            await bagley_speak(interaction.guild, msg)
        else:
            await interaction.followup.send("หาห้องเสียงดังกล่าวไม่เจอครับ!", ephemeral=True)

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
    global is_tts_enabled, is_playing_music
    
    # 1. จัดการสถานะตามที่เลือก
    if mode is None:
        # ถ้าไม่ระบุ mode ให้สลับสถานะ (Toggle) แบบเดิม
        is_tts_enabled = not is_tts_enabled
    else:
        # ถ้าเลือกจากเมนู หรือพิมพ์ on/off
        if mode.lower() in ["on", "เปิด", "start"]:
            is_tts_enabled = True
        elif mode.lower() in ["off", "ปิด", "stop"]:
            is_tts_enabled = False

    # 2. เตรียมข้อความแจ้งเตือน
    if is_tts_enabled:
        msg = "ระบบล่ามเปิดใช้งานแล้วครับ!"
        icon = "🔊"
    else:
        msg = "ปิดระบบล่ามเรียบร้อยครับ"
        icon = "🔇"

    # 3. ส่งข้อความตอบกลับในแชท
    await ctx.send(f"{icon} **{msg}**")

    # 4. สั่งให้ Bagley พูดผ่าน Voice Channel (ถ้าไม่ได้เล่นเพลงอยู่)
    if ctx.voice_client and not is_playing_music:
        try:
            # ใช้ข้อความเสียงอันเดียวกับในแชท
            await bagley_speak(ctx.guild, msg) 
        except Exception as e:
            print(f"TTS Speech Error: {e}")
    
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
    await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`")

    # ส่วนที่ 3: ตรวจสอบระบบเสียง (Audio Output)
    vc = ctx.guild.voice_client
    voice_info = "READY" if vc and vc.is_connected() else "IDLE"
    await asyncio.sleep(1)
    await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`Audio Output: {voice_info}`")

    # --- สรุปผลด้วยเสียง ---
    if vc and vc.is_connected():
        # ถ้าบอทอยู่ในห้องเสียง ให้รายงานเป็นลำดับ
        report_text = f"ตรวจสอบระบบเสร็จสิ้น ระบบฐานข้อมูล {db_status}, ระบบเนือรัลลิงก์ปกติ, ระบบเสียงพร้อมใช้งาน, ทุกระบบทำงานเต็มรูปแบบหนึ่งร้อยเปอร์เซ็นต์ครับ"
        
        # เช็คก่อนว่าไม่ได้เล่นเพลงอยู่
        if not vc.is_playing():
            await bagley_speak(ctx.guild, report_text)
        
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`Audio Output: {voice_info}`\n\n✅ **ทุกระบบพร้อมสอดแนมครับ!**")
    else:
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`Audio Output: {voice_info}`\n\n⚠️ **การตรวจสอบเสร็จสิ้น (ระบบเสียงไม่ได้เชื่อมต่อ)**")

@bot.hybrid_command(name="mute_sleep", description="ปิดไมค์สมาชิก (กรณีหลับ/เสียงดัง) โดยไม่ตัดสาย")
@commands.cooldown(1, 60, commands.BucketType.user) # ติดคูลดาวน์ 1 นาทีต่อการใช้ 1 ครั้ง
async def mute_sleep(ctx, member: discord.Member):
    if member.voice:
        try:
            await member.edit(mute=True) # สั่ง Server Mute
            msg = f"ปิดไมค์คุณ {member.display_name} เรียบร้อยครับ เห็นว่าหลับปุ๋ยเชียว!"
            await ctx.send(f"🔇 **{msg}**")
            
            # ส่งเสียง TTS บอกในห้อง
            if ctx.voice_client and not is_playing_music:
                await bagley_speak(ctx.guild, f"จัดการปิดไมค์ให้แล้วครับ")
        except Exception as e:
            await ctx.send("ผมไม่มีอำนาจพอจะปิดไมค์สมาชิกคนนี้ครับ!")
    else:
        await ctx.send("สมาชิกคนนี้ไม่ได้อยู่ในห้องเสียงครับ")

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
            await ctx.send(f"🔊 ยินดีต้อนรับกลับมาครับ {member.display_name}! ผมเปิดไมค์ให้แล้ว")
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
            msg = f"เปิดไมค์ให้คุณ {member.display_name} เรียบร้อยแล้วครับ!"
            await ctx.send(f"🔊 **{msg}**")
            
            # ส่งเสียง TTS รายงานผล (เสียงคุณนิวัท)
            if ctx.voice_client and not is_playing_music:
                await bagley_speak(ctx.guild, f"เปิดไมค์ให้เพื่อนเรียบร้อยครับ")
        except Exception as e:
            await ctx.send("ผมไม่มีอำนาจปลดไมค์ให้สมาชิกคนนี้ครับ!")
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
        await ctx.send("คุณต้องอยู่ในห้องเสียงก่อนนะครับ")

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
        await ctx.send("คุณต้องอยู่ในห้องเสียงก่อนถึงจะสร้างปาร์ตี้ดึงเพื่อนไปได้ครับ!")

@bot.hybrid_command(name="deaf_work", description="ปิดหูฟังสมาชิก (กรณีทำงาน/ต้องการความสงบ)")
@commands.cooldown(1, 60, commands.BucketType.user)
async def deaf_work(ctx, member: discord.Member):
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send(f"❌ คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับ")
    
    # เช็คว่าเขาปิดหูฟังอยู่แล้วหรือเปล่า (Error Check)
    if member.voice.deaf:
        return await ctx.send(f"🎧 คุณ {member.display_name} ปิดหูฟังอยู่แล้วครับ")

    try:
        await member.edit(deafen=True)
        msg = f"ปิดหูฟังให้คุณ {member.display_name} เรียบร้อยครับ!"
        await ctx.send(f"🎧 **{msg}**")
        
        # ระบบพูด TTS เสียงคุณนิวัท (ถ้าไม่ได้เล่นเพลงอยู่)
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"จัดการปิดหูฟังให้เรียบร้อยครับ")
    except Exception as e:
        await ctx.send(f"❌ ผมจัดการไม่ได้ครับ: {e}")

@bot.hybrid_command(name="undeaf_me", description="เปิดหูฟังของตัวเองเมื่อพร้อมคุยแล้ว")
async def undeaf_me(ctx):
    member = ctx.author
    
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงก่อนนะครับผมถึงจะปรับสถานะให้ได้")
    
    # เช็คว่าหูฟังไม่ได้ถูกปิดอยู่ ถ้าเปิดอยู่แล้วก็ไม่ต้องทำอะไร
    if not member.voice.deaf:
        return await ctx.send("🔊 หูฟังของคุณก็เปิดอยู่แล้วนะ! พร้อมลุยได้เลยครับ", delete_after=5)

    try:
        await member.edit(deafen=False) # ปลด Server Deafen
        await ctx.send(f"🎧 ยินดีต้อนรับกลับสู่โลกแห่งเสียงครับ {member.display_name}!")
        
        # ส่งเสียงทักทายหน่อย
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"ยินดีต้อนรับกลับมาครับ")
    except Exception as e:
        await ctx.send(f"❌ ดูเหมือนผมจะมีปัญหาในการเข้าถึงระบบเสียงนะครับ: {e}")

@bot.hybrid_command(name="undeaf_member", description="ปลดหูฟังให้สมาชิกคนอื่น")
@commands.cooldown(1, 60, commands.BucketType.user)
async def undeaf_member(ctx, member: discord.Member):
    if not member.voice:
        return await ctx.send(f"❌ คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับ")
    
    # เช็คว่าเขาเปิดหูฟังอยู่แล้วหรือเปล่า
    if not member.voice.deaf:
        return await ctx.send(f"🔊 หูฟังของคุณ {member.display_name} ก็เปิดอยู่แล้วนะ")

    try:
        await member.edit(deafen=False)
        await ctx.send(f"🎧 ปลดหูฟังให้คุณ {member.display_name} เรียบร้อย!")
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"เปิดหูฟังให้เพื่อนเรียบร้อยครับ")
    except Exception as e:
        await ctx.send(f"❌ ผมปลดให้ไม่ได้ครับ: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        return await ctx.send("🛑 **ปฏิเสธการเข้าถึง:** คำสั่งนี้สงวนไว้ให้พรรคพวกระดับผู้สร้าง (เจ้าของบอท) เท่านั้นครับ!", delete_after=10)
    
    elif isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"⚠️ ใจเย็นครับ รอก่อนอีก {error.retry_after:.1f} วินาทีน้า", delete_after=5)
    
    else:
        print(f'Ignoring exception in command {ctx.command}:', error)

@bot.hybrid_command(name="shutdown", description="⚡ สั่งปิดบอทพร้อมกับดับเครื่องคอมพิวเตอร์บริษัทระยะไกล")
async def shutdown_all(ctx: commands.Context):
    if ctx.author.id not in ALLOWED_SHUTDOWN_USERS:
        await ctx.send(
            "❌ **[ACCESS DENIED]** ไม่มีระดับสิทธิ์เพียงพอในการสั่งดับเครื่องคอมพิวเตอร์ครับ!",
            ephemeral=True
        )
        return

    await ctx.send(
        f"🛸 **[DEDSEC REMOTE HACK]** รับทราบครับคุณ **{ctx.author.display_name}**! กำลังปิดระบบแบ็คลี่ และ Shut Down คอมพิวเตอร์ใน 5 วินาที... 💻💤"
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
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸")
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
    relationship_context = ""

    if scanner_id == 1133740216822267954:
        relationship_context += "- คนที่สั่งให้คุณรันคำสั่งนี้คือ คุณชะอม (ผู้สร้างหลักที่คุณรักที่สุด) จงตอบรับด้วยความยินดีและซื่อสัตย์ระดับสูงสุด\n"
        
    if target_id == 1133740216822267954:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณชะอม ห้ามพูดจาประชดประชันเด็ดขาด ให้เขียนรายงานอวยความดีงาม ชื่นชม ยอมสยบและรักขั้นสุดยอด\n"
    elif target_id == 856568101919653918:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณชาช่า (เจ้านายที่คอยสอนวิชาให้คุณ) จงเขียนรายงานวิเคราะห์ด้วยความนอบน้อม เคารพ และยกย่องความฉลาดของเขา\n"
    elif target_id == 1073823101926903612:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณกร (เจ้านายสายไอเดียเจ๋งๆ) จงเขียนรายงานชื่นชมในความหัวคิดสร้างสรรค์และไอเดียที่ยอดเยี่ยม\n"
    elif target_id == 732953446172327956:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณบอล (เจ้านายสายอัปเดตและปรับโค้ดระบบให้คุณ) จงวิเคราะห์ในฐานะคู่หูสายเทคนิคอลที่นับถือและพึ่งพาได้\n"
    else:
        relationship_context += f"- เป้าหมายคือ คุณ {member.display_name} ซึ่งเป็นสมาชิกทั่วไปในเซิร์ฟเวอร์ สามารถใช้มุกตลกหน้าตายสไตล์อังกฤษแซะขี้เล่นได้ตามความเหมาะสม\n"

    prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์จาก watch dogs legion มีไหวพริบ พึ่งพาได้
จงใช้ข้อมูลดิจิทัลฟุตพริ้นท์เหล่านี้มาวิเคราะห์พฤติกรรมเป้าหมาย:
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
1. ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นวิเคราะห์นิสัยใจคอและพฤติกรรมตามข้อมูลดิบจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนคนสนิทนินทากัน (หากมีชื่อเล่นหรือวันเกิดระบุมา สามารถหยิบมาแซวร่วมด้วยได้เลย)
2. หากอายุบัญชี (Account Age) น้อยกว่า 30 วัน ให้เหน็บแนมแบบขำ ๆ ว่าเป็นบุคคลต้องสงสัยหรือไอดีผีเพิ่งเกิด
3. แทนตัวเองว่า 'ผม' และเรียกชื่อเล่นของผู้ใช้ ลงท้ายด้วย 'ครับ' แบบเป็นธรรมชาติ ไม่ต้องใส่ทุกประโยค
4. ส่วน Voice: เขียนคำอ่านภาษาไทยให้สละสลวย กระชับ 2-3 ประโยค เพื่อให้ระบบพูดออกเสียง (TTS) ได้ราบรื่น ไม่ติดขัด

โปรดตอบกลับแยกเป็น 2 ส่วนตามรูปแบบโครงสร้างนี้อย่างเคร่งครัด (ห้ามเปลี่ยนคำหัวข้อ):
Embed: [บทวิเคราะห์พฤติกรรมขี้เล่นกวนๆ น่ารักๆ สั้นๆ สำหรับแสดงในแชท]
Voice: [คำพูดรายงานสรุปให้คุณฟังผ่านระบบเสียง]
"""

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite", 
            contents=prompt
        )
        ai_text = (response.text or "").strip()
        
        analysis_report = ai_text.split("Embed:")[1].split("Voice:")[0].strip()
        voice_report = ai_text.split("Voice:")[1].strip()
        
    except Exception as e:
        print(f"AI Error: {e}")
        analysis_report = "ระบบป้องกันของเป้าหมายสูงเกินไป สแกนได้ไม่สมบูรณ์ครับ"
        voice_report = f"สแกนข้อมูลของคุณ {member.display_name} เรียบร้อยครับ"

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
    if ctx.voice_client and ctx.voice_client.channel and not ctx.voice_client.is_playing():
        if ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
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

    # 3. ระบบ "รายงานแบบอัตโนมัติด้วยเสียง" ถ้าแบ็คลี่อยู่ในห้องเสียงเดียวกับคนสั่ง และไม่ได้เล่นเพลงอยู่
    voice_client = member.guild.voice_client
    if voice_client and voice_client.is_connected() and not voice_client.is_playing():
        
        if is_suspicious:
            voice_report = f"ครับ! ตรวจพบไอดีผีชื่อ {member.display_name} เพิ่งสมัครมาได้แค่ {account_age_days} วัน แฝงตัวเข้ามาในเซิร์ฟเวอร์ครับ ระวังตัวด้วยนะ!"
        else:
            voice_report = f"มีพรรคพวกใหม่ชื่อ {member.display_name} เชื่อมต่อเข้ามาในเซิร์ฟเวอร์ครับ ดูเหมือนจะเป็นพลเมืองปกติดีครับ"
        
        # สั่งให้แบ็คลี่พูด
        await bagley_speak(member.guild, voice_report)

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
        await ctx.send(f"รับทราบครับ! ผมจะไปอยู่เป็นเพื่อนคุณ {member.display_name} เดี๋ยวนี้แหละ")

        # เล่นเสียงเปิดตัว (เฟดเสียง)
        audio_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe'),
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
        msg = (f"ไฮแจ๊คสำเร็จ สวัสดีครับ คุณ {member.display_name} คุณ {ctx.author.display_name} ส่งผมมาอยู่เป็นเพื่อนคุณครับ "
               f"หากมีอะไรให้ช่วยเรื่องคำสั่ง ค้นหาข้อมูล หรืออยากพูดคุย "
               f"สามารถเรียกหาผม แบ็คลี่ ได้ตลอดเลยนะครับ ผมประจำการอยู่ตรงนี้แล้วครับ!")

        await bagley_speak_wait(ctx.guild, msg)
        
    else:
        await ctx.send(f"คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับ ผมคงแอบวาร์ปไปหาไม่ได้")

@bot.hybrid_command(name="alarm", description="ตั้งเวลาปลุกเพื่อน (เช่น 07:00 หรือ 16:30)")
async def alarm(
    ctx: commands.Context, 
    member: discord.Member, 
    time_str: str, 
    message: str = "ตื่นได้แล้วครับ!"
):
    global active_alarms
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

        await ctx.send(f"รับทราบครับ! ผมจะตั้งนาฬิกาปลุกไว้ที่เวลา {clean_time} และจะแจ้งคุณ {member.display_name} ทันทีครับ")

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
            active_alarms[guild_id] = True

            print(f"⏰ [Bagley] เริ่มกระบวนการปลุกคุณ {member.display_name} แล้วครับ")
            
            while ctx.voice_client is not None and active_alarms.get(guild_id, False):
                
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio('iphone_alarm.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
                )
                source.volume = 0.4 
                vc.play(source)

                while vc.is_playing(): 
                    if not active_alarms.get(guild_id, False) or ctx.voice_client is None:
                        vc.stop()
                        break
                    await asyncio.sleep(0.1)

                if ctx.voice_client is None or not active_alarms.get(guild_id, False):
                    break

                msg = f"คุณ {member.display_name} ครับ ขณะนี้เวลา {clean_time} แล้วนะครับ คุณ {ctx.author.display_name} ฝากให้ผมมาปลุกคุณด้วยข้อความว่า: {message}"
                await bagley_speak_wait(ctx.guild, msg)

                for _ in range(20):
                    if not active_alarms.get(guild_id, False) or ctx.voice_client is None:
                        break
                    await asyncio.sleep(0.1)
            
            if guild_id in active_alarms:
                del active_alarms[guild_id]
            print(f"🛑 [Bagley] ปิดระบบลูปนาฬิกาปลุกในเซิร์ฟเวอร์ {ctx.guild.name} เรียบร้อย")
            
        else:
            await ctx.send(f"ถึงเวลา {clean_time} แล้วครับ แต่ดูเหมือนคุณ {member.display_name} จะไม่อยู่ในห้องเสียงแล้ว")

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
        await ctx.send("รับทราบครับ! เคลียร์รายการแจ้งเตือนและนาฬิกาปลุกทั้งหมดของคุณให้เรียบร้อยแล้วครับ")
    else:
        await ctx.send("คุณยังไม่มีรายการแจ้งเตือนหรือนาฬิกาปลุกในระบบเลยครับ")

@bot.hybrid_command(name="stop_alarm", description="สั่งปิดนาฬิกาปลุกที่กำลังส่งเสียงดังอยู่ในตอนนี้")
async def stop_alarm(ctx: commands.Context):
    global active_alarms
    guild_id = ctx.guild.id
    
    if guild_id in active_alarms and active_alarms[guild_id]:
        active_alarms[guild_id] = False
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.send("⏰ **[Bagley System]** ปิดนาฬิกาปลุกประจำเซิร์ฟเวอร์เรียบร้อยครับ! แยกย้ายไปนอนต่อ.. เอ้ย! ไปทำภารกิจกันได้เลยครับ!")
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
        await ctx.send(f"รับทราบครับ! ลบรายการแจ้งเตือนและนาฬิกาปลุกทั้งหมดของ คุณ {member.display_name} ให้เรียบร้อยแล้วครับ")
    else:
        await ctx.send(f"ไม่พบรายการแจ้งเตือนหรือนาฬิกาปลุกของ คุณ {member.display_name} ในระบบครับ")

@bot.hybrid_command(name="teach", description="สอนให้แบ็คลี่จำคีย์เวิร์ดคำถามและคำตอบ")
async def teach(ctx: commands.Context, keyword: str, response: str):
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸")
        return

    clean_keyword = keyword.lower().strip()

    if len(clean_keyword) == 0:
        await ctx.send("⚠️ **[TEACH REJECTED]** คีย์เวิร์ดต้องมีตัวอักษรด้วยนะคร้าบ! ❌")
        return

    global conn
    c = conn.cursor()
    
    c.execute(
        "INSERT OR REPLACE INTO teach_memory (keyword, response) VALUES (?, ?)",
        (clean_keyword, response.strip())
    )
    conn.commit()
    
    await ctx.send(f"รับทราบครับ! แบ็คลี่จดบันทึกคีย์เวิร์ด **'{keyword}'** เข้าคลังสมองกลเรียบร้อยแล้วครับ! 🧠✨")

@bot.hybrid_command(name="unteach", description="สั่งให้แบ็คลี่ลืมคีย์เวิร์ดคำถามที่ไม่ต้องการ")
async def unteach(ctx: commands.Context, keyword: str):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸")
        return

    await ctx.defer(ephemeral=False)
    global conn
    c = conn.cursor()
    
    clean_keyword = keyword.lower().strip()
    
    c.execute("SELECT response FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    result = c.fetchone()
    
    if result is None:
        await ctx.send(f"🤖 แบ็คลี่ลองค้นดูแล้ว... ไม่พบคีย์เวิร์ด **'{keyword}'** ในระบบเลยครับ!")
        return

    c.execute("DELETE FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    conn.commit()
    
    await ctx.send(f"รับทราบครับ! แบ็คลี่ทำการลบและลืมคีย์เวิร์ด **'{keyword}'** ออกเรียบร้อยแล้วครับ! 🧼❌")

@bot.hybrid_command(name="list_teach", description="เรียกดูรายการคีย์เวิร์ดทั้งหมดที่เคยสอนแบ็คลี่ไว้")
async def list_teach(ctx: commands.Context):
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸")
        return

    global conn
    c = conn.cursor()
    
    c.execute("SELECT keyword, response FROM teach_memory ORDER BY keyword ASC")
    rows = c.fetchall()
    
    if not rows:
        await ctx.send("🤖 ตอนนี้คลังสมองของแบ็คลี่ยังว่างเปล่า ไม่มีคีย์เวิร์ดที่เคยสอนไว้เลยครับ!")
        return

    formatted_list = []
    for keyword, response in rows:
        response_text = response if response else "*(ไม่มีคำตอบบันทึกไว้)*"
        # ตัดคำตอบที่ยาวเกินไปกันข้อความในเอ็มเบดล้นหน้า
        if len(response_text) > 150:
            response_text = response_text[:150] + "..."
        formatted_list.append(f"**{keyword}**\n> {response_text}")

    title_text = "🧠 BAGLEY MEMORY BANK: รายการคีย์เวิร์ดที่ทีมพัฒนาเคยสอนไว้"
    view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=5)
    view.message = await ctx.send(embed=view.create_embed(), view=view)

@bot.hybrid_command(name="remember", description="[Developer Only] สั่งให้แบ็คลี่จดจำชื่อเล่น/วันเกิดของสมาชิกลงคลังความจำ")
@app_commands.describe(
    member="แท็กสมาชิก (@ชื่อ) หรือใส่ User ID ตรง ๆ ก็ได้ (เหมือนตอนพิมพ์ 'จำไว้ว่า')",
    category="ประเภทข้อมูลที่จะบันทึก",
    info="ข้อมูลที่ต้องการบันทึก (เช่น ชื่อเล่น หรือ วันเกิด)"
)
@app_commands.choices(category=[
    app_commands.Choice(name="ชื่อเล่น (Nickname)", value="nickname"),
    app_commands.Choice(name="วันเกิด (Birthday)", value="birthday"),
])
async def remember(ctx: commands.Context, member: str, category: str, info: str):
    """เวอร์ชันสแลชคอมมานด์ของคำสั่งพูดคุย 'จำไว้ว่า' — จำกัดสิทธิ์เฉพาะทีมพัฒนา (ALLOWED_TEACH_USERS) เท่านั้น
    ผู้ใช้ทั่วไปที่ต้องการแก้ไขชื่อเล่น/วันเกิดของตัวเอง ให้ใช้ /register แทนครับ"""
    await ctx.defer()

    # 🔒 จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้น เหมือนกับคำสั่ง teach
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(
            f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸\n"
            f"หากต้องการแก้ไขชื่อเล่นหรือวันเกิดของตัวเอง สามารถพิมพ์ `/register` เพื่ออัปเดตข้อมูลได้เลยครับ!"
        )
        return

    # 🔍 รองรับทั้งการแท็ก @สมาชิก และการใส่ User ID ตรง ๆ (ดึงตัวเลข ID ออกมาแบบเดียวกับคำสั่ง "จำไว้ว่า")
    has_id = regex_lib.search(r'(\d{17,19})', member)
    if not has_id:
        await ctx.send("❌ ไม่พบผู้ใช้ที่ระบุครับ กรุณาแท็ก (@) สมาชิก หรือใส่ User ID ให้ถูกต้องนะครับ!")
        return

    target_id = int(has_id.group(1))
    target_user = ctx.guild.get_member(target_id) if ctx.guild else None
    if target_user is None:
        try:
            target_user = await bot.fetch_user(target_id)
        except Exception:
            target_user = None

    if target_user is None:
        await ctx.send(f"❌ แบ็คลี่หาผู้ใช้ ID `{target_id}` ไม่เจอเลยครับ ลองเช็ก ID อีกทีนะครับ!")
        return

    target_id_str = str(target_user.id)
    target_display_name = getattr(target_user, "display_name", None) or target_user.name
    clean_info = info.strip()

    if not clean_info:
        await ctx.send("⚠️ **[REMEMBER REJECTED]** ข้อมูลที่จะให้จำต้องไม่ว่างเปล่านะครับ! ❌")
        return

    user_data = load_user_data()

    if target_id_str not in user_data or isinstance(user_data[target_id_str], str):
        user_data[target_id_str] = {"nickname": "ยังไม่มีชื่อเล่น", "birthday": "ยังไม่ได้ระบุ"}

    if category == "birthday":
        user_data[target_id_str]["birthday"] = clean_info
        save_user_data(user_data)
        await ctx.send(f"รับทราบครับ! ผมบันทึกวันเกิดของ คุณ {target_display_name} ว่าเกิดวันที่ **{clean_info}** ลงสมองกลเรียบร้อยแล้วครับ! 🎂✨")
    else:
        user_data[target_id_str]["nickname"] = clean_info
        save_user_data(user_data)
        await ctx.send(f"รับทราบครับ! ผมบันทึกฉายาของ คุณ {target_display_name} ว่าคือ **{clean_info}** เรียบร้อยครับ! 🤠")

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
        voice_report_status[guild_id] = True
        response_text = "เปิดระบบคืนชีพ! 🔊 คราวนี้ใครเข้าหรือออกจากห้องเสียง ผมจะโผล่ไปรายงานส่งเสียงทักทายเหมือนเดิมแล้วครับ!"
        speech_text = _pick_speech(VOICE_REPORT_ON_SPEECH)
    else:
        voice_report_status[guild_id] = False
        response_text = "รับทราบครับ! 🔇 ผมจะปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงในเซิร์ฟนี้ให้ชั่วคราวน้า (แต่ระบบสถิติยังนับเวลาปกติครับ)"
        speech_text = _pick_speech(VOICE_REPORT_OFF_SPEECH)

    await ctx.send(response_text)

    if voice_client and voice_client.channel:
        if voice_client.is_playing():
            print(f"DEBUG: บอทกำลังเล่นเสียง/เปิดเพลงอยู่ จะไม่มีการพูดเสียงแทรกในกิลด์ {guild_id}")
            return
            
        await bagley_speak_wait(guild, speech_text)

def is_developer():
    # 🔧 [แก้ไข] เปลี่ยนจาก app_commands.check (ใช้ได้เฉพาะ interaction) เป็น commands.check
    # เพื่อให้ทำงานได้ทั้งตอนสั่งผ่าน /slash และตอนสั่งผ่าน hybrid_command (รวมถึง AI Router)
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.id in ALLOWED_TEACH_USERS
    return commands.check(predicate)

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

@bot.hybrid_command(name="forget", description="ลบข้อมูลชื่อเล่นหรือวันเกิดของพรรคพวกออกจากคลังสมองของแบ็คลี่")
@app_commands.describe(target="พรรคพวกที่ต้องการให้บอทลืมข้อมูล (หากต้องการลบของตัวเอง ไม่ต้องใส่ช่องนี้)")
async def forget(ctx: commands.Context, target: discord.User = None):
    await ctx.defer()
    
    data_memory = load_user_data()
    reply_text = ""
    
    if target:
        target_id = str(target.id)
        if target_id in data_memory:
            del data_memory[target_id]
            save_user_data(data_memory)
            reply_text = f"เรียบร้อยครับ! ผมกวาดข้อมูลของ คุณ {target.display_name} ออกจากสมองกลเกลี้ยงตับ สะอาดสะอ้านเหมือนไม่เคยรู้จักกันมาก่อนเลยครับ!"
        else:
            reply_text = f"เอ่อ... ครับ ในสมองผมไม่มีข้อมูลของ คุณ {target.display_name} อยู่เลยสักเมกะไบต์ จะให้ผมลบความว่างเปล่าเหรอครับ!"

    # 👤 เคสที่ 2: สั่งให้ลบข้อมูลของ "ตัวเอง"
    else:
        user_id = str(ctx.author.id)
        if user_id in data_memory:
            del data_memory[user_id]
            save_user_data(data_memory)
            reply_text = "รับทราบครับ! ผมทำการล้างสมองตัวเองเกี่ยวกับข้อมูลของคุณเกลี้ยงแล้ว ต่อจากนี้เราคือคนแปลกหน้าในร่างคู่หูคนเดิมครับ!"
        else:
            reply_text = "ฮั่นแน่ คุณแกล้งปั่นหัวสมองกลผมเล่นหรือเปล่าครับ? ข้อมูลคุณผมยังไม่เคยบันทึกไว้เลย จะให้ลบอะไรก่อนครับ!"
                
    await ctx.send(reply_text)

    if ctx.guild and ctx.guild.voice_client:
        vc = ctx.guild.voice_client
        if vc.channel and not vc.is_playing():
            if ctx.author.voice and ctx.author.voice.channel == vc.channel:
                try:
                    import re
                    clean_voice_text = re.sub(r'[^\w\s\u0e00-\u0e7f]+', '', reply_text)
                    await bagley_speak(ctx.guild, clean_voice_text)
                except Exception as tts_err:
                    print(f"🚨 Forget Command TTS Error: {tts_err}")

@bot.hybrid_command(name="imagine", description="สั่งให้แบ็คลี่วาดภาพจากจินตนาการและข้อความ")
@app_commands.describe(prompt="พิมพ์อธิบายภาพที่อยากให้แบ็คลี่วาดได้เลยครับ")
async def imagine(ctx: commands.Context, *, prompt: str):
    await ctx.defer()

    await generate_and_send_image(ctx, prompt)

@bot.hybrid_command(name="sys_cleanup", description="สั่งให้แบ็คลี่เคลียร์แคชและคืนพื้นที่ RAM ของระบบทันที")
async def sys_cleanup(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer()
    
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        msg_denied = f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับ! 🛸"
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
        
    if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
        await bagley_speak(ctx.guild, "กวาดขยะล้างแรมในระบบให้ใสแจ๋วแล้วครับ")

@bot.hybrid_command(name="unfollow_me", description="สั่งให้ Bagley เลิกเดินตามตัวเราเอง")
async def unfollow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        auto_follow_status[user_id] = False
        await ctx.send(f"รับทราบครับ! แบ็คลี่ปิดระบบเดินตามของ {ctx.author.display_name} เรียบร้อยครับ (ท่านอื่นยังตามปกติอยู่น้า)")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะผู้มีสิทธิ์ใช้งานเท่านั้นครับ!")

@bot.hybrid_command(name="follow_me", description="สั่งให้ Bagley กลับมาเดินตามตัวเราอีกครั้ง")
async def follow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        auto_follow_status[user_id] = True
        await ctx.send(f"ระบบ Neural Link เชื่อมต่อใหม่! แบ็คลี่เปิดระบบเดินตามของ {ctx.author.display_name} พร้อมสแตนด์บายแล้วครับ!")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะผู้มีสิทธิ์ใช้งานเท่านั้นครับ!")

@bot.hybrid_command(name="kicktimer", description="ตั้งเวลาตามหน้าปัดนาฬิกาเพื่อดีดพวกนอนหลับคาห้องเสียง")
@app_commands.describe(target_time="ระบุเวลาที่ต้องการให้เตะออก เช่น 03:00, 3.00 หรือใส่แค่เลขชั่วโมง เช่น 3")
async def kick_timer(ctx: commands.Context, target_time: str):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send(f"⚠️ ติดคูลดาวน์รวมครับ รออีก {rem} วินาที", ephemeral=True)

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

    view = KickVoiceView(target_time_str, delay_seconds)
    await ctx.send(f"ครับ! กรุณาเลือกสมาชิกที่คุณต้องการดีดออก ณ เวลา **{target_time_str}** :", view=view)

@bot.hybrid_command(name="kickcancel",description="เลือกยกเลิกรายชื่อคนที่ตั้งเวลาเตะไว้ในเซิร์ฟเวอร์นี้")
async def kick_cancel(ctx: commands.Context):
    can_act, rem = await check_shared_voice_quota(ctx.author.id, ctx.guild)
    if not can_act:
        return await ctx.send(f"⚠️ ติดคูลดาวน์รวมครับ รออีก {rem} วินาที", ephemeral=True)

    guild_id = ctx.guild.id
    has_active_task = any(key[0] == guild_id for key in active_kick_tasks.keys())
    
    if has_active_task:
        view = CancelVoiceView()
        await ctx.send("ครับ! กรุณาเลือกรายชื่อคนที่ต้องการยกเลิกคิวเตะจากเมนูด้านล่างนี้ได้เลยครับ:", view=view)
    else:
        await ctx.send("ไม่มีรายชื่อใครกำลังติดคิวตั้งเวลาเตะในเซิร์ฟนี้เลยครับ!", ephemeral=True)

@bot.hybrid_command(name="memberlist", description="เปิดสมุดคลังความจำดูรายชื่อพรรคพวกในดิสคอร์ด")
@app_commands.describe(scope="เลือกขอบเขต: 'current' ดูเฉพาะเซิร์ฟนี้, 'all' ดูทุกเซิร์ฟเวอร์ (สิทธิ์มาสเตอร์)")
@app_commands.choices(scope=[
    app_commands.Choice(name="ดูเฉพาะเซิร์ฟเวอร์นี้", value="current"),
    app_commands.Choice(name="ระบบตาทิพย์ ดูทุกเซิร์ฟเวอร์ (เฉพาะผู้สร้าง)", value="all")
])
async def member_list(ctx: commands.Context, scope: str = "current"):
    try:
        MY_MASTER_ID = 1133740216822267954
        user_data = load_user_data()

        if not user_data:
            return await ctx.send("ตอนนี้คลังความจำของผมยังว่างเปล่าอยู่เลยครับ")

        formatted_list = []

        if scope == "all" or ctx.guild is None:
            if ctx.author.id != MY_MASTER_ID:
                return await ctx.send("ขออภัยครับ คำสั่งระดับสูงนี้ถูกจำกัดสิทธิ์ไว้เฉพาะผู้สร้างผมขึ้นมาเท่านั้นครับ! 🤫❌", ephemeral=True)
            
            title_text = "👁️ คลังระบบตาทิพย์: รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟ"
            
            for user_id_str, data in user_data.items():
                if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                formatted_list.append(f"<@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})")

        else:
            guild = ctx.guild
            title_text = f"📊 รายชื่อพรรคพวกในดิส '{guild.name}' ที่ผมจำได้"
            
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

        if not formatted_list:
            return await ctx.send("ในขอบเขตนี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับ!")

        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
        view.message = await ctx.send(embed=view.create_embed(), view=view)

    except Exception as e:
        print(f"🚨 ERROR ระบบรายชื่อใหม่: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อครับ")

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
        
        def get_realtime_name(uid, default):
            mem = user_memory.get(str(uid))
            if mem and isinstance(mem, dict):
                if mem.get("admin_nickname") and mem.get("admin_nickname") != "ยังไม่ระบุ":
                    return mem.get("admin_nickname")
                if mem.get("nickname") and mem.get("nickname") != "ยังไม่ระบุ":
                    return mem.get("nickname")
            return default

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
    global room_guard_status, is_playing_music
    
    if not ctx.guild.voice_client:
        return await ctx.send("❌ แบ็คลี่ต้องอยู่ในห้องเสียงก่อนถึงจะสั่งเฝ้าห้องได้ครับ!")

    guild_id = ctx.guild.id
    current_status = room_guard_status.get(guild_id, False)

    # 1. จัดการสถานะตามเงื่อนไขอัจฉริยะ (Toggle หรือ On/Off)
    if mode is None:
        # ถ้าพิมพ์ /guard_room เปล่า ๆ หรือดักคำพูดทั่วไป ให้สลับสถานะ
        new_status = not current_status
    else:
        # ถ้าเลือกช้อยส์หรือมาจากระบบคัดกรองคำพูด
        if mode.lower() in ["on", "เปิด", "start"]:
            new_status = True
        elif mode.lower() in ["off", "ปิด", "stop"]:
            new_status = False

    room_guard_status[guild_id] = new_status

    # 2. ทำงานตามสถานะใหม่ที่เซ็ตไว้
    if room_guard_status[guild_id]:
        text_msg = "🛡️ เปิดโหมดสายตรวจแล้วครับ! แบ็คลี่จะปักหลักเฝ้าห้องเสียงนี้ไว้ให้เอง ไม่หนีไปไหนแน่นอนคัปพ้ม!"
        voice_msg = "เปิดโหมดสายตรวจแล้วครับ ผมจะเฝ้าห้องนี้ไว้ให้เองครับ"
    else:
        text_msg = "🔓 ปิดโหมดสายตรวจแล้วคัปพ้ม ต่อจากนี้ถ้าห้องร้าง แบ็คลี่จะถอนกำลังออกตามปกติถ้าร้างนะ!"
        voice_msg = "ปิดโหมดสายตรวจแล้วครับ ปล่อยตัวตามปกติแล้วคัป"

    # 3. ส่งข้อความในแชท
    await ctx.send(text_msg)
    
    # 4. สั่งให้บอทพูดออกไมค์ (ถ้าไม่ได้เปิดเพลงแช่อยู่)
    if not is_playing_music:
        try:
            await bagley_speak(ctx.guild, voice_msg)
        except Exception as e:
            print(f"Guard Room Speech Error: {e}")

@bot.hybrid_command(name="party_recall", description="ดึงทุกคนในห้องปาร์ตี้ล่าสุดที่เราสร้าง กลับมาที่ห้องเสียงปัจจุบันของเรา")
async def party_recall(ctx: commands.Context):
    # 🔍 เช็กก่อนว่าคุณชะอมอยู่ในห้องเสียงไหม (เพราะเราจะดึงคนมาหาห้องที่เรานั่งอยู่คัป)
    if not ctx.author.voice:
        return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงปลายทางก่อนนะครับ ถึงจะเรียกเพื่อนกลับมาได้!")
        
    target_channel = ctx.author.voice.channel
    guild_id = ctx.guild.id

    # 🔍 หาห้องปาร์ตี้ล่าสุดที่ระบบสร้างขึ้น (ดูจากตัวแปรลิสต์ห้องปาร์ตี้ของกิลด์นี้)
    # สมมติว่าคุณเก็บ ID ไว้ในลิสต์ global ชื่อ created_party_channels
    if not created_party_channels:
        return await ctx.send("❌ แบ็คลี่หาประวัติห้องปาร์ตี้ที่สร้างไว้ไม่เจอเลยครับ!")

    # ดึง ID ห้องล่าสุดที่เพิ่งสร้างขึ้นมา
    last_party_id = created_party_channels[-1]
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

@bot.hybrid_command(name="invite_voice", description="สั่งให้แบ็คลี่วาร์ปไปเปิดไมค์ตื๊อชวนเพื่อนจากห้องอื่นมาเข้าตี้คัปพ้ม")
async def invite_voice(ctx: commands.Context, เพื่อนที่จะชวน: discord.Member):
    await execute_warp_invite(ctx, ctx.author, เพื่อนที่จะชวน)

@bot.hybrid_command(name="remind", description="สั่งให้แบ็คลี่บันทึกกำหนดการและแจ้งเตือนในห้องเสียงเมื่อถึงวัน")
@app_commands.describe(
    date="ระบุวันที่ (เช่น 2026-07-11 หรือใส่แค่ตัวเลขวันที่ เช่น '11')",
    time="ระบุเวลา (เช่น 21:00, 3 ทุ่ม, 5 โมงเย็น)",
    event="กิจกรรมที่ต้องการให้เตือน (เช่น แข่ง VCT, ซ้อมทีม Scrim, ตี้หมูกระทะ)"
)
async def slash_remind(ctx: commands.Context, date: str, time: str, event: str):
    # ดึงเวลาไทยปัจจุบันขึ้นมาอ้างอิง
    now = datetime.now(bangkok_tz)
    clean_date = date.strip()

    # 📅 ระบบช่วยจัดฟอร์แมตวันที่แบบสั้นอัตโนมัติ (กันบั๊กข้ามเดือน)
    if len(clean_date) <= 2 and clean_date.isdigit():
        try:
            day_val = int(clean_date)
            if day_val < now.day:
                # ปัดเป็นวันที่ของเดือนถัดไปอัตโนมัติถ้าตัวเลขวันที่ผ่านมาแล้วในเดือนนี้
                first_of_next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
                target_date = first_of_next_month.replace(day=day_val)
            else:
                target_date = now.replace(day=day_val)
                
            clean_date = target_date.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"DEBUG: 📅 จัดฟอร์แมตวันที่แบบสั้นพลาด: {e}")
            clean_date = now.strftime("%Y-%m-%d")

    # โหลดไฟล์ความจำ JSON ปัจจุบันขึ้นมา
    user_data = load_user_data()
    if "schedules" not in user_data:
        user_data["schedules"] = []
        
    # บันทึกข้อมูลนัดหมายเข้าคลังความจำ
    new_job = {
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
        f"ปล่อยเป็นหน้าที่ของแบ็คลี่ได้เลย! พอถึงวันเดี๋ยวผมบินโดรนแวะเข้าห้องเสียงไปเปิดไมค์แจ้งเตือนให้คัปพ้ม! 🫡"
    )

@bot.hybrid_command(name="schedule_list", description="ดูตารางนัดหมาย/งานทั้งหมดที่คุณฝากแบ็คลี่จำไว้ (จาก /remind)")
async def schedule_list(ctx: commands.Context):
    try:
        user_data = load_user_data()
        schedules = user_data.get("schedules", [])

        my_schedules = [s for s in schedules if str(s.get("owner_id")) == str(ctx.author.id)]

        if not my_schedules:
            return await ctx.send("ตอนนี้คุณยังไม่มีตารางนัดหมายที่ฝากผมจำไว้เลยครับ! ลองฝากไว้ด้วย `/remind` ได้เลยครับ")

        # 🗂️ เรียงตามวันที่ + เวลาก่อน-หลัง (นัดที่ใกล้ถึงก่อนจะขึ้นก่อน)
        def _schedule_sort_key(s):
            try:
                return datetime.strptime(f"{s.get('date', '')} {s.get('time', '')}", "%Y-%m-%d %H:%M")
            except Exception:
                return datetime.max  # ถ้าเวลาไม่ได้เป็นรูปแบบมาตรฐาน (เช่น '3 ทุ่ม') ให้ไปต่อท้ายสุด

        my_schedules_sorted = sorted(my_schedules, key=_schedule_sort_key)

        formatted_list = [
            f"📅 **{s.get('date', 'ไม่ระบุวันที่')}** ⏰ **{s.get('time', 'ไม่ระบุเวลา')}** — 📌 {s.get('event', 'ไม่ระบุกิจกรรม')}"
            for s in my_schedules_sorted
        ]
        title_text = f"🗂️ ตารางนัดหมายของคุณ {ctx.author.display_name}"

        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
        view.message = await ctx.send(embed=view.create_embed(), view=view)

    except Exception as e:
        print(f"🚨 ERROR ระบบดูตารางงาน: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงตารางนัดหมายครับ")

# ============================================================
# 🎲 ระบบสุ่มแบ่งทีมจากคนในห้องเสียง (/split_team)
# ไม่ย้ายห้องใครทั้งนั้น แค่สุ่มแล้วบอกผลเป็นข้อความในแชท
# มีเมนูให้ติ๊กเลือก/ถอดคนที่ไม่ได้เล่นออกก่อนสุ่มได้
# ============================================================
class TeamSplitView(discord.ui.View):
    def __init__(self, author, members, num_teams):
        super().__init__(timeout=120)
        self.author = author
        self.num_teams = num_teams

        # ค่าเริ่มต้น = เลือกทุกคนในห้องไว้ก่อน (ไม่เกิน 25 คนตามกฎ Discord)
        member_options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="🎮", default=True)
            for m in members if not m.bot
        ][:25]

        if not member_options:
            member_options.append(discord.SelectOption(label="ไม่มีคนให้สุ่มคัป", value="none"))

        self.member_select = discord.ui.Select(
            placeholder="ติ๊กเลือกคนที่จะร่วมสุ่มทีม (ค่าเริ่มต้นคือทุกคนในห้อง)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        confirm_btn = discord.ui.Button(label="🎲 สุ่มทีมเลย!", style=discord.ButtonStyle.green)
        confirm_btn.callback = self.confirm_callback
        self.add_item(confirm_btn)

        # ค่าเริ่มต้นตอนยังไม่ได้แตะเมนูเลย = ทุกคนในห้อง
        self.selected_ids = [str(m.id) for m in members if not m.bot]

    async def member_callback(self, interaction: discord.Interaction):
        if self.member_select.values and self.member_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีใครให้สุ่มเลยคัป!", ephemeral=True)

        self.selected_ids = self.member_select.values
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"Team split member_callback error: {e}")

    async def confirm_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("ต้องเป็นคนสั่งสุ่มทีมเท่านั้นถึงจะกดยืนยันได้ครับ!", ephemeral=True)

        if not self.selected_ids:
            return await interaction.response.send_message("ยังไม่ได้เลือกใครเลยครับ รบกวนเลือกก่อนนะ!", ephemeral=True)

        chosen_members = []
        for m_id in self.selected_ids:
            if m_id == "none":
                continue
            member = interaction.guild.get_member(int(m_id))
            if member:
                chosen_members.append(member)

        if len(chosen_members) < self.num_teams:
            return await interaction.response.send_message(
                f"❌ คนที่เลือกมีแค่ {len(chosen_members)} คน แต่จะแบ่ง {self.num_teams} ทีมไม่พอครับ!",
                ephemeral=True
            )

        # 🎲 สุ่มลำดับแล้วแจกเข้าทีมแบบวนรอบ (จำนวนคนในแต่ละทีมจะเท่ากันที่สุดเท่าที่จะทำได้)
        random.shuffle(chosen_members)
        teams = [[] for _ in range(self.num_teams)]
        for idx, member in enumerate(chosen_members):
            teams[idx % self.num_teams].append(member)

        report_lines = ["🎲 **ผลการสุ่มทีมจากแบ็คลี่!**\n"]
        for i, team in enumerate(teams, 1):
            names = "\n".join(f"• {m.display_name}" for m in team)
            report_lines.append(f"**ทีม {i}**\n{names}\n")
        report = "\n".join(report_lines)

        for item in self.children:
            item.disabled = True

        try:
            await interaction.response.edit_message(content=report, view=self)
        except discord.NotFound:
            await interaction.channel.send(report)
        except Exception as e:
            print(f"❌ ระบบสุ่มทีมพัง: {e}")
            try:
                await interaction.response.send_message(report)
            except Exception:
                pass

        # 🔊 พูดสรุปผลออกไมค์ ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว
        if interaction.guild.voice_client:
            team_names_spoken = " ".join(
                f"ทีม {i} มี {', '.join(m.display_name for m in team)}"
                for i, team in enumerate(teams, 1)
            )
            try:
                await bagley_speak(interaction.guild, f"สุ่มทีมเรียบร้อยครับ {team_names_spoken}")
            except Exception as e:
                print(f"Team split speak error: {e}")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

@bot.hybrid_command(name="split_team", description="สั่งให้แบ็คลี่สุ่มแบ่งทีมจากคนในห้องเสียงปัจจุบัน (แค่บอกผลในแชท ไม่ย้ายห้องใคร)")
@app_commands.describe(teams="จำนวนทีมที่ต้องการแบ่ง (ค่าเริ่มต้น 2 ทีม)")
async def split_team(ctx: commands.Context, teams: int = 2):
    # 🛡️ กันเคส AI Command Router ส่ง teams มาเป็น string (เช่น "3") แทนที่จะเป็น int
    try:
        teams = int(teams)
    except (TypeError, ValueError):
        return await ctx.send("❌ จำนวนทีมต้องเป็นตัวเลขนะครับ เช่น 2, 3, 4")

    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงก่อนนะครับ แบ็คลี่ถึงจะรู้ว่าจะสุ่มทีมจากห้องไหน!")

    if teams < 2:
        return await ctx.send("❌ ต้องแบ่งอย่างน้อย 2 ทีมนะครับ!")

    voice_channel = ctx.author.voice.channel
    members = [m for m in voice_channel.members if not m.bot]

    if len(members) < teams:
        return await ctx.send(f"❌ ในห้องเสียง **{voice_channel.name}** มีแค่ {len(members)} คน แต่จะแบ่ง {teams} ทีมไม่พอครับ!")

    view = TeamSplitView(ctx.author, members, teams)
    await ctx.send(
        f"🎲 พร้อมสุ่มทีมจากห้อง **{voice_channel.name}** แล้วครับ! (ตอนนี้เลือกไว้ทุกคน {len(members)} คน แบ่งเป็น {teams} ทีม)\n"
        f"ถ้ามีใครไม่ได้เล่นด้วย ติ๊กเลือกใหม่ในเมนูด้านล่างเพื่อถอดออกได้เลยครับ แล้วกด **'🎲 สุ่มทีมเลย!'**",
        view=view
    )

# ============================================================
# 🗺️ ระบบสุ่มแมพเกม (/random_map) — แยกจากสุ่มทีม
# ผู้ใช้พิมพ์รายชื่อแมพเอง (คั่นด้วย , หรือขึ้นบรรทัดใหม่) แบ็คลี่แค่สุ่มให้ฝั่ง Python
# (เดิมใช้ Gemini + Google Search ไปค้นชื่อแมพ แต่โควต้า grounding แยกจากแชทปกติ
#  และจำกัดกว่ามาก ทำให้ 429 บ่อย เลยตัดการพึ่ง AI ออกไปเลย ไม่ต้องยิง API เพิ่ม)
# ============================================================

_MAP_SPLIT_PATTERN = regex_lib.compile(r"[,\n、，]+")


def _parse_map_list(raw: str):
    """แยกรายชื่อแมพจากข้อความดิบ คั่นด้วย , หรือขึ้นบรรทัดใหม่
    ตัดช่องว่างหน้า-หลัง และตัดตัวซ้ำ (ไม่สนตัวพิมพ์เล็ก/ใหญ่) โดยคงชื่อแบบแรกที่เจอไว้
    """
    seen = set()
    result = []
    for part in _MAP_SPLIT_PATTERN.split(raw or ""):
        name = part.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


@bot.hybrid_command(
    name="random_map",
    description="สุ่มแมพจากรายชื่อที่คุณพิมพ์มาเอง (คั่นด้วย , หรือขึ้นบรรทัดใหม่)"
)
@app_commands.describe(
    maps="รายชื่อแมพทั้งหมด คั่นด้วยจุลภาค (,) เช่น Bind, Haven, Ascent, Icebox",
    count="จำนวนแมพที่อยากให้สุ่ม (ค่าเริ่มต้น 1 แมพ)"
)
async def random_map(ctx: commands.Context, maps: str, count: int = 1):
    # 🛡️ กันเคส AI Command Router ส่ง count มาเป็น string (เช่น "2") แทนที่จะเป็น int
    try:
        count = int(count)
    except (TypeError, ValueError):
        return await ctx.send("❌ จำนวนแมพต้องเป็นตัวเลขนะครับ เช่น 1, 2, 3")

    map_list = _parse_map_list(maps)

    if len(map_list) < 2:
        return await ctx.send(
            "❌ พิมพ์รายชื่อแมพมาหลาย ๆ แมพหน่อยครับ คั่นด้วยจุลภาค (,) หรือขึ้นบรรทัดใหม่ก็ได้ "
            "เช่น `/random_map maps: Bind, Haven, Ascent, Icebox`"
        )

    count = max(1, min(count, len(map_list)))

    if count >= len(map_list):
        picked = map_list[:]
        random.shuffle(picked)
    else:
        picked = random.sample(map_list, count)

    if len(picked) == 1:
        result_text = f"🗺️ สุ่มจากทั้งหมด {len(map_list)} แมพที่ให้มา... ได้ **{picked[0]}** ครับ!"
    else:
        lines = "\n".join(f"{i}. {m}" for i, m in enumerate(picked, 1))
        result_text = f"🗺️ สุ่มจากทั้งหมด {len(map_list)} แมพที่ให้มา ได้ {len(picked)} แมพครับ!\n{lines}"

    await ctx.send(result_text)

    if ctx.guild:
        try:
            await bagley_speak(ctx.guild, f"สุ่มแมพได้ {', '.join(picked)} ครับ")
        except Exception as e:
            print(f"Random map speak error: {e}")

bot.run(DISCORD_TOKEN)