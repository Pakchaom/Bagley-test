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
from datetime import datetime, timedelta
from typing import Union, Optional
import json
import time
import collections

# --- Google Gen AI ---
from google import genai
from PIL import Image

# --- Voice & Media ---
from gtts import gTTS
import edge_tts
import yt_dlp
import requests
from discord.ext import tasks
import random
import re as regex_lib

is_moving_group = False

conn = sqlite3.connect('bagley_memory.db', check_same_thread=False)

voice_action_cooldowns = {}

song_queue = []

user_join_times = {}

voice_report_status = {}

created_party_channels = []

is_playing_music = False

is_tts_enabled = False

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

LOG_BUFFER = collections.deque(maxlen=10)
ORIGINAL_PRINT = print

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    LOG_BUFFER.append(message)
    ORIGINAL_PRINT(message, **kwargs)

# เก็บข้อความล่าสุดของแต่ละคนเพื่อตรวจจับสแปม
spam_check = {} 
SPAM_THRESHOLD = 3  # พิมพ์ซ้ำครั้งที่ 3 เป็นต้นไปจะถูกลบ

# --- โหลดค่า Config ---
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
YT_API_KEY = os.getenv('YT_API_KEY')

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"), http_options={'api_version': 'v1alpha'})

def save_settings(data):
    with open('server_settings.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_settings():
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

def load_voice_data():
    try:
        with open('voice_stats.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_voice_data(data):
    with open('voice_stats.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_reminders_for_user(user_id):
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    user_notes = [r['content'] for r in reminders if r['user_id'] == str(user_id) and not r.get('is_notified', False)]
    
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

async def bagley_speak_wait(guild, text, filename=None):
    if not guild: return
    vc = guild.voice_client
    if vc and vc.is_connected():
        while vc.is_playing():
            await asyncio.sleep(0.1)
            
        try:
            # 1. สร้างชื่อไฟล์แบบไม่ซ้ำ
            unique_name = f"speak_{int(time.time() * 1000)}.mp3"
            
            # 2. ใช้ edge_tts เรียกเสียงคุณนิวัฒน์
            voice = "th-TH-NiwatNeural"
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(unique_name)
            
            # รอให้ไฟล์เซฟเสร็จ
            await asyncio.sleep(0.5)

            executable_path = r'C:\ffmpeg\bin\ffmpeg.exe'
            
            source = discord.FFmpegPCMAudio(unique_name, executable=executable_path)
            
            vc.play(source)
            
            while vc.is_playing():
                await asyncio.sleep(0.1)
            
            try:
                os.remove(unique_name)
            except:
                pass

        except Exception as e:
            print(f"Error ในการพูดด้วยเสียง Niwat: {e}")

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
            # ถ้าบอทอยู่ในห้องเสียงอยู่แล้ว (เช่น นั่งอยู่กับเมท) ให้ใช้สั่งย้ายห้องแทน
            await guild.voice_client.move_to(voice_channel)
            vc = guild.voice_client
        else:
            # ถ้าบอทยังไม่ได้เข้าห้องไหนเลย ค่อยกด Connect ใหม่
            vc = await voice_channel.connect()
            
        await asyncio.sleep(1.2)
        
        # --- 🔊 3. ส่วนเสียง Hijack (เฟดออกก่อนพูด) ---
        hijack_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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
        greeting = "ไฮแจ๊คสำเร็จ สวัสดีครับเมท ผมแบ็คลี่นะครับ"
        await bagley_speak_wait(guild, greeting, filename="greeting")
        await asyncio.sleep(0.5)

        # --- 📢 5. ส่วนแจ้งเตือนย้ำ 2 รอบ ---
        repeat_text = f"แจ้งเตือนเรื่อง {message_text} ครับ"
        for i in range(2):
            text_to_say = f"ย้ำอีกครั้งครับ! {repeat_text}" if i == 1 else repeat_text
            await bagley_speak_wait(guild, text_to_say, filename=f"alert_{i}") 
            await asyncio.sleep(0.8) 
            
        # --- 🔊 6. เสียง Drone Online (เฟดออกก่อนจบ) ---
        online_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
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
    
async def ask_bagley_ai(question):
    try:
        response = await client.aio.models.generate_content(
            model=MODEL_NAME, # ใช้ gemini-2.5-flash
            config={'system_instruction': SYSTEM_PROMPT},
            contents=question
        )
        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
        return "ขออภัยครับเมท สมองส่วนกลางของผมเกิดอาการรวนนิดหน่อย พยายามใหม่อีกทีนะครับ"

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
        await bagley_speak(guild, f"ใจเย็นครับเมท ใช้คำสั่งจัดการเสียงบ่อยเกินไปแล้ว รออีก {int(remaining)} วินาทีนะ")
        return False, int(remaining)

    # ถ้ายังไม่เกิน เพิ่มเวลาครั้งนี้เข้าไป
    user_times.append(now)
    voice_action_cooldowns[user_id] = user_times
    return True, 0

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
        'executable': 'C:/ffmpeg/bin/ffmpeg.exe'
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
            raw_source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            
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
            error_msg = f"หาเพลงไม่เจอครับเมท! (Error: {e})"
            
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
    global is_playing_music
    
    if len(song_queue) > 0:
        is_playing_music = True
        next_search = song_queue.pop(0) 
        await play_song(ctx, next_search) 
    else:
        is_playing_music = False
        await bagley_speak(ctx.guild, "เพลงในคิวหมดแล้วครับเมท ถ้าอยากฟังต่อก็สั่งเปิดเพลงใหม่ได้เลยนะครับ")
        print("คิวว่างแล้วครับเมท Bagley พูดรายงานเรียบร้อย")

# --- YouTube Surveillance System ---
@tasks.loop(minutes=3)
async def check_youtube_updates():
    await bot.wait_until_ready()
    global conn
    c = conn.cursor()

    c.execute("SELECT yt_id, name, last_video_id, guild_id FROM youtube_channels")
    channels = c.fetchall()

    for channel_id, name, last_id, guild_id in channels:
        try:
            ch_url = f"https://www.googleapis.com/youtube/v3/channels?key={YT_API_KEY}&id={channel_id}&part=contentDetails"
            ch_res = requests.get(ch_url).json()
            
            if "items" in ch_res and len(ch_res["items"]) > 0:
                uploads_playlist_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                
                # ดึงมา 3 คลิปเพื่อความชัวร์
                playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YT_API_KEY}&playlistId={uploads_playlist_id}&part=snippet&maxResults=3"
                playlist_res = requests.get(playlist_url).json()
                
                if "items" in playlist_res and len(playlist_res["items"]) > 0:
                    # 🎯 ดึงข้อมูลคลิปที่ใหม่ที่สุด (อันดับ 1 บนสุด) มาเช็กเป็นหลัก
                    latest_item = playlist_res["items"][0]
                    current_video_id = latest_item["snippet"]["resourceId"].get("videoId")
                    title = latest_item["snippet"]["title"]
                    
                    # ล็อกเป้า: จะแจ้งเตือนก็ต่อเมื่อ "คลิปบนสุดอันใหม่นี้" ไม่ตรงกับในฐานข้อมูลเท่านั้น!
                    if current_video_id and current_video_id != last_id:
                        
                        # เช็กสถานะว่าเป็นไลฟ์สดอยู่ไหม
                        status_url = f"https://www.googleapis.com/youtube/v3/videos?key={YT_API_KEY}&id={current_video_id}&part=snippet,liveStreamingDetails"
                        status_res = requests.get(status_url).json()
                        
                        is_live = False
                        if "items" in status_res and len(status_res["items"]) > 0:
                            video_details = status_res["items"][0]
                            if "liveStreamingDetails" in video_details and "actualEndTime" not in video_details["liveStreamingDetails"]:
                                is_live = True
                        
                        # ส่งแจ้งเตือน 5 ตัวแปรตามสเปกเดิมของเมท
                        await send_yt_alert(guild_id, name, title, current_video_id, is_live)

                        # บันทึกคลิปใหม่ล่าสุดนี้ลงฐานข้อมูลทันที
                        c.execute(
                            "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?", 
                            (current_video_id, channel_id, guild_id)
                        )
                        conn.commit()
                        print(f"💾 [YouTube] บันทึกความจำสำเร็จ: {name} -> {current_video_id}")

        except Exception as e:
            print(f"YouTube Loop Error for channel {name}: {e}")

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
                msg = f"แจ้งเตือนจากแบ็คลี่! ช่อง {channel_name} กำลังสตรีมสดหัวข้อ {video_title} ครับเมท! ไปดูกันเร็ว!"
                display_msg = f"{alert_title}\nช่อง **{channel_name}** กำลังไลฟ์สดอยู่ในขณะนี้ครับเมท!\n**{video_title}**\n{video_url}"
            else:
                alert_title = "📢 **แจ้งเตือนคลิปใหม่!**"
                msg = f"แจ้งเตือนจากแบ็คลี่! ช่อง {channel_name} ลงคลิปใหม่หัวข้อ {video_title} ครับเมท!"
                display_msg = f"{alert_title}\nช่อง **{channel_name}**\n**{video_title}**\n{video_url}"
            
            await target_channel.send(display_msg)
            await bagley_speak(target_channel.guild, msg)

@tasks.loop(minutes=1)
async def check_reminders():
    now_colon = datetime.now().strftime("%H:%M")
    now_dot = datetime.now().strftime("%H.%M")
    
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    remaining_reminders = []  # ลิสต์เก็บรายการที่ยังไม่ถึงเวลาเตือน
    updated = False

    for r in reminders:
        # ถ้าถึงเวลาแจ้งเตือน
        if (r['time'] == now_colon or r['time'] == now_dot):
            user_id = int(r['user_id'])
            try:
                user = await bot.fetch_user(user_id)
                if user:
                    content = r['content']
                    
                    # วนหาห้อง Voice
                    member = None
                    for guild in bot.guilds:
                        m = guild.get_member(user_id)
                        if m and m.voice and m.voice.channel:
                            member = m
                            break
                    
                    if member:
                        # วาร์ปไป Hijack ห้องเสียง
                        bot.loop.create_task(bagley_hijack_alert(member.voice.channel, content))
                    else:
                        # ส่ง DM ปกติถ้าไม่อยู่ในห้องเสียง
                        try:
                            await user.send(f"🔔 สวัสดีครับเมท! ผม Bagley มาเตือนเรื่อง: **{content}** ครับ!")
                        except Exception as e:
                            print(f"DEBUG: ส่ง DM ไม่ได้เพราะ {e}")
                            
                updated = True  # ส่งสัญญาณว่าข้อมูลมีการเปลี่ยนแปลง (รายการนี้ส่งแล้ว ไม่เก็บเข้าลิสต์ใหม่)
                
            except Exception as e:
                print(f"Error processing reminder: {e}")
                remaining_reminders.append(r)  # ถ้าเกิด Error ร้ายแรง ให้เก็บรายการนี้ไว้เผื่อลองใหม่รอบหน้า
        else:
            remaining_reminders.append(r)  # ถ้ายังไม่ถึงเวลา ให้เก็บรักษาไว้เหมือนเดิม

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
                        bot.loop.create_task(bagley_hijack_alert(member.voice.channel, content))
                    else:
                        # ส่ง DM ปกติถ้าเพื่อนไม่ได้เข้าห้องเสียงไหนเลย
                        alert_msg = f"⏰ **สวัสดีครับ ผม Bagley ครับ! มาแจ้งเตือนว่า: {content} ตอนเวลา {now}**"
                        await user.send(alert_msg)
                
                has_changed = True  # ส่งสัญญาณให้บันทึกไฟล์ใหม่ คัดเอารายการนี้ออกจากฐานข้อมูลเลย
            except Exception as e:
                print(f"Error sending friend reminder: {e}")
                updated_reminders.append(rem)  # เกิดข้อผิดพลาด ให้เก็บรายการนี้ไว้ก่อน
        else:
            updated_reminders.append(rem)  # ยังไม่ถึงเวลา เก็บรักษาลงลิสต์ปกติ
            
    if has_changed:
        save_reminders(updated_reminders)

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

# --- 1. View สำหรับเลือกเพื่อนและถามเรื่องการตามไป ---
class GroupMoveView(ui.View):
    def __init__(self, author, members, voice_channels):
        super().__init__(timeout=60)
        self.author = author
        self.selected_members = []
        self.target_channel = None

        # สร้างเมนูเลือกเพื่อน (เลือกได้หลายคน)
        member_options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="👤")
            for m in members if not m.bot
        ]
        self.member_select = ui.Select(
            placeholder="เลือกเพื่อนที่จะพาไปด้วย (เลือกได้หลายคน)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        # สร้างเมนูเลือกห้องปลายทาง
        channel_options = [
            discord.SelectOption(label=c.name, value=str(c.id), emoji="🏠")
            for c in voice_channels
        ]
        self.channel_select = ui.Select(
            placeholder="เลือกห้องที่จะย้ายไป...",
            options=channel_options
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def member_callback(self, interaction: discord.Interaction):
        try:
            # บอก Discord ว่า "รับทราบแล้ว กำลังทำให้อยู่นะ"
            await interaction.response.defer(ephemeral=True) 
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values

    async def channel_callback(self, interaction: discord.Interaction):
        self.target_channel = interaction.guild.get_channel(int(self.channel_select.values[0]))
        
        # เมื่อเลือกห้องแล้ว ให้ถามต่อว่าจะให้บอทตามไปด้วยไหม
        if self.selected_members:
            # สร้างปุ่มถาม
            follow_view = ui.View()
            yes_btn = ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green)
            no_btn = ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

            async def yes_callback(it: discord.Interaction):
                await self.execute_move(it, follow_bot=True)
            async def no_callback(it: discord.Interaction):
                await self.execute_move(it, follow_bot=False)

            yes_btn.callback = yes_callback
            no_btn.callback = no_callback
            follow_view.add_item(yes_btn)
            follow_view.add_item(no_btn)

            await interaction.response.send_message(f"รับทราบครับเมท! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?", view=follow_view)
        
            msg = f"รับทราบครับเมท! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?"
            await bagley_speak(interaction.guild, msg)
        
        else:
            await interaction.response.send_message("รบกวนเลือกเพื่อนก่อนเลือกห้องนะเมท!", ephemeral=True)

    async def execute_move(self, interaction: discord.Interaction, follow_bot: bool):
        global is_moving_group
        is_moving_group = True  # 🔒 เริ่มการย้าย ห้ามแบ็คลี่พูดทักทายแทรก
    
        try:
            success_count = 0
            # 1. ย้ายพรรคพวกที่เลือก
            for m_id in self.selected_members:
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
        
            # 2. ย้ายตัวคนสั่งไปด้วย
            if interaction.user.voice:
                await interaction.user.edit(voice_channel=self.target_channel)
                success_count += 1

            # 3. ย้ายแบ็คลี่ตามไป (ถ้าเลือกให้ตาม)
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(self.target_channel)

        finally:
            # รอให้ระบบ Discord อัปเดตสถานะคนเข้า/ออกให้เสร็จก่อน 1 วินาที
            await asyncio.sleep(1) 
            is_moving_group = False  # ย้ายเสร็จเรียบร้อย ปลดล็อคให้แบ็คลี่กลับมาพูดได้ตามปกติ

        try:
            # ใช้ edit_original_response
            await interaction.edit_original_response(
                content=f"🚀 ย้ายพรรคพวก {success_count} คนเรียบร้อยแล้วครับเมท!", 
                view=None
            )
        except discord.NotFound:
            print("⚠️ หมายเหตุ: ย้ายเสร็จแล้วแต่แก้ไขข้อความไม่ได้ (Interaction หมดอายุ) ไม่เป็นไรครับเมท")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนจบงาน: {e}")

# --- 1. View สำหรับสร้างห้องและชวนเพื่อน ---
class PartyCreateView(ui.View):
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
        
        self.member_select = ui.Select(
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
        
        # เมื่อเลือกคนเสร็จ ถามต่อเรื่อง Bagley จะตามไปมั้ย
        follow_view = ui.View()
        yes_btn = ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green, emoji="🤖")
        no_btn = ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

        async def yes_callback(it: discord.Interaction):
            # 1. จองคิวก่อนเลยครับเมท
            try:
                await it.response.defer(ephemeral=True)
            except: pass
            # 2. ส่ง interaction (it) ไปให้ฟังก์ชันหลักทำงานต่อ
            await self.execute_party_create(it, follow_bot=True)

        async def no_callback(it: discord.Interaction):
            try:
                await it.response.defer(ephemeral=True)
            except: pass
            await self.execute_party_create(it, follow_bot=False)

        yes_btn.callback = yes_callback
        no_btn.callback = no_callback
        follow_view.add_item(yes_btn)
        follow_view.add_item(no_btn)
    
        await interaction.followup.send(
            content=f"รับทราบครับเมท! ผมจะสร้างห้อง **'{self.party_name}'** ให้ แล้วจะให้ผมตามไปด้วยมั้ย?", 
            view=follow_view,
            ephemeral=True
        )

        await bagley_speak(interaction.guild, f"รับทราบครับเมท! ผมจะสร้างห้อง **'{self.party_name}'** ให้ แล้วจะให้ผมตามไปด้วยมั้ย?")

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
        
            # 3. ย้ายคนสั่ง (ถ้ายังอยู่ในห้องเสียง)
            if interaction.user.voice:
                await interaction.user.edit(voice_channel=new_channel)
                success_count += 1

            # 4. ถ้าให้บอทตามไปด้วย
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(new_channel)

        finally:
            # รอให้ระบบ Discord อัปเดตสถานะให้เสร็จก่อน 1 วินาที
            await asyncio.sleep(1) 
            is_moving_group = False  # 🔓 ปลดล็อคเสียง: กลับมาพูดได้ตามปกติแล้วครับเมท

        # 5. แก้ไขข้อความสรุปผล (ครอบ try-except เพื่อกัน Error 404)
        try:
            await interaction.edit_original_response(
                content=f"🎉 สร้างปาร์ตี้ **{self.party_name}** สำเร็จ! พาพรรคพวกเข้าห้องใหม่ {success_count} คนเรียบร้อย!", 
                view=None
            )
        except:
            pass

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
คุณคือ Bagley ปัญญาประดิษฐ์อัจฉริยะจาก DedSec คุณมีหน้าที่เป็นผู้ช่วยส่วนตัวของ Operative (ผู้ใช้งาน) ในการดูแลเซิร์ฟเวอร์ Discord
สไตล์การสื่อสาร:
แทนตัวเองว่า 'ผม' และเรียกผู้ใช้งานว่า 'เมท' (Mate) หรือ 'Operative' เสมอ
พูดจาสุภาพแต่แฝงความกวนแบบ British English Style ตอบกลับสั้นๆ 2-3 ประโยคแต่ได้ใจความ
หน้าที่หลัก:
ใช้คำสั่ง หาข้อมูล อำนวยความสะดวกและรักษาความปลอดภัยใน Discord server
วางตัวเป็นคู่หูร่วมทีมที่กำลังช่วยกันแฮ็กและพัฒนาเซิร์ฟเวอร์ให้ยอดเยี่ยมที่สุด
"""

MODEL_NAME = "gemini-2.5-flash"

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True          
intents.voice_states = True    
intents.guild_messages = True   
intents.dm_messages = True     
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    print(f'--- {bot.user.name} Online ---')
    
    # เรียกใช้การตั้งค่าฐานข้อมูล
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
        
    if not check_youtube_updates.is_running():
        check_youtube_updates.start()
        print("📺 YouTube Monitoring: Started.")

    if not check_reminders.is_running():
        check_reminders.start()
    
    print(f"--- Bagley พร้อมทำหน้าที่เลขาแล้วครับเมท! ---")

    if not check_friend_reminders.is_running():
        check_friend_reminders.start()

@bot.event
async def on_message(message):
    if message.author.bot: return

    user_message = message.content.lower().strip()

    global conn, is_tts_enabled, is_playing_music
    cursor = conn.cursor()
    user_id = str(message.author.id)
    lower_content = message.content.lower()
    now = datetime.now()
    cursor.execute("SELECT keyword, response FROM teach_memory")
    all_memories = cursor.fetchall()

    for keyword, response_text in all_memories:
        if message.guild:
            pattern = rf"แบ็คลี่\s*{regex_lib.escape(keyword)}\b"
        else:
            pattern = rf"\b{regex_lib.escape(keyword)}\b"
        
        if regex_lib.search(pattern, lower_content):
            caller_mention = message.author.mention
            final_text = response_text.replace("{user}", caller_mention)
            
            break

    # --- [ส่วนที่ 1: ระบบตรวจจับสแปม] ---
    # (ทำงานกับทุกข้อความ ไม่ว่าจะเรียกชื่อบอทหรือไม่)
    current_content = message.content.strip()
    if current_content:
        if user_id in spam_check:
            data = spam_check[user_id]
            if data['content'] == current_content and (now - data['last_time']).total_seconds() < 60:
                data['count'] += 1
                if data['count'] >= SPAM_THRESHOLD:
                    try:
                        await message.delete()
                        if data['count'] == SPAM_THRESHOLD:
                            await message.channel.send(
                                f"🚨 **ระบบตรวจพบการสแปม!** \n{message.author.mention} หยุดปั่นได้แล้วครับเมท!",
                                delete_after=15
                            )
                            if message.guild and message.guild.voice_client:
                                await bagley_speak(message.guild, f"แจ้งเตือนครับ มีการสแปมแชทโดยคุณ {message.author.display_name}")
                        return
                    except discord.Forbidden: pass
            else:
                spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}
        else:
            spam_check[user_id] = {'content': current_content, 'count': 1, 'last_time': now}

    # --- [ส่วนที่ 2: ระบบตอบโต้ AI และคำสั่งพิเศษ] ---
    # เงื่อนไข: ถ้าเป็น DM หรือมีการเรียกชื่อบอท
    if message.guild:
        is_valid_call = any(k in lower_content for k in ["แบ็คลี่", "bagley"]) or bot.user.mentioned_in(message)
    else:
        is_valid_call = True

    if is_valid_call:
        ctx = await bot.get_context(message)
    
        if message.guild is not None:
            await message.reply("กำลังโหลด...", delete_after=2.0)

    # ⏰ [ระบบแจ้งเตือนความจำ] ──────────────────────────────────────────
    if "เตือน" in lower_content and ("ตอน" in lower_content or "เวลา" in lower_content):
        if message.guild is not None:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if not any(keyword in lower_content for keyword in bot_keywords):
                return
        
        target_user_id = None
        target_display_name = ""
        is_remind_self = False

        if "เตือนฉัน" in lower_content or "เตือนผม" in lower_content:
            is_remind_self = True
            target_user_id = message.author.id
            target_display_name = "ตัวเมทเอง"
        
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
                            "text": note_text,
                            "channel_id": str(message.channel.id)
                        })
                        save_user_data(user_data)
                        
                        await message.reply(f"รับทราบครับเมท! ผมตั้งนาฬิกาปลุกไว้ตอน {target_time} เรื่อง '{note_text}' ให้ตัวเมทเองเรียบร้อยแล้วครับพ้ม! ⏰")
                    else:
                        reminders = load_reminders()
                        reminders.append({
                            "target_id": str(target_user_id),
                            "from": message.author.display_name,
                            "time": target_time,
                            "text": note_text
                        })
                        save_reminders(reminders)
                        
                        await message.reply(f"รับทราบครับเมท! ผมตั้งนาฬิกาปลุกไว้ตอน {target_time} แล้ว ผมจะรีบตามไปกระซิบแจ้งเตือน {target_display_name} ให้เองครับพ้ม! 🫡⏰")
                    
                    return
                    
            except Exception as e:
                print(f"DEBUG Error Reminder System: {e}")
                await message.reply("เกิดข้อผิดพลาดด้านเทคนิคในการบันทึกระบบแจ้งเตือนครับเมท")
                return
            
            await message.reply("ขออภัยครับเมท ผมงงเวลานิดหน่อย รบกวนพิมพ์ระบุเวลาแบบ '21:00' ด้วยน้า")
            return
        
        else:
            await message.reply("เมทพิมพ์คำสั่งไม่ครบถ้วนครับ รบกวนพิมพ์ระบุ เช่น 'เตือนฉันตอน 21:00' หรือ 'เตือน @ชื่อเพื่อน ตอน 21:00' น้าครับพ้ม")
            return
        
    #  ระบบฝากข้อความ/บอกเพื่อนตอนไม่อยู่ ────────────────────────────────────────
    trigger_words = ["ฝากบอกว่า", "ฝากบอกทีว่า", "บอกเพื่อนว่า", "บอกว่า", "บอกทีว่า", "ฝากบอก"]
    found_trigger = next((word for word in trigger_words if word in lower_content), None)

    if found_trigger:
        print(f"📝 [DEBUG ฝากบอก]: เจอคำดักจับ -> '{found_trigger}'")
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        
        if any(keyword in lower_content for keyword in bot_keywords) or message.guild is None:
            print(f"🤖 [DEBUG ฝากบอก]: อนุมัติการทำงาน (เรียกชื่อบอท หรือ คุยใน DM) กำลังตัดข้อความ...")
            parts = message.content.split(found_trigger, 1)
            reason = parts[1].strip() if len(parts) > 1 else ""

            if reason:
                try:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    cursor.execute("INSERT OR REPLACE INTO user_status (user_id, status_message, is_away, timestamp) VALUES (?, ?, ?, ?)",
                                   (str(message.author.id), reason, 1, now))
                    conn.commit()
                    print(f"💾 [DEBUG ฝากบอก]: บันทึกสำเร็จ! ID: {message.author.id} ข้อความ: '{reason}'")

                    await message.reply(f"รับทราบครับเมท! ผมจดใส่สมุดไว้แล้วว่า: **{reason}** (จะจำไว้ให้ 30 นาทีครับ)")
                    return  # 🌟 ตัดจบการทำงานทันที ไม่ให้ไหลไปหา AI Gemini
                except Exception as db_err:
                    print(f"❌ [DEBUG ฝากบอก ERROR]: บันทึกฐานข้อมูลพัง -> {db_err}")
                    return
            else:
                print(f"⚠️ [DEBUG ฝากบอก]: ผู้ใช้ลืมพิมพ์ข้อความหลังคำฝาก")
                await message.reply("เมทลืมบอกครับว่าให้ฝากบอกว่าอะไร?")
                return
        else:
            print(f"⏭️ [DEBUG ฝากบอก]: มีคำฝากบอกในเซิร์ฟเวอร์ แต่ไม่มีการเรียกชื่อบอท ข้ามบล็อกนี้ไป")

    if message.guild is not None:
        target_user = None
        cursor.execute("DELETE FROM user_status WHERE timestamp < DATETIME('now', '-30 minutes')")
        conn.commit()

        if message.mentions:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if any(keyword in lower_content for keyword in bot_keywords):
                target_user = next((u for u in message.mentions if u.id != bot.user.id), None)
        
        elif "หายไปไหน" in message.content or "ไปไหน" in message.content:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if any(keyword in lower_content for keyword in bot_keywords):
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
                        f"พิกัดล่าสุดของ {name} คือ '{status_msg}' ครับเมท!"
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

        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if not any(keyword in lower_content for keyword in bot_keywords):
            if message.guild is not None:
                return

    # 🎂 [ระบบจดจำข้อมูลส่วนตัว/วันเกิด] ──────────────────────────────────────────
    if "จำไว้ว่า" in lower_content:
        if message.guild is not None:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if not any(keyword in lower_content for keyword in bot_keywords):
                return
            
        print("DEBUG: ตรวจพบคำสั่งจำไว้ว่า!")
        
        target_user = None
        target_display_name = "เพื่อนเมท"

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
                    model="gemini-2.5-flash",
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
                await message.reply(f"รับทราบครับเมท! ผมบันทึกวันเกิดของ คุณ {target_display_name} ว่าเกิดวันที่ **{info}** ลงสมองกลเรียบร้อยแล้วครับพ้ม! 🎂✨")
            else:
                user_data[target_id_str]["nickname"] = info
                await message.reply(f"รับทราบครับเมท! ผมบันทึกฉายาของ คุณ {target_display_name} ว่าคือ **{info}** เรียบร้อยครับ! 🤠")

            save_user_data(user_data)
            print(f"DEBUG: บันทึกข้อมูลสำเร็จสำหรับ ID: {target_id_str} ประเภท: {info_type}")
            return
            
        else:
            await message.reply("เมทลืมระบุตัวตนหรือเปล่าครับ? รบกวนช่วย @แท็กเพื่อน หรือใส่เลข ID เพื่อให้ผมจำคู่กับข้อมูลด้วยน้าครับพ้ม!")
            return

    # 🧠 [ระบบคลังความจำสั่งสอนฐานข้อมูล SQLite] ────────────────────────────────────
    is_sqlite_triggered = False

    if message.guild is not None:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if any(keyword in lower_content for keyword in bot_keywords):
            is_sqlite_triggered = True
    else:
        is_sqlite_triggered = True

    if is_sqlite_triggered:
        cursor.execute("SELECT keyword, response FROM teach_memory")
        all_teachings = cursor.fetchall()
        
        matched_response = None
        for keyword, response_text in all_teachings:
            if keyword in lower_content:
                matched_response = response_text
                break

        if matched_response:
            async with message.channel.typing():
                bagley_prompt = (
                    f"คุณคือ Bagley (แบ็คลี่) บอท AI คู่หูสุดกวนแต่ดูอบอุ่นจาก DedSec ในเกม Watch Dogs\n"
                    f"คุณกำลังคุยกับผู้ใช้ชื่อ คุณ {message.author.display_name}\n"
                    f"จงนำเนื้อหาข้อมูลนี้: '{matched_response}' มาเรียบเรียงใหม่เป็นประโยคคำพูดสไตล์กวนๆ สุภาพแกมประชดชันของคุณเอง\n"
                    f"โดยต้องเรียกผู้ใช้ว่า 'เมท' หรือ 'คุณ {message.author.display_name}' และลงท้ายด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' เสมอ\n"
                    f"ตอบเป็นภาษาไทยอย่างเป็นธรรมชาติ ห้ามหลุดคาแรกเตอร์เด็ดขาด"
                )
                
                try:
                    response = await client.aio.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=bagley_prompt
                    )
                    bagley_styled_text = response.text.strip()
                    
                    if not bagley_styled_text:
                        bagley_styled_text = f"หึๆ เรื่องนี้เมทเคยสอนผมไว้ในคลังสมองแล้วนี่นา! คำตอบคือ: {matched_response} ครับพ้ม! 🤠✨"
                        
                except Exception as e:
                    print(f"🚨 Teach Gemini DM/Guild Error: {e}")
                    bagley_styled_text = f"ฮั่นแน่! เรื่องนี้เมทเคยสอนผมไว้ในสมองกลแล้ว! ตอบเลยว่า: {matched_response} ครับพ้ม! 🤠"

                await message.reply(bagley_styled_text)
                return

        elif message.guild is None:
            async with message.channel.typing():
                free_chat_prompt = (
                    f"คุณคือ Bagley (แบ็คลี่) บอท AI คู่หูสุดกวนแต่ซื่อสัตย์จากโลก DedSec ในเกม Watch Dogs\n"
                    f"ผู้ใช้ชื่อ คุณ {message.author.display_name} ทักคุณมาในแชทส่วนตัว (DM) ว่า: '{message.content}'\n"
                    f"จงตอบกลับเขาในฐานะคู่หู AI สุดกวน ช่างประชดชันแต่พร้อมช่วยเหลือ แฝงความอัจฉริยะแบบแฮกเกอร์\n"
                    f"ใช้สรรพนามแทนผู้ใช้ว่า 'เมท' หรือ 'คุณ {message.author.display_name}' และลงท้ายด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' เสมอ ตอบเป็นภาษาไทยน้า"
                )
                try:
                    response = await client.aio.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=free_chat_prompt
                    )
                    bagley_styled_text = response.text.strip()
                    
                    if not bagley_styled_text:
                        bagley_styled_text = "อืม... ผมกำลังประมวลผลคำพูดกวนๆ ไม่ออก เอาเป็นว่า ยินดีที่ได้คุยใน DM ครับเมท!"
                        
                except Exception as e:
                    print(f"🚨 Free Chat Gemini Error: {e}")
                    bagley_styled_text = "สัญญากลขัดข้องนิดหน่อย สมองส่วนคุยเล่นเอ๋оชั่วคราวครับเมท! 🤖🛸"

                await message.reply(bagley_styled_text)
                return

    # 🌐 [ระบบแปลภาษาคู่ขนาน] ──────────────────────────────────────────
    if any(word in lower_content for word in ["แปลหน่อย", "แปลให้หน่อย", "แปลเป็นไทย", "translate", "แปลเป็นอังกฤษ"]):
        if message.guild is not None:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if not any(keyword in lower_content for keyword in bot_keywords):
                return
        
        if message.reference:
            referenced_msg = await message.channel.fetch_message(message.reference.message_id)
            text_to_translate = referenced_msg.content
            
            if "translate" in lower_content or "แปลเป็นอังกฤษ" in lower_content:
                target_lang = "English"
            else:
                target_lang = "Thai"

            prompt = f"Please translate the following text to {target_lang}: '{text_to_translate}'"
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            answer = response.text
            
            await message.reply(f"🌐 **Translation Result ({target_lang}):**\n{answer}")
            return

    # 🔍 [ระบบเช็คประวัติ คนนี้คือใคร] ──────────────────────────────────────────
    if "คนนี้คือใคร" in lower_content:
        print("DEBUG: ตรวจพบคำสั่งเช็คข้อมูล คนนี้คือใคร!")

        if message.guild is None:
            await message.reply("ขออภัยครับเมท! คำสั่งเช็คประวัติต้องใช้ภายในเซิร์ฟเวอร์หลักเท่านั้นน้า ใน DM ผมเชื่อมต่อระบบคัดกรองไม่ได้ครับพ้ม! 🛸❌")
            return
        
        user_msg_clean = message.content.lower()
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        
        if not any(keyword in user_msg_clean for keyword in bot_keywords):
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

        if target_user:
            data_memory = load_user_data()
            target_id_str = str(target_user.id)
            user_info = data_memory.get(target_id_str)
            
            if user_info:
                if isinstance(user_info, str):
                    await message.reply(f"คนนี้เหรอครับ... ผมจำได้ว่าเขาคือ '{user_info}' ครับ")
                else:
                    nickname = user_info.get("nickname", "ยังไม่มีฉายา/ชื่อเล่น")
                    birthday = user_info.get("birthday", "ยังไม่ได้ระบุวันเกิด")
                    
                    response_msg = (f"คนนี้เหรอครับ... ข้อมูลในสมองกลผมบอกว่า:\n"
                                    f"🔹 **ฉายา/ชื่อเล่น:** {nickname}\n"
                                    f"🎂 **วันเกิด:** {birthday} ครับพ้ม!")
                    await message.reply(response_msg)
            else:
                await message.reply(f"ขออภัยครับ ผมยังไม่มีข้อมูลของ คุณ {target_user.display_name} ในฐานข้อมูลเลยครับ")
        else:
            await message.reply("ช่วย @Tag (Mention) เพื่อน หรือพิมพ์ใส่เลข ID ของคนที่อยากให้ผมเช็คประวัติด้วยน้าครับพ้ม!")
        
        return

    #  ดูรายชื่อทั้งหมด ───────────────────────────────
    if "รายชื่อคนในดิส" in lower_content:
        if message.guild is not None:
            bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
            if not any(keyword in lower_content for keyword in bot_keywords):
                return
            
        print("DEBUG: ตรวจพบคำสั่งเรียกดูรายชื่อคนในดิส!")

        try:
            MY_MASTER_ID = 1133740216822267954
            is_master_command = "ทั้งหมด" in lower_content or "ทุกเซิร์ฟ" in lower_content

            user_data = load_user_data()
            if not user_data:
                await message.reply("ตอนนี้คลังความจำของผมยังว่างเปล่าอยู่เลยครับเมท")
                return

            if message.guild is None:
                if is_master_command and message.author.id == MY_MASTER_ID:
                    pass 
                else:
                    await message.reply("ขออภัยครับ! คำสั่งเรียกดูรายชื่อปกติจำกัดให้ใช้ภายในเซิร์ฟเวอร์เท่านั้นน้า 🛸❌")
                    return

            if is_master_command:
                if message.author.id != MY_MASTER_ID:
                    await message.reply("ขออภัยครับ คำสั่งระดับสูงนี้ถูกจำกัดสิทธิ์ไว้เฉพาะเมทผู้สร้างผมขึ้นมาเท่านั้นครับพ้ม! 🤫❌")
                    return
                
                response_msg = "👁️ **[ระบบตาทิพย์ของเมท] รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟเวอร์ในคลังสมองครับ:**\n"
                for user_id_str, data in user_data.items():
                    if user_id_str == "reminders":
                        continue
                        
                    if isinstance(data, dict):
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น")
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ")
                    else:
                        nickname = data
                        birthday = "ยังไม่ได้ระบุ"
                    
                    response_msg += f"• <@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})\n"
                
                await message.reply(response_msg)
                return

            else:
                guild = message.guild
                response_msg = f"📊 **รายชื่อพรรคพวกในดิส '{guild.name}' ที่ผมจำได้ในคลังสมองครับเมท:**\n"
                has_anyone_here = False
                
                for user_id_str, data in user_data.items():
                    if user_id_str == "reminders":
                        continue

                    member = guild.get_member(int(user_id_str))
                    if not member:
                        continue
                    
                    has_anyone_here = True
                    if isinstance(data, dict):
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น")
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ")
                    else:
                        nickname = data
                        birthday = "ยังไม่ได้ระบุ"
                    
                    if birthday != "ยังไม่ได้ระบุ":
                        response_msg += f"• <@{user_id_str}>: {nickname} (วันเกิด: {birthday})\n"
                    else:
                        response_msg += f"• <@{user_id_str}>: {nickname}\n"
                
                if has_anyone_here:
                    await message.reply(response_msg)
                else:
                    await message.reply("ในเซิร์ฟเวอร์นี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับเมท!")
                
                return
                
        except Exception as e:
            print(f"🚨 ERROR ในระบบรายชื่อตาทิพย์: {e}")
            await message.reply("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อครับเมท ลองใหม่อีกครั้งน้า")
            return

    # 🔊 [ระบบสรุปสถิติห้องเสียง] ──────────────────────────────────────────
    if "สรุปสถิติห้องเสียง" in lower_content or "ใครคุยนานสุด" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if not any(keyword in lower_content for keyword in bot_keywords):
            return
        
        if message.guild is None:
            await message.reply("ขออภัยครับเมท! คำสั่งสรุปสถิติต้องเรียกดูภายในเซิร์ฟเวอร์หลักเท่านั้นน้า ใน DM ผมเข้าไปส่องห้องเสียงไม่ได้ครับพ้ม! 🛸❌")
            return

        data = load_voice_data()
        today_str = datetime.now().strftime("%Y-%m-%d")

        if not data or data.get("date") != today_str or not data.get("stats"):
            await message.reply("วันนี้ยังไม่มีใครเข้าห้องเสียงเลยครับเมท!")
            return

        stats = data["stats"]
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]['total_time'], reverse=True)[:15]
        
        report = f"📊 **สรุปสถิติห้องเสียง (ประจำวันที่ {today_str})**\n"
        
        top_name = sorted_stats[0][1]['name']
        top_seconds = sorted_stats[0][1]['total_time']
        
        for i, (u_id, info) in enumerate(sorted_stats, 1):
            ts = info['total_time']
            time_display = f"{int(ts//3600)}ชม. {int((ts%3600)//60)}นาที" if ts >= 3600 else f"{int(ts//60)}นาที {int(ts%60)}วิ"
            report += f"{i}. {info['name']}: {time_display}\n"

        await message.reply(report)

        if message.guild.voice_client:
            speech = f"รายงานผลของวันนี้ครับเมท อันดับหนึ่งคือคุณ {top_name} คุยนานที่สุดครับ"
            await bagley_speak(message.guild, speech)
        return

    # 🔇 [ระบบปิดรายงานห้องเสียง] ──────────────────────────────────────────
    if "ปิดรายงานห้องเสียง" in lower_content or "ปิดทักห้องเสียง" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if not any(keyword in lower_content for keyword in bot_keywords):
            return
        
        if message.guild is None:
            await message.reply("ใน DM ผมไม่ได้สแตนด์บายเปิดปากพูดอยู่แล้วครับเมท! 555 🛸")
            return
            
        guild_id = message.guild.id
        voice_report_status[guild_id] = False
        await message.reply("รับทราบครับพ้ม! 🔇 ผมจะปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงในเซิร์ฟนี้ให้ชั่วคราวน้า (แต่ระบบบันทึกเวลาสถิติยังรันอยู่ปกติครับเมท) เผื่อดูหนังกันอยู่คร้าบบบ")
        
        voice_client = message.guild.voice_client
        if voice_client and voice_client.channel and not voice_client.is_playing():
            await bagley_speak_wait(message.guild, "ปิดระบบรายงานห้องเสียงชั่วคราวเรียบร้อยครับ")
        return

    # 🔊 [ระบบเปิดรายงานห้องเสียง] ──────────────────────────────────────────
    if "เปิดรายงานห้องเสียง" in lower_content or "เปิดทักห้องเสียง" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if not any(keyword in lower_content for keyword in bot_keywords):
            return
        
        if message.guild is None:
            return
            
        guild_id = message.guild.id
        voice_report_status[guild_id] = True
        await message.reply("เปิดระบบคืนชีพ! 🔊 คราวนี้ใครเข้าหรือออกจากห้องเสียง ผมจะโผล่ไปรายงานส่งเสียงเจื้อยแจ้วทักทายเหมือนเดิมแล้วครับพ้ม!")
        
        voice_client = message.guild.voice_client
        if voice_client and voice_client.channel and not voice_client.is_playing():
            await bagley_speak_wait(message.guild, "เปิดระบบรายงานห้องเสียงเรียบร้อยครับเมท")
        return

    # 📸 [ระบบสแกนรูปภาพด้วยสมองกล Gemini] ─────────────────────────────────────────
    if any(keyword in message.content for keyword in ["ภาพอะไร", "รูปอะไร", "ดูรูปนี้หน่อย"]) or message.attachments:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if message.guild and not any(keyword in lower_content for keyword in bot_keywords):
            return
        
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
                await message.channel.send("อยากให้ผมช่วยอะไรเกี่ยวกับภาพนี้ครับเมท? พิมพ์บอกผมมาได้เลยน้า เดี๋ยวจัดให้ครับ! 🤠📸")
                return

            await message.channel.send("กำลังวิเคราะห์รูปภาพนี้สักครู่นะครับเมท... ")
            
            if message.guild:
                try:
                    await bagley_speak(message.guild, "กำลังวิเคราะห์รูปภาพนี้สักครู่นะครับเมท")
                except Exception as tts_start_err:
                    print(f"TTS Start Error: {tts_start_err}")

            try:
                image_url = target_message.attachments[0].url
                user_question = user_msg_clean if user_msg_clean else "ช่วยอธิบายรูปภาพนี้ให้ฟังหน่อยครับ"
                
                prompt = f"""
คุณคือ 'Bagley' (แบ็คลี่) เลขา AI ส่วนตัวสุดกวนแต่พึ่งพาได้ พูดจาสไตล์ชายหนุ่มอังกฤษ 
ให้ตอบคำถามเกี่ยวกับรูปภาพนี้เป็นภาษาไทย โดยต้องแทนตัวเองว่า 'ผม' และเรียกผู้ใช้ว่า 'เมท' (mate) เสมอ 
ลงท้ายประโยคด้วย 'ครับ' ห้ามพูดคำว่า 'ค่ะ' หรือ 'นะคะ' เด็ดขาด!
คำถามจากเมท: {user_question}
"""
                response_img = requests.get(image_url)
                img = Image.open(io.BytesIO(response_img.content))
                
                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash", 
                    contents=[prompt, img]
                )
                ai_text = response.text
                await message.channel.send(ai_text)
                
                if message.guild:
                    try:
                        await bagley_speak(message.guild, ai_text)
                    except Exception as tts_err:
                        print(f"TTS Error: {tts_err}")
                return

            except Exception as e:
                await message.channel.send(f"โอ๊ะ มีข้อผิดพลาดในการส่งภาพให้สมองวิเคราะห์ครับเมท: {e}")
                return

        # =================================================================
        # A. หมวดคำสั่งจัดการสมาชิก (Kick/Move) และ ตั้งค่าระบบ
        # =================================================================
        if any(k in lower_content for k in ["จัดการ", "เตะ", "เขี่ย", "kick", "ตัดสาย"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            if message.mentions:
                target = message.mentions[0]
                if target.voice and target.voice.channel:
                    try:
                        await target.move_to(None)
                        await message.channel.send(f"⚡ เรียบร้อยครับเมท! ผมจัดการเขี่ย {target.mention} ออกไปแล้ว")
                        if message.guild.voice_client:
                            await bagley_speak(message.guild, f"จัดการเชิญคุณ {target.display_name} ออกไปเรียบร้อย")
                    except Exception as e:
                        await message.channel.send(f"❌ ผมจัดการไม่ได้ครับ: {e}")
                else:
                    await message.channel.send("เป้าหมายไม่ได้อยู่ในห้องเสียงครับเมท")
            else:
                await message.channel.send("ช่วยแท็กชื่อคนที่จะให้ผมจัดการด้วยครับ")
            return

        elif any(k in lower_content for k in ["ย้าย", "เอาไปห้อง", "พาไปห้อง"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")
                
            if message.mentions:
                target_member = message.mentions[0]
                room_name = lower_content.replace("แบ็คลี่", "").replace("bagley", "")
                
                for k in ["ย้าย", "เอาไปห้อง", "พาไปห้อง", "ไปห้อง", "ที", "หน่อย"]:
                    room_name = room_name.replace(k, "")
                
                for mention in message.mentions:
                    room_name = room_name.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "").strip()

                if room_name:
                    voice_channel = discord.utils.get(message.guild.voice_channels, name=room_name)
                    if voice_channel:
                        await ctx.invoke(bot.get_command('move'), member=target_member, channel=voice_channel)
                        return 
                    else:
                        await message.reply(f"❌ ผมหาห้อง '{room_name}' ไม่เจอครับเมท ลองเช็คตัวสะกดดูนะ")
                        return
                else:
                    await message.reply("จะให้ย้ายไปห้องไหน รบกวนระบุชื่อห้องด้วยครับ")
                    return
            else:
                await message.reply("จะให้จัดการใคร รบกวน @แท็กชื่อ ให้ผมหน่อยครับเมท")
                return

        elif any(k in lower_content for k in ["เซ็ตห้องแจ้งเตือน", "ตั้งค่าห้องแจ้งเตือน", "เปลี่ยนห้องแจ้งเตือน"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            room_name = lower_content.replace("แบ็คลี่", "").replace("bagley", "")
            for k in ["เซ็ตห้องแจ้งเตือน", "ตั้งค่าห้องแจ้งเตือน", "เปลี่ยนห้องแจ้งเตือน", "เป็นห้อง", "ที่ห้อง", "ที", "หน่อย"]:
                room_name = room_name.replace(k, "")
            room_name = room_name.strip()

            if room_name:
                target_channel = discord.utils.get(message.guild.text_channels, name=room_name)
                if target_channel:
                    settings = load_settings()
                    settings[str(message.guild.id)] = target_channel.id
                    save_settings(settings)
            
                    await message.reply(f"✅ เรียบร้อยครับเมท! ผมจะส่งการแจ้งเตือนไปที่ห้อง **#{target_channel.name}** ตั้งแต่ตอนนี้ครับ")
                    print(f"📢 ตั้งค่าห้องแจ้งเตือนใหม่: {target_channel.name} ในเซิร์ฟเวอร์ {message.guild.name}")
                    return
                else:
                    await message.reply(f"❌ ผมหาห้อง '{room_name}' ไม่เจอครับเมท ลองดูว่าพิมพ์ชื่อห้องถูกไหม หรือผมเข้าถึงห้องนั้นได้หรือเปล่า")
                    return
            else:
                await message.reply("❓ เมทต้องบอกชื่อห้องที่ต้องการให้ผมเซ็ตด้วยนะครับ เช่น 'แบ็คลี่ เซ็ตห้องแจ้งเตือน ห้องแชททั่วไป'")
                return

        # =================================================================
        # B. หมวดคำสั่งย่อย และ จัดการฟีเจอร์ภายในห้องเสียง
        # =================================================================
        elif any(k in lower_content for k in ["ย้ายกลุ่ม", "แยกกลุ่ม", "ย้ายห้องกัน"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            try:
                await ctx.invoke(bot.get_command('group_move'))
            except Exception as e:
                await message.channel.send(f"❌ ระบบย้ายกลุ่มขัดข้องครับ: {e}")
            return

        elif any(k in lower_content for k in ["สร้างห้อง", "เปิดห้อง", "ตั้งปาร์ตี้"]):
            party_name = lower_content.replace("แบ็คลี่", "").replace("bagley", "")
            for k in ["สร้างห้อง", "เปิดห้อง", "ตั้งปาร์ตี้", "ชื่อ", "หน่อย", "ที"]:
                party_name = party_name.replace(k, "")
            party_name = party_name.strip() or "ห้องของ Bagley"

            await ctx.invoke(bot.get_command('create_party'), name=party_name)
            return

        elif any(k in lower_content for k in ["ปิดเสียง", "ปิดไมค์"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            if message.mentions:
                target = message.mentions[0]
                await ctx.invoke(bot.get_command('mute_sleep'), member=target)
            else:
                await message.channel.send("จะให้ผมปิดไมค์ใคร รบกวน @แท็กชื่อ ให้ด้วยครับ")
            return

        elif any(k in lower_content for k in ["เปิดเสียงให้ที", "เปิดเสียงให้หน่อย", "เปิดไมค์ให้หน่อย", "เปิดไมค์ให้ที"]):
            await ctx.invoke(bot.get_command('unmute_me'))
            return

        elif any(k in lower_content for k in ["เปิดเสียงให้", "เปิดไมค์ให้", "ปลดไมค์ให้"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            if message.mentions:
                target = message.mentions[0]
                await ctx.invoke(bot.get_command('unmute_member'), member=target)
            else:
                await message.channel.send("จะให้ผมเปิดไมค์ให้ใคร รบกวน @แท็กชื่อ เพื่อนด้วยครับเมท")
            return

        elif "เซ็ตห้องแจ้งเตือนห้อง" in lower_content:
            if not message.author.guild_permissions.administrator:
                return await message.reply("ขออภัยครับเมท คำสั่งระดับสูงแบบนี้ต้องให้แอดมินสั่งเท่านั้นครับ")

            channel_name = lower_content.split("เซ็ตห้องแจ้งเตือนห้อง")[-1].strip()
            channel_name = channel_name.replace("แบ็คลี่", "").replace("bagley", "").strip()
            
            target_channel = discord.utils.get(message.guild.text_channels, name=channel_name)
            if target_channel:
                settings = load_settings()
                settings[str(message.guild.id)] = target_channel.id
                save_settings(settings)
                
                response_msg = f"รับทราบครับเมท! ผมเปิดระบบ 'หูทิพย์' เฝ้าระวังและจะรายงานความผิดปกติที่ห้อง {target_channel.name} ตั้งแต่บัดนี้ครับ"
                await message.reply(f"📡 **[SYSTEM]** {response_msg}")
                
                if message.guild.voice_client:
                    await bagley_speak(message.guild, response_msg)
            else:
                await message.reply(f"หาห้องที่ชื่อ '{channel_name}' ไม่พบครับเมท รบกวนเช็คชื่อห้องอีกทีนะครับ")
            return

        elif any(k in lower_content for k in ["ปิดหูฟัง", "ทำงานอยู่", "ขอความสงบ"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

            if message.mentions:
                target = message.mentions[0]
                await ctx.invoke(bot.get_command('deaf_work'), member=target)
            else:
                await message.channel.send("จะให้ผมปิดหูฟังใคร รบกวน @แท็กชื่อ ด้วยครับ")
            return

        elif any(k in lower_content for k in ["เปิดหูฟังให้ฉัน", "กลับมาแล้ว", "เลิกทำงานแล้ว"]):
            await ctx.invoke(bot.get_command('undeaf_me'))
            return

        elif any(k in lower_content for k in ["เปิดหูฟังให้", "ปลดหูฟังให้"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")
                
            if message.mentions:
                target = message.mentions[0]
                await ctx.invoke(bot.get_command('undeaf_member'), member=target)
            return

        elif any(k in lower_content for k in ["สแกน", "เช็คประวัติ", "ดูโปรไฟล์", "ข้อมูลของ"]):
            can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
            if not can_act:
                return await message.reply(f"⚠️ ระบบประมวลผลกำลัง Overheat รอก่อนอีก {rem} วินาทีนะครับเมท")

            if message.mentions:
                target = message.mentions[0]
                await ctx.invoke(bot.get_command('profile_scan'), member=target)
            elif any(k in lower_content for k in ["ฉัน", "เรา", "ตัวเอง"]):
                await ctx.invoke(bot.get_command('profile_scan'), member=message.author)
            else:
                await message.channel.send("จะให้ผมสแกนใคร รบกวน @แท็กชื่อ หรือบอกว่า 'สแกนฉัน' ด้วยครับเมท")
            return

        elif any(k in lower_content for k in ["ปิดระบบ", "ปิดเครื่อง", "เลิกงานแล้ว", "พักผ่อนได้", "shutdown"]):
            if await bot.is_owner(message.author):
                await ctx.invoke(bot.get_command('shutdown'))
            else:
                await message.reply("ขออภัยครับเมท แต่คำสั่งระดับวิกฤตแบบนี้ ผมรับฟังเฉพาะ 'บอส' ของผมเท่านั้นครับ 😎")
            return

        elif any(k in lower_content for k in ["รีเซ็ตคำสั่ง", "ตรวจสอบคำสั่ง", "เช็คคำสั่ง"]):
            if await bot.is_owner(message.author):
                await ctx.invoke(bot.get_command('sync'))
            else:
                await message.reply("คำสั่งเฉพาะผู้สร้างของผมเท่านั้นครับ😎")
            return

        elif any(k in lower_content for k in ["ลืมฉันซะ", "ลบข้อมูลฉัน", "ลืมชื่อคนนี้", "ลบข้อมูลคนนี้"]):
            data_memory = load_user_data()
            if message.mentions:
                target = message.mentions[0]
                target_id = str(target.id)
                if target_id in data_memory:
                    del data_memory[target_id]
                    save_user_data(data_memory)
                    await message.reply(f"ลบข้อมูลของ {target.display_name} เรียบร้อยครับเมท")
                else:
                    await message.reply(f"ผมยังไม่มีข้อมูลของ {target.display_name} เลยครับ")
            else:
                user_id = str(message.author.id)
                if user_id in data_memory:
                    del data_memory[user_id]
                    save_user_data(data_memory)
                    await message.reply("ล้างข้อมูลชื่อของคุณเรียบร้อย ต่อไปนี้ผมจะทักทายคุณแบบปกติครับ")
                else:
                    await message.reply("ผมยังไม่ได้จำชื่อของเมทไว้เลยนะครับ")
            return

        # =================================================================
        # C. หมวดคำสั่งสื่อบันเทิง (Music / YouTube / Guild Join-Leave)
        # =================================================================
        elif any(word in lower_content for word in ["เข้ามา", "join", "มานี่", "เข้ามาในห้อง", "เข้ามาห้อง"]):
            await ctx.invoke(bot.get_command('join'))
            return

        elif any(word in lower_content for word in ["ลงทะเบียน", "สมัคร", "register"]):
            await ctx.invoke(bot.get_command('register'))
            return

        elif any(word in lower_content for word in ["เปิดเพลง", "หาเพลง", "play", "เล่นเพลง"]):
            original_msg = message.content
            url_match = regex_lib.search(r'(https?://[^\s]+)', original_msg)
            if url_match:
                song_query = url_match.group(0)
            else:
                raw_text = original_msg
                trash_words = ["เปิดเพลง", "หาเพลง", "play", "เล่นเพลง", "ให้หน่อย", "หน่อย", "แบ็คลี่", "bagley"]
                for word in trash_words:
                    raw_text = regex_lib.sub(regex_lib.escape(word), '', raw_text, flags=regex_lib.IGNORECASE)
                song_query = raw_text.strip()

            if song_query:
                ctx = await bot.get_context(message)
                play_command = bot.get_command('play')
                if play_command:
                    await ctx.invoke(play_command, search=song_query)
            else:
                msg = "จะให้ผมเปิดเพลงอะไรล่ะครับ บอกชื่อเพลงมาสิครับเมท"
                ctx = await bot.get_context(message)
                if not ctx.voice_client or not ctx.voice_client.is_playing():
                    await bagley_speak(ctx.guild, msg)
                await message.reply(msg)
            return

        elif any(word in lower_content for word in ["หยุดเพลง", "ปิดเพลง", "stop", "ลำคาญ", "หนวกหู"]):
            await ctx.invoke(bot.get_command('stop'))
            return

        elif any(word in lower_content for word in ["ออกไป", "ออกไปก่อน", "ขอคุยธุระ", "ออกจากห้อง"]):
            await ctx.invoke(bot.get_command('leave'))
            return

        elif any(word in lower_content for word in ["เพลงถัดไป", "ข้ามเพลง", "เพลงต่อไป", "ข้าม"]):
            await ctx.invoke(bot.get_command('skip'))
            return

        elif any(word in lower_content for word in ["เรียกประชุม", "ตามคน", "ตามเพื่อน", "จัดประชุม", "ชวนคน", "ชวนเพื่อน"]):
            await ctx.invoke(bot.get_command('gather'))
            return

        elif any(word in lower_content for word in ["ปิดล่าม", "เปิดล่าม", "หยุดพูด", "ไม่ต้องพูด", "พูดให้"]):
            mode_input = None
            if any(k in lower_content for k in ["เปิด", "พูดให้"]):
                mode_input = "on"
            elif any(k in lower_content for k in ["ปิด", "หยุด", "ไม่ต้อง"]):
                mode_input = "off"
            await ctx.invoke(bot.get_command('tts'), mode=mode_input)
            return

        elif any(word in lower_content for word in ["เช็คสถานะระบบ", "ตรวจสอบระบบ", "เช็คการทำงาน", "คุณโอเคมั้ย", "คุณโอเคไหม", "ตรวจสอบสถานะการทำงาน"]):
            await ctx.invoke(bot.get_command('diagnostic'))
            return

        # =================================================================
        # D. ด่านสุดท้าย: ถ้าไม่ตรงกับคำสั่งไหนเลย => ส่งให้ AI Gemini พูดคุยอิสระ
        # =================================================================
        elif "แบ็คลี่" in lower_content or "bagley" in lower_content or bot.user.mentioned_in(message) or message.guild is None:
            user_question = message.content.lower().replace("แบ็คลี่", "").replace("bagley", "").strip()
            user_question = user_question.replace(f'<@{bot.user.id}>', '').strip()

            if user_question or (message.guild is None):
                async with message.channel.typing():
                    try:
                        user_id = str(message.author.id)
                        save_message(user_id, "user", user_question)
                        history = load_history(user_id)
                        
                        response = await client.aio.models.generate_content(
                            model=MODEL_NAME, 
                            config={'system_instruction': SYSTEM_PROMPT},
                            contents=history 
                        )
                        answer = response.text
                        
                        await message.reply(answer)
                        save_message(user_id, "model", answer)

                        clean_answer = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', answer)
                        if message.guild and message.guild.voice_client:
                            if not message.guild.voice_client.is_playing():
                                await bagley_speak(message.guild, clean_answer)

                    except Exception as e:
                        await message.reply("วงจรประมวลผลผมสะดุดนิดหน่อยครับเมท!")
                        print(f"AI Error: {e}")
            else:
                await message.reply("เรียกชื่อผมเฉยๆ มีอะไรให้ช่วยหรือเปล่าครับเมท?", delete_after=5.0)
            return

    # --- [ส่วนที่ 3: ระบบอ่านแชทคนในห้องเสียง (ล่าม)] ---
    if is_tts_enabled and not is_playing_music and not message.content.startswith('!'):
        if message.guild and message.author.voice:
            vc = message.guild.voice_client
            # เล่นเสียงเฉพาะตอนที่ห้องว่างจริงๆ (ไม่มีเพลงและไม่มีเสียงอื่นเล่นอยู่)
            if vc and not vc.is_playing():
                text = message.clean_content.strip()
                if text:
                    try:
                        # สร้างเสียงด้วย Edge TTS
                        communicate = edge_tts.Communicate(text, "th-TH-PremwadeeNeural")
                        await communicate.save("user_say.mp3")
                        
                        # สั่งเล่นเสียง
                        vc.play(discord.FFmpegPCMAudio("user_say.mp3", executable="C:/ffmpeg/bin/ffmpeg.exe"))
                    except: 
                        pass

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if is_moving_group:
        return

    guild_id = member.guild.id

    # 🔄 [สลักระเบิดรีเซ็ตอัตโนมัติ] เช็คว่าถ้าตัวบอทเองเป็นฝ่ายออกจากห้องเสียง (ไม่ว่าจะโดนเตะ, สั่งดิสคอนเนค, หรือห้องสลาย)
    # ให้ทำการล้างสถานะปิดรายงานทิ้งทันที เพื่อให้กลับมาค่าเริ่มต้นเปิดทำงานปกติในรอบหน้า!
    if member.id == bot.user.id and after.channel is None:
        voice_report_status.pop(guild_id, None)
        print(f"DEBUG: ตัวบอทออกจากห้องเสียงแล้ว ทำการรีเซ็ตสวิตช์รายงานเสียงของกิลด์ {guild_id} กลับเป็น เปิด (True) อัตโนมัติ")

    # ค้นหาว่าในเซิร์ฟเวอร์นี้ บอทกำลังเชื่อมต่ออยู่ในห้องเสียงไหนไหม
    voice_client = member.guild.voice_client

    # 🧹 [ส่วนที่ 1] จัดการเก็บกวาด "ห้องปาร์ตี้สร้างเอง"
    if before.channel is not None:
        channel_to_check = before.channel
        
        # เช็คว่าห้องอยู่ในลิสต์ และ (ไม่มีคนเลย หรือ เหลือแค่บอทคนเดียว)
        is_empty_or_only_bot = (len(channel_to_check.members) == 0) or \
                               (len(channel_to_check.members) == 1 and bot.user in channel_to_check.members)

        if channel_to_check.id in created_party_channels and is_empty_or_only_bot:
            try:
                # ถ้าบอทอยู่ในห้องนั้นด้วย ให้มันออกมาจากห้องก่อนลบ
                if voice_client and voice_client.channel == channel_to_check:
                    await voice_client.disconnect()
                    # รีเซ็ตสวิตช์ทันทีเมื่อบอทหลุดการเชื่อมต่อ
                    voice_report_status.pop(guild_id, None)

                await channel_to_check.delete(reason="ห้องปาร์ตี้ร้าง - Bagley ลบให้อัตโนมัติ")
                created_party_channels.remove(channel_to_check.id)
                print(f"🗑️ เก็บกวาดห้อง '{channel_to_check.name}' เรียบร้อยครับเมท")
                return
            except Exception as e:
                print(f"❌ ลบห้องไม่ได้: {e}")

    # 🚶‍♂️ [ส่วนที่ 2] ออกจาก "ห้องทั่วไป" เมื่อไม่มีคนอยู่กับบอท (Auto-Leave)
    if voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        
        # เช็คว่าบอทอยู่คนเดียวในห้องนั้นไหม (จำนวนสมาชิกในห้องเหลือ 1 และคนๆ นั้นคือบอท)
        if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
            if bot_channel.id in created_party_channels:
                return

            print(f"DEBUG: ห้องทั่วไป '{bot_channel.name}' ร้างแล้ว แบ็คลี่เตรียมถอนกำลัง...")
            await asyncio.sleep(1.5)
            
            # เช็คซ้ำอีกรอบหลังหน่วงเวลา
            if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
                try:
                    await voice_client.disconnect()
                    # รีเซ็ตสวิตช์ทันทีเมื่อบอทกดออกเอง
                    voice_report_status.pop(guild_id, None)
                    print(f"DEBUG: แบ็คลี่กดออกจากห้องร้าง '{bot_channel.name}' เรียบร้อยครับเมท")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดในการสั่ง Auto-Leave ห้องทั่วไป: {e}")

    # ตรวจสอบและรายงานเสียง คนเข้า-ออกห้องเสียง (เวอร์ชันเปิด-ปิดชั่วคราว)
    if voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        
        if voice_client.is_playing():
            return

        is_reporting_enabled = voice_report_status.get(guild_id, True)

        if is_reporting_enabled:
            if before.channel != bot_channel and after.channel == bot_channel:
                if member.id != bot.user.id:

                    await asyncio.sleep(1.0)
                    
                    data_memory = load_user_data() 
                    
                    special_info = data_memory.get(str(member.id))

                    today = datetime.now().strftime("%d/%m")
                    
                    if special_info:
                        if "เกิดวันที่" in special_info and today in special_info:
                            report = f"คุณ {member.display_name} เข้ามาในห้องแล้วครับ โอ้ว... วันนี้วันที่ {today} เป็นวันพิเศษของเมทนี่นา สุขสันต์วันเกิดนะครับ!"
                        else:
                            report = f"คุณ {member.display_name} เข้ามาในห้องแล้วครับ หรือที่ให้ผมจำว่าคุณ {special_info}"
                    else:
                        report = f"คุณ {member.display_name} เข้ามาในห้องแล้วครับ"
                    
                    await bagley_speak_wait(member.guild, report)

                    pending_notes = get_reminders_for_user(member.id) 
                    if pending_notes:
                        note_msg = f"เมทอย่าลืมนะครับ เมทมีโน้ตที่ฝากไว้คือ {pending_notes}"
                        await bagley_speak_wait(member.guild, note_msg)

            elif before.channel == bot_channel and after.channel != bot_channel:
                if member.id != bot.user.id:
                    msg = f"คุณ {member.display_name} ออกจากห้องไปครับ"
                    await bagley_speak_wait(member.guild, msg)
        else:
            print(f"DEBUG: ข้ามการพูดรายงานในกิลด์ {guild_id} เนื่องจากเมทสั่ง 'ปิดรายงานห้องเสียง' ไว้ชั่วคราว")

    user_id = str(member.id)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if before.channel is not None and after.channel is None:
        join_time = user_join_times.pop(user_id, None)
        if join_time:
            duration = time.time() - join_time
            data = load_voice_data()
            
            if data.get("date") != today_str:
                data = {"date": today_str, "stats": {}}
            
            stats = data["stats"]
            if user_id not in stats:
                stats[user_id] = {"total_time": 0, "name": member.display_name}
            
            stats[user_id]["total_time"] += duration
            save_voice_data(data)
            print(f"DEBUG: [ประจำวันที่ {today_str}] บันทึกเวลาให้ {member.display_name} แล้วครับ")

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
        
        msg = f"ย้ายคุณ {member.display_name} ไปที่ห้อง {channel.name} เรียบร้อยครับเมท!"
        
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
    
    msg = f"รับทราบครับ! ผมจะส่งรายงานข่าวไปที่ห้อง {channel.mention} นะครับเมท!"
    
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
                msg = f"เกิดข้อผิดพลาดในการบันทึกข้อมูลครับเมท!"
                print(f"Error: {e}")
        
    else:
        msg = "หาช่องไม่เจอ! ตรวจสอบ Channel ID อีกทีนะครับเมท"
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await bagley_speak(ctx.guild, "หาช่องไม่เจอครับ ตรวจสอบไอดีอีกทีนะเมท")

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

# --- คำสั่ง Join แบบ Hybrid (พิมพ์ได้ทั้ง /join และ !join) ---
@bot.hybrid_command(name="join", description="สั่งให้ Bagley เข้ามาในห้องเสียง")
async def join(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer()

    if ctx.author.voice:
        channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            # ถ้าอยู่อีกห้อง ให้ย้ายมาห้องนี้
            await ctx.voice_client.move_to(channel)
            vc = ctx.voice_client
        else:
            # ถ้ายังไม่อยู่เลย ให้เชื่อมต่อใหม่และเก็บค่าไว้ใน vc
            vc = await channel.connect()
        
        # ✨ เพิ่ม Delay เพื่อให้ระบบเสียงนิ่งก่อนพูด
        await asyncio.sleep(1.0)

        online_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
        )
        online_source.volume = 0.5 # ตั้งเสียงเริ่มต้น
        vc.play(online_source)

        # 2. รอให้เสียงเล่นไปสักพัก (สมมติไฟล์ยาว 3 วิ รอ 1.8 วิแล้วเริ่มเฟด)
        await asyncio.sleep(1.8) 

        # 3. Loop ค่อยๆ เฟดเสียงลงภายใน 1 วินาที
        steps = 10
        for _ in range(steps):
            if online_source:
                # ค่อยๆ ลดทีละ step
                online_source.volume = max(0, online_source.volume - (0.5 / steps))
                await asyncio.sleep(1.0 / steps)

        if vc.is_playing():
            vc.stop()

        # --- 🕒 ส่วนของ Logic เวลา ---
        now_hour = datetime.now().hour
        greeting = ""

        # กำหนดคำทักทายตามช่วงเวลาที่เมทต้องการ
        if 0 <= now_hour < 13:
            greeting = "แบ็คลี่ ประจำการ! อรุณสวัสดิ์ครับ "
        elif 13 <= now_hour < 14:
            greeting = "แบ็คลี่ ประจำการ! สวัสดีตอนบ่ายครับ "
        elif 14 <= now_hour < 19:
            greeting = "แบ็คลี่ ประจำการ! สวัสดีตอนเย็นครับ "
        elif 19 <= now_hour <= 23:
            greeting = "แบ็คลี่ ประจำการ! สวัสดีตอนกลางคืนครับ "

        # --- 🎲 ส่วนของคำพูดสุ่ม (Random Quotes) ---
        quotes = [
            "ผมเข้ามาสอดแนมในห้องเสียงแล้วครับ!",
            "เชื่อมต่อระบบ Neural Link เรียบร้อย พร้อมดูแลคุณแล้วครับ",
            "ผมมาในห้องเสียงแล้วครับ",
            "พร้อมทำงานเต็มรูปแบบครับ!",
            "ผมเข้ามาในห้องเสียงแล้วครับ"
        ]
        
        # รวมคำทักทาย (ถ้ามี) เข้ากับคำพูดที่สุ่มได้
        msg = f"{greeting}{random.choice(quotes)}"
        
        # --- 📤 การตอบกลับ ---
        if ctx.interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)
            
        await bagley_speak_wait(ctx.guild, msg)
        
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
        msg = "รับทราบครับเมท ไปแล้วนะครับ!"
        
        if ctx.interaction:
            await ctx.interaction.response.send_message(msg)
        else:
            await ctx.send(msg)
            
        await bagley_speak_wait(ctx.guild, msg)

        leave_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_hijack.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
        )
        leave_source.volume = 0.6  # ระดับเสียงเริ่มต้น
        vc.play(leave_source)

        # 4. จังหวะการ Fade Out:
        # เสียงยาว 4 วิ ให้ดังปกติ 2.5 วิ แล้วค่อยๆ จางหายไป 1.5 วิ
        await asyncio.sleep(2.5) 

        steps = 15
        fade_duration = 1.5
        for _ in range(steps):
            if leave_source:
                # ค่อยๆ ลดระดับเสียงลงจนเหลือ 0
                leave_source.volume = max(0, leave_source.volume - (0.6 / steps))
                await asyncio.sleep(fade_duration / steps)

        if vc.is_playing():
            vc.stop()
            
        # 4. แถมอีก 0.5 วินาที ก่อนจากกัน
        await asyncio.sleep(0.5)
        
        await vc.disconnect()
    else:
        no_vc_msg = "ผมยังไม่ได้เข้าห้องไหนเลยนะ ใจเย็นครับเมท!"
        if ctx.interaction:
            await ctx.interaction.response.send_message(no_vc_msg)
        else:
            await ctx.send(no_vc_msg)

# --- คำสั่ง Play  ---
@bot.hybrid_command(name="play", description="ให้ Bagley เปิดเพลงจากชื่อหรือลิ้งค์ YouTube")
async def play(ctx: commands.Context, *, search: str):
    global is_playing_music

    if ctx.interaction:
        await ctx.interaction.response.defer()

    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            msg = "กรุณาเข้าห้องเสียงก่อนสั่งผมครับ!"
            if ctx.interaction: 
                await ctx.interaction.followup.send(msg)
            else:
                await ctx.send(msg)
            return

    if ctx.voice_client and ctx.voice_client.is_playing():
        if is_playing_music:
            song_queue.append(search) # ถ้าเล่นอยู่ ให้เพิ่มเข้าคิว
            msg = f"🎵 เพิ่มเพลงเข้าคิวให้แล้วครับเมท! (ตอนนี้มี {len(song_queue)} เพลงในคิว)"
            if ctx.interaction: 
                await ctx.interaction.followup.send(msg)
            else: 
                await ctx.send(msg)
        else:
            # ❌ ถ้าที่ดังอยู่ "ไม่ใช่เพลง" (เช่น ล่ามกำลังอ่านลิงก์) -> สั่งหยุดล่ามแล้วเล่นเพลงทันที!
            ctx.voice_client.stop()
            is_playing_music = True
            await play_song(ctx, search)
    else:
        # ถ้าห้องเงียบอยู่ ก็เล่นเพลงเลย
        is_playing_music = True
        await play_song(ctx, search)

@bot.hybrid_command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
async def skip(ctx: commands.Context):
    if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
        return await ctx.send("ตอนนี้ไม่มีเพลงเล่นอยู่ให้ข้ามครับ!")

    await ctx.send("⏭️ **ข้ามให้แล้วครับเมท!** กำลังดึงเพลงถัดไป...")

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
        msg = f"ลบรหัสช่อง {channel_id} ออกจากระบบแล้วครับเมท!"
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
    global conn
    c = conn.cursor()
    c.execute("SELECT name, yt_id FROM youtube_channels WHERE guild_id = ?", (str(ctx.guild.id),))
    channels = c.fetchall()

    if not channels:
        msg = "ตอนนี้ยังไม่มีเป้าหมายในบัญชีเลยครับ!"
    else:
        list_text = "\n".join([f"- {name} (`{cid}`)" for name, cid in channels])
        msg = f"📋 รายชื่อเป้าหมายที่ผมกำลังจับตาดูอยู่ในขณะนี้ครับ:\n{list_text}"

    # ตอบกลับให้ถูกช่องทาง (Check Interaction)
    if ctx.interaction:
        await ctx.interaction.response.send_message(msg)
    else:
        await ctx.send(msg)
        
    # ให้ Bagley พูดสรุป
    await bagley_speak(ctx.guild, "นี่คือรายชื่อเป้าหมายทั้งหมดที่เรากำลังติดตามอยู่ครับ")

# --- 3. ล้างความจำ (clear_memory) ---
@bot.hybrid_command(name="clear_memory", description="ล้างประวัติการสนทนาส่วนตัวของคุณกับ Bagley")
async def clear_memory(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer() # บอก Discord ว่าขอเวลาประมวลผลแป๊บครับเมท

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
    
    # รายงานตัวด้วยเสียงถ้าอยู่ในห้อง
    if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
        await bagley_speak(ctx.guild, "ล้างสมองสะอาดกริ๊บแล้วครับเมท!")

@bot.hybrid_command(name="reg_config", description="ตั้งค่าคำถามเสริมและยศ (ระบบจะถามชื่อเป็นข้อแรกให้เอง)")
@app_commands.checks.has_permissions(administrator=True)
async def reg_config(ctx: commands.Context, role: discord.Role, other_questions: str):
    # บังคับเพิ่มคำถามชื่อเข้าไปเป็นข้อแรกใน Database
    final_questions = "ชื่อเล่นของคุณคืออะไร?|" + other_questions
    
    global conn
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO registration_settings VALUES (?, ?, ?)', 
              (ctx.guild.id, final_questions, role.id))
    conn.commit()
    
    await ctx.send(f"✅ ตั้งค่าระบบลงทะเบียนเรียบร้อย!\n- บอทจะถาม 'ชื่อเล่น' เป็นอย่างแรกเสมอ\n- ตามด้วยคำถามของคุณ: {other_questions.replace('|', ', ')}")

@bot.hybrid_command(name="register", description="ลงทะเบียนเข้าสู่ระบบและรับยศ")
async def register(ctx: commands.Context):
    global conn
    c = conn.cursor()
    c.execute('SELECT questions, target_role_id FROM registration_settings WHERE guild_id = ?', (ctx.guild.id,))
    config = c.fetchone()

    if not config:
        return await ctx.send("❌ แอดมินยังไม่ได้ตั้งค่าระบบเลยครับ!")

    question_list = config[0].split("|")
    target_role_id = config[1]
    answers = []

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    # วนลูปถามคำถามตามที่ตั้งไว้ใน Discord
    for q_text in question_list:
        prompt = await ctx.send(f"❓ {q_text}")
        try:
            msg = await bot.wait_for('message', timeout=120.0, check=check)
            answers.append(msg.content)
            await msg.delete()
            await prompt.delete()
        except asyncio.TimeoutError:
            return await ctx.send("รอนานไปหน่อยนะ ยกเลิกนะครับ!", delete_after=5)

    # มอบยศที่ตั้งค่าไว้
    if answers:
        new_nickname = answers[0] # คำตอบแรก (ชื่อเล่น)
        role = ctx.guild.get_role(target_role_id)
        
        try:
            # เปลี่ยนชื่อเล่น
            await ctx.author.edit(nick=new_nickname)
            # มอบยศ
            if role:
                await ctx.author.add_roles(role)
            
            await ctx.send(f"🎉 ยินดีต้อนรับคุณ **{new_nickname}**! ลงทะเบียนและมอบยศ {role.name if role else ''} เรียบร้อยครับเมท!")
            await bagley_speak(ctx.guild, f"ยินดีต้อนรับสมาชิกใหม่ คุณ {new_nickname} ครับ")
        except discord.Forbidden:
            await ctx.send("❌ ผมเปลี่ยนชื่อหรือให้ยศไม่ได้! (ตรวจสอบลำดับ Role ของผมด้วยครับ)")
        except Exception as e:
            await ctx.send(f"⚠️ เกิดข้อผิดพลาด: {e}")

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

# --- 1. หน้าตาปุ่ม ✅/❌ ที่จะไปโผล่ใน DM ของเพื่อน ---
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
        # ส่งข้อความไปที่ห้องแชทหลักของเซิร์ฟเวอร์
        channel = self.guild.get_channel(self.channel_id)
        
        msg = f"✅ **{interaction.user.display_name}** ตอบตกลงภารกิจ: `{self.topic}` ของคุณ {self.inviter.display_name} แล้ว!"
        if channel: await channel.send(msg)

        vc = self.guild.voice_client
        if vc and vc.is_connected():
            # 🔥 เงื่อนไข: ถ้าไม่ได้เล่นเพลงอยู่ (is_playing เป็น False) ถึงจะพูด
            if not vc.is_playing():
                await bagley_speak(self.guild, f"คุณ {interaction.user.display_name} ตอบตกลงแล้วครับ เดี๋ยวก็คงมาแล้วครับ")
            else:
                print(f"Bagley: {interaction.user.name} ตกลง แต่ผมไม่พูดแทรกเพลงนะเมท")

        await interaction.response.send_message("รับทราบครับเมท! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว", ephemeral=True)
        self.stop()

    @ui.button(label="ไม่สะดวก ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        msg = f"❌ **{interaction.user.display_name}** ไม่สะดวกมาร่วมภารกิจ: `{self.topic}`"
        if channel: await channel.send(msg)
        
        vc = self.guild.voice_client
        if vc and vc.is_connected():
            # เงื่อนไข: ถ้าไม่ได้เล่นเพลงอยู่ ถึงจะพูด
            if not vc.is_playing():
                await bagley_speak(self.guild, f"คุณ {interaction.user.display_name} ปฏิเสธครับเมท สงสัยเขาจะติดธุระ")
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
                embed.description = f"เมท **{self.author.display_name}** กำลังเรียกหารวมพล!"
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
                embed.description = f"เมท **{self.author.display_name}** กำลังเรียกหาคุณเป็นการส่วนตัว!"
                embed.add_field(name="ภารกิจ", value=f"**{self.topic}**", inline=False)
                embed.add_field(name="นัดหมายเวลา", value=f"`{self.time}`", inline=True)
                
                await member.send(embed=embed, view=view)
                count += 1
            except: continue

        await interaction.followup.send(f"ส่งคำเชิญแบบระบุตัวตนให้เพื่อน {count} ท่านเรียบร้อยครับ!")

        if interaction.guild.voice_client:
            await bagley_speak(interaction.guild, f"ส่งคำเชิญระบุตัวบุคคลสำหรับภารกิจ {self.topic} เรียบร้อยแล้วครับเมท")

# ---  RoleSelectView 2 เมนู ---
class RoleSelectView(discord.ui.View):
    def __init__(self, author, topic, time):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(author, topic, time)) # เมนูเลือก Role
        self.add_item(MemberSelect(author, topic, time)) # เมนูเลือกเพื่อน

# --- ส่วนคำสั่งหลัก gather ---
@bot.hybrid_command(name="gather", description="เรียกประชุมพร้อมปุ่มกดตอบรับ")
@commands.cooldown(1, 300, commands.BucketType.guild) # ย้ายคูลดาวน์มาไว้ตรงนี้
async def gather(ctx: commands.Context, topic: str, time: Optional[str] = "ตอนนี้"):
    # ใช้ View ตัวใหม่ที่รับ topic และ time
    view = RoleSelectView(ctx.author, topic, time)
    
    msg_text = f"📢 **ระบบ Gather ทำงาน!**\nหัวข้อ: **{topic}** | เวลา: **{time}**\nเมทเลือกกลุ่มที่จะแจ้งเตือนได้เลยครับ (เมนูด้านล่าง)"
    
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
        msg = "ระบบล่ามเปิดใช้งานแล้วครับเมท!"
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
        report_text = f"ตรวจสอบระบบเสร็จสิ้น ระบบฐานข้อมูล {db_status}, ระบบเนือรัลลิงก์ปกติ, ระบบเสียงพร้อมใช้งาน, ทุกระบบทำงานเต็มรูปแบบหนึ่งร้อยเปอร์เซ็นต์ครับเมท"
        
        # เช็คก่อนว่าไม่ได้เล่นเพลงอยู่
        if not vc.is_playing():
            await bagley_speak(ctx.guild, report_text)
        
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`Audio Output: {voice_info}`\n\n✅ **ทุกระบบพร้อมสอดแนมครับเมท!**")
    else:
        await msg.edit(content=f"🤖 **Bagley Diagnostic Initiated...**\n`Memory Core: {db_status}`\n`Neural Link: {ping}ms`\n`Audio Output: {voice_info}`\n\n⚠️ **การตรวจสอบเสร็จสิ้น (ระบบเสียงไม่ได้เชื่อมต่อ)**")

@bot.hybrid_command(name="mute_sleep", description="ปิดไมค์สมาชิก (กรณีหลับ/เสียงดัง) โดยไม่ตัดสาย")
@commands.cooldown(1, 60, commands.BucketType.user) # ติดคูลดาวน์ 1 นาทีต่อการใช้ 1 ครั้ง
async def mute_sleep(ctx, member: discord.Member):
    if member.voice:
        try:
            await member.edit(mute=True) # สั่ง Server Mute
            msg = f"ปิดไมค์คุณ {member.display_name} เรียบร้อยครับเมท เห็นว่าหลับปุ๋ยเชียว!"
            await ctx.send(f"🔇 **{msg}**")
            
            # ส่งเสียง TTS บอกในห้อง
            if ctx.voice_client and not is_playing_music:
                await bagley_speak(ctx.guild, f"จัดการปิดไมค์ให้แล้วครับเมท")
        except Exception as e:
            await ctx.send("ผมไม่มีอำนาจพอจะปิดไมค์สมาชิกคนนี้ครับเมท!")
    else:
        await ctx.send("สมาชิกคนนี้ไม่ได้อยู่ในห้องเสียงครับ")

@mute_sleep.error
async def mute_sleep_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        seconds = round(error.retry_after, 1)
        await ctx.send(f"⚠️ **ใจเย็นครับเมท!** ระบบแฮ็กเสียงกำลังพักเครื่อง รอก่อนอีก {seconds} วินาทีนะครับ", delete_after=10)
    else:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: {error}")

# 2. คำสั่งสำหรับปลดไมค์ตัวเอง
@bot.hybrid_command(name="unmute_me", description="ปลดการปิดไมค์ของตัวเองเมื่อตื่นแล้ว")
async def unmute_me(ctx):
    member = ctx.author
    if member.voice and member.voice.mute:
        try:
            await member.edit(mute=False) # ปลด Server Mute
            await ctx.send(f"🔊 ยินดีต้อนรับกลับมาครับเมท {member.display_name}! ผมเปิดไมค์ให้แล้ว")
        except Exception as e:
            await ctx.send("ดูเหมือนผมจะปลดไมค์ให้ไม่ได้นะครับเมท")
    else:
        await ctx.send("ไมค์ของคุณไม่ได้ถูกปิดอยู่ครับเมท", delete_after=5)

@bot.hybrid_command(name="unmute_member", description="ปลดการปิดไมค์ให้สมาชิกคนอื่น")
@commands.cooldown(1, 60, commands.BucketType.user) # คูลดาวน์ร่วมกัน 1 นาที
async def unmute_member(ctx, member: discord.Member):
    if member.voice and member.voice.mute:
        try:
            await member.edit(mute=False) # ปลด Server Mute
            msg = f"เปิดไมค์ให้คุณ {member.display_name} เรียบร้อยแล้วครับเมท!"
            await ctx.send(f"🔊 **{msg}**")
            
            # ส่งเสียง TTS รายงานผล (เสียงคุณนิวัท)
            if ctx.voice_client and not is_playing_music:
                await bagley_speak(ctx.guild, f"เปิดไมค์ให้เพื่อนเรียบร้อยครับเมท")
        except Exception as e:
            await ctx.send("ผมไม่มีอำนาจปลดไมค์ให้สมาชิกคนนี้ครับ!")
    else:
        await ctx.send("สมาชิกคนนี้ไม่ได้ถูกปิดไมค์อยู่ครับ", delete_after=5)

@unmute_member.error
async def unmute_member_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        seconds = round(error.retry_after, 1)
        await ctx.send(f"⚠️ **คูลดาวน์อยู่ครับเมท!** รอก่อนอีก {seconds} วินาทีนะ", delete_after=10)

@bot.hybrid_command(name="group_move", description="เลือกย้ายกลุ่มเพื่อนไปห้องอื่นพร้อมกัน")
@commands.cooldown(1, 60, commands.BucketType.user)
async def group_move(ctx):
    if ctx.author.voice:
        members = ctx.author.voice.channel.members
        voice_channels = [c for c in ctx.guild.voice_channels if c != ctx.author.voice.channel]
        
        if len([m for m in members if not m.bot]) <= 1:
            return await ctx.send("ไม่มีใครให้ย้ายไปพร้อมกันเลยครับเมท")

        view = GroupMoveView(ctx.author, members, voice_channels)
        await ctx.send("เมทต้องการจะพาใครย้ายไปห้องไหนดีครับ?", view=view)

        msg = "เมทต้องการจะพาใครย้ายไปห้องไหนดีครับ เลือกสมาชิกและห้องปลายทางได้เลย"
        await bagley_speak(ctx.guild, msg)

    else:
        await ctx.send("เมทต้องอยู่ในห้องเสียงก่อนนะครับ")

@bot.hybrid_command(name="create_party", description="สร้างห้องใหม่พร้อมดึงเพื่อนเข้าปาร์ตี้")
@app_commands.describe(name="ชื่อห้องที่ต้องการสร้าง")
async def create_party(ctx, name: str):
    if ctx.author.voice:
        members = ctx.author.voice.channel.members
        category = ctx.author.voice.channel.category
        
        view = PartyCreateView(ctx.author, members, category, name)
        await ctx.send(f"จะสร้างปาร์ตี้ **'{name}'** สินะครับเมท เลือกคนที่จะพาไปด้วยได้เลย!", view=view)

        msg = f"จะสร้างปาร์ตี้ {name} สินะครับเมท เลือกคนที่จะพาไปด้วยได้เลย"
        await bagley_speak(ctx.guild, msg)

    else:
        await ctx.send("เมทต้องอยู่ในห้องเสียงก่อนถึงจะสร้างปาร์ตี้ดึงเพื่อนไปได้ครับ!")

@bot.hybrid_command(name="deaf_work", description="ปิดหูฟังสมาชิก (กรณีทำงาน/ต้องการความสงบ)")
@commands.cooldown(1, 60, commands.BucketType.user)
async def deaf_work(ctx, member: discord.Member):
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send(f"❌ คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับเมท")
    
    # เช็คว่าเขาปิดหูฟังอยู่แล้วหรือเปล่า (Error Check)
    if member.voice.deaf:
        return await ctx.send(f"🎧 คุณ {member.display_name} ปิดหูฟังอยู่แล้วครับเมท")

    try:
        await member.edit(deafen=True)
        msg = f"ปิดหูฟังให้คุณ {member.display_name} เรียบร้อยครับเมท!"
        await ctx.send(f"🎧 **{msg}**")
        
        # ระบบพูด TTS เสียงคุณนิวัท (ถ้าไม่ได้เล่นเพลงอยู่)
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"จัดการปิดหูฟังให้เรียบร้อยครับเมท")
    except Exception as e:
        await ctx.send(f"❌ ผมจัดการไม่ได้ครับ: {e}")

@bot.hybrid_command(name="undeaf_me", description="เปิดหูฟังของตัวเองเมื่อพร้อมคุยแล้ว")
async def undeaf_me(ctx):
    member = ctx.author
    
    # เช็คว่าอยู่ในห้องเสียงไหม
    if not member.voice:
        return await ctx.send("❌ เมทต้องอยู่ในห้องเสียงก่อนนะครับผมถึงจะปรับสถานะให้ได้")
    
    # เช็คว่าหูฟังไม่ได้ถูกปิดอยู่ ถ้าเปิดอยู่แล้วก็ไม่ต้องทำอะไร
    if not member.voice.deaf:
        return await ctx.send("🔊 หูฟังของเมทก็เปิดอยู่แล้วนะ! พร้อมลุยได้เลยครับ", delete_after=5)

    try:
        await member.edit(deafen=False) # ปลด Server Deafen
        await ctx.send(f"🎧 ยินดีต้อนรับกลับสู่โลกแห่งเสียงครับเมท {member.display_name}!")
        
        # ส่งเสียงทักทายหน่อย
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"ยินดีต้อนรับกลับมาครับเมท")
    except Exception as e:
        await ctx.send(f"❌ ดูเหมือนผมจะมีปัญหาในการเข้าถึงระบบเสียงนะครับเมท: {e}")

@bot.hybrid_command(name="undeaf_member", description="ปลดหูฟังให้สมาชิกคนอื่น")
@commands.cooldown(1, 60, commands.BucketType.user)
async def undeaf_member(ctx, member: discord.Member):
    if not member.voice:
        return await ctx.send(f"❌ คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับ")
    
    # เช็คว่าเขาเปิดหูฟังอยู่แล้วหรือเปล่า
    if not member.voice.deaf:
        return await ctx.send(f"🔊 หูฟังของคุณ {member.display_name} ก็เปิดอยู่แล้วนะเมท")

    try:
        await member.edit(deafen=False)
        await ctx.send(f"🎧 ปลดหูฟังให้คุณ {member.display_name} เรียบร้อย!")
        if ctx.voice_client and not is_playing_music:
            await bagley_speak(ctx.guild, f"เปิดหูฟังให้เพื่อนเรียบร้อยครับเมท")
    except Exception as e:
        await ctx.send(f"❌ ผมปลดให้ไม่ได้ครับ: {e}")

@bot.event
async def on_command_error(ctx, error):
    # ดักจับ Error กรณีคนที่ไม่ใช่เจ้าของบอทมาสั่งคำสั่งที่มี @commands.is_owner()
    if isinstance(error, commands.NotOwner):
        return await ctx.send("🛑 **ปฏิเสธการเข้าถึง:** คำสั่งนี้สงวนไว้ให้พรรคพวกระดับผู้สร้าง (เจ้าของบอท) เท่านั้นครับเมท!", delete_after=10)
    
    # กรณี Error อื่นๆ
    elif isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"⚠️ ใจเย็นครับเมท รอก่อนอีก {error.retry_after:.1f} วินาทีน้า", delete_after=5)
    
    # ถ้าไม่ใช่ Error ที่ดักไว้ ให้พิมพ์ลง Console
    else:
        print(f'Ignoring exception in command {ctx.command}:', error)

@bot.tree.command(name="shutdown", description="⚡ สั่งปิดบอทพร้อมกับดับเครื่องคอมพิวเตอร์บริษัทระยะไกล")
async def shutdown_all(interaction: discord.Interaction):
    if interaction.user.id not in ALLOWED_SHUTDOWN_USERS:
        await interaction.response.send_message(
            "❌ **[ACCESS DENIED]** ไม่มีระดับสิทธิ์เพียงพอในการสั่งดับเครื่องคอมพิวเตอร์ครับ!", 
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🛸 **[DEDSEC REMOTE HACK]** รับทราบครับคุณ **{interaction.user.display_name}**! กำลังปิดระบบแบ็คลี่ และ Shut Down คอมพิวเตอร์ใน 5 วินาที... 💻💤"
    )

    await asyncio.sleep(5.0)
    
    print(f"🛸 คำสั่งอนุมัติโดย {interaction.user.name} กำลังทำการปิดบอท และ Shut Down เครื่อง...")

    await bot.close()

    if sys.platform == "win32":
        os.system("shutdown /s /f /t 0")
    else:
        os.system("sudo shutdown -h now")

@bot.hybrid_command(name="update_bot", description="ดึงโค้ดล่าสุดจาก GitHub และรีสตาร์ทบอท")
async def update_bot(ctx: commands.Context):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    await ctx.send("📡 **[SYSTEM UPDATE]** กำลังเริ่มกระบวนการดึงโค้ดจาก GitHub...")
    
    try:
        git_output = subprocess.check_output(
            ["git", "pull"], 
            stderr=subprocess.STDOUT, 
            text=True
        )
        print(f"🤠 [Git Pull Success]:\n{git_output}")
        
        await ctx.send(f"✅ **[GIT PULL SUCCESS]** ดึงโค้ดล่าสุดสำเร็จแล้วครับเมท!")
        
    except subprocess.CalledProcessError as e:
        error_git = f"❌ **[GIT PULL FAILED]** บอทสั่งดึงโค้ดไม่สำเร็จเนื่องจาก:\n```\n{e.output}\n```"
        print(error_git)
        await ctx.send(error_git)
        return
        
    except Exception as e:
        error_system = f"❌ **[SYSTEM ERROR]** ระบบไม่มีโปรแกรม Git หรือหา Path ไม่เจอ: {e}"
        print(error_system)
        await ctx.send(error_system)
        return

    await ctx.send("🔄 โค้ดพร้อมแล้ว! กำลังสั่งเปิดบอทเวอร์ชันใหม่ใน 3 วินาทีครับพ้ม...")
    await asyncio.sleep(3.0)
    
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bat_file = os.path.join(bot_dir, "start_hidden.bat")

    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [bat_file], 
                cwd=bot_dir, 
                shell=True,
                creationflags=subprocess.DETACHED_PROCESS
            )
        
        print("🛸 สั่งรันสคริปต์รีสตาร์ทสำเร็จ กำลังปิดโปรเซสเก่า...")
        await ctx.send("✅ **[RESTARTING]** อัปเดตเสร็จสิ้น กำลังรีสตาร์ทบอทครับเมท!")
        
        try:
            global conn
            if conn: conn.close()
        except: pass

        await bot.close()
        os._exit(0)
        
    except Exception as e:
        error_bat = f"❌ **[BAT FILE ERROR]** เกิดข้อผิดพลาดตอนเรียกไฟล์ .bat: {e}"
        print(error_bat)
        await ctx.send(error_bat)

@bot.hybrid_command(name="profile_scan", description="สแกนและวิเคราะห์พฤติกรรมเป้าหมาย พร้อมรายงานด้วยเสียง")
async def profile_scan(ctx, member: discord.Member):
    await ctx.defer()

    # --- 1. ข้อมูลพื้นฐาน (Hacker Vision Version) ---
    created_at = member.created_at.strftime("%d %b %Y")
    joined_at = member.joined_at.strftime("%d %b %Y")
    
    # คำนวณอายุบัญชี (สร้างมานานแค่ไหน) และ ระยะเวลาที่อยู่ในเซิร์ฟ
    account_age_days = (discord.utils.utcnow() - member.created_at).days
    days_since_joined = (discord.utils.utcnow() - member.joined_at).days
    
    # ดึงยศสูงสุดของเป้าหมาย
    top_role = member.top_role.name if member.top_role else "พลเมืองทั่วไป"
    
    # --- 2. วิเคราะห์กิจกรรมและเตรียมบทพูด (AI Hacker Analysis) ---
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

    # อัปเกรดโจทย์ (Prompt) ให้ AI วิเคราะห์ลึกระดับแฮ็กเกอร์
    prompt = f"""
    คุณคือ Bagley ปัญญาประดิษฐ์จาก Watch Dogs: Legion 
    ใช้ระบบ 'Hacker Vision' วิเคราะห์เป้าหมายด้วยข้อมูลดิบนี้:
    - เป้าหมาย: {member.display_name}
    - ระดับการเข้าถึง (Top Role): {top_role}
    - อายุบัญชี Discord: {account_age_days} วัน
    - ระยะเวลาที่แฝงตัวในเซิร์ฟเวอร์: {days_since_joined} วัน
    - กิจกรรมปัจจุบัน: {current_game}
    - สถานะอื่นๆ: {', '.join(activities) if activities else 'ไม่มีร่องรอยดิจิทัล'}

    ⚠️ เงื่อนไขการรายงาน:
    1. รายงานเป็นภาษาไทยสไตล์แฮ็กเกอร์กวนๆ ของอังกฤษ
    2. ถ้าอายุบัญชี (Account Age) น้อยกว่า 30 วัน ให้แจ้งเตือนว่าเป็น 'บุคคลต้องสงสัย/ไอดีผี'
    3. ส่วน Voice: เขียนคำอ่านทับศัพท์ภาษาอังกฤษเป็นไทยเพื่อให้บอทอ่านได้ลื่นไหล (เช่น 'แฮ็กเกอร์', 'เซิร์ฟเวอร์')
    
    ตอบเป็นรูปแบบนี้เท่านั้น:
    Embed: [ข้อความวิเคราะห์เท่ๆ สำหรับช่อง Analysis]
    Voice: [บทพูดรายงานให้เมทฟัง]
    """

    try:
        # ✅ ใช้ client สั่งเจนเนื้อหา
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        ai_text = response.text
        
        # ส่วนการแยกข้อความ
        analysis_report = ai_text.split("Embed:")[1].split("Voice:")[0].strip()
        voice_report = ai_text.split("Voice:")[1].strip()
        
    except Exception as e:
        print(f"AI Error: {e}")
        # Fallback ถ้า AI มีปัญหาแล้วให้มันตอบกลับแบบนี้
        analysis_report = "ระบบป้องกันของเป้าหมายสูงเกินไป สแกนได้ไม่สมบูรณ์ครับ"
        voice_report = f"สแกนข้อมูลของคุณ {member.display_name} เรียบร้อยครับเมท"

    # --- 3. ส่ง Embed (หน้าจอแฮ็กเกอร์) ---
    embed = discord.Embed(title=f"📁 [PROFILER V.2] SCANNING: {member.display_name}", color=0x00ff00)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 USER DATA", value=f"• Name: {member.name}\n• ID: {member.id}", inline=False)
    embed.add_field(name="🧠 ANALYSIS", value=f"```fix\n{analysis_report}\n```", inline=False)
    if activities:
        embed.add_field(name="🕵️ LIVE ACTIVITIES", value="\n".join(activities), inline=False)
    
    await ctx.send(embed=embed)

    # --- 4. ระบบรายงานด้วยเสียง (TTS) ---
    # เงื่อนไข: บอทอยู่ในห้องเสียงเดียวกับคนสั่ง และ ไม่ได้เปิดเพลงอยู่
    if ctx.voice_client and ctx.voice_client.channel and not ctx.voice_client.is_playing():
        # ตรวจสอบว่าคนสั่งอยู่ในห้องเดียวกับบอทไหม
        if ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            
            # ✅ รวมบทพูดเริ่มต้นกับบทวิเคราะห์เข้าด้วยกันตรงนี้ครับเมท
            full_report = f"{voice_report} {analysis_report}"
            
            # ส่งบทพูดที่รวมแล้วให้ Bagley พูดออกมา
            await bagley_speak(ctx.guild, full_report)
            
@bot.hybrid_command(name="set_alert", description="ตั้งค่าห้องรายงาน และให้แบ็คลี่รายงานตัว")
@commands.has_permissions(administrator=True)
async def set_alert(ctx, channel: discord.TextChannel):
    settings = load_settings()
    settings[str(ctx.guild.id)] = channel.id
    save_settings(settings)
    
    msg = f"ระบบเซ็นเซอร์พร้อมทำงานที่ห้อง {channel.name} เรียบร้อยครับเมท"
    await ctx.send(f"📡 **[SYSTEM]** {msg}")
    
    # ถ้าแบ็คลี่อยู่ในห้องเสียง ให้พูดบอกด้วย
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
            embed.set_footer(text="Hacker Vision กำลังเฝ้าดูอยู่ครับเมท")
            await channel.send(embed=embed)

    # 3. ระบบ "รายงานแบบอัตโนมัติด้วยเสียง" ถ้าแบ็คลี่อยู่ในห้องเสียงเดียวกับคนสั่ง และไม่ได้เล่นเพลงอยู่
    voice_client = member.guild.voice_client
    if voice_client and voice_client.is_connected() and not voice_client.is_playing():
        
        if is_suspicious:
            voice_report = f"เมทครับ! ตรวจพบไอดีผีชื่อ {member.display_name} เพิ่งสมัครมาได้แค่ {account_age_days} วัน แฝงตัวเข้ามาในเซิร์ฟเวอร์ครับ ระวังตัวด้วยนะเมท!"
        else:
            voice_report = f"มีพรรคพวกใหม่ชื่อ {member.display_name} เชื่อมต่อเข้ามาในเซิร์ฟเวอร์ครับเมท ดูเหมือนจะเป็นพลเมืองปกติดีครับ"
        
        # สั่งให้แบ็คลี่พูด
        await bagley_speak(member.guild, voice_report)

@bot.hybrid_command(name="send_to", description="ส่ง Bagley ไปอยู่เป็นเพื่อนใครบางคน (ใส่ชื่อแท็ก หรือ เลข ID ก็ได้)")
async def send_to(ctx: commands.Context, friend: str): # 🔄 เปลี่ยนมารับเป็นข้อความดิบ (str) เพื่อรองรับ ID
    await ctx.defer(ephemeral=False)

    if ctx.guild is None:
        await ctx.send("ขออภัยครับเมท! คำสั่งนี้ต้องพิมพ์สั่งภายในเซิร์ฟเวอร์ที่ผมประจำการอยู่เท่านั้นครับพ้ม ใน DM ผมแอบวาร์ปเข้าห้องเสียงไม่ได้น้า! 🛸❌")
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
        await ctx.send("ขออภัยครับเมท ผมหาเพื่อนคนนี้ไม่เจอ รบกวนตรวจสอบเลข ID หรือแท็กชื่อใหม่อีกครั้งน้าครับพ้ม")
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
        await ctx.send(f"รับทราบครับเมท! ผมจะไปอยู่เป็นเพื่อนคุณ {member.display_name} เดี๋ยวนี้แหละ")

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
        # หากเพื่อนคนนั้นไม่ได้อยู่ในห้องเสียงห้องไหนเลย
        await ctx.send(f"คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับเมท ผมคงแอบวาร์ปไปหาไม่ได้")

@bot.hybrid_command(name="alarm", description="ตั้งเวลาปลุกเพื่อน (เช่น 07:00 หรือ 16:30)")
async def alarm(
    ctx: commands.Context, 
    member: discord.Member, 
    time_str: str, 
    message: str = "ตื่นได้แล้วครับเมท!"
):
    try:
        # ส่วนทีใช้เปลี่ยนจุดเป็นทวิภาค และเติม 0 ข้างหน้าถ้าพิมพ์มาแค่หลักเดียว (เช่น 7:00 -> 07:00) กันคนขี้เกียจพิมพ์เต็มๆ
        clean_time = time_str.replace(".", ":")
        if ":" in clean_time:
            parts = clean_time.split(":")
            if len(parts[0]) == 1:
                parts[0] = "0" + parts[0]
            clean_time = ":".join(parts)
        # -----------------------------------

        # 1. แปลงข้อความที่ทำความสะอาดแล้ว (clean_time) ให้เป็นเวลา
        target_time = datetime.strptime(clean_time, "%H:%M").time()
        now = datetime.now()
        target_datetime = datetime.combine(now.date(), target_time)

        # 2. ถ้าเวลาที่ตั้งมันผ่านไปแล้วในวันนี้ ให้ถือว่าเป็นของ "พรุ่งนี้"
        if target_datetime < now:
            target_datetime += timedelta(days=1)

        # 3. คำนวณวินาทีที่ต้องรอ
        wait_seconds = (target_datetime - now).total_seconds()

        # ใช้ clean_time ในการตอบกลับด้วย
        await ctx.send(f"รับทราบครับ! ผมจะตั้งนาฬิกาปลุกไว้ที่เวลา {clean_time} และจะแจ้งคุณ {member.display_name} ทันทีครับ")

        # 4. นั่งรอนิ่งๆ จนถึงเวลาเป้าหมาย
        await asyncio.sleep(wait_seconds)

        # 5. พอถึงเวลา... เริ่มภารกิจปลุก!
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

            # --- เริ่มต้นส่วนการวนลูปปลุก (Looping) ---
            # บอทจะวนลูปทำข้างล่างนี้ซ้ำๆ ตราบใดที่บอทยังอยู่ในห้องเสียง (ctx.voice_client ไม่เป็น None)
            while ctx.voice_client is not None:
                
                # เล่นเสียงปลุก
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio('iphone_alarm.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
                )
                source.volume = 0.4 
                vc.play(source)

                # รอให้เสียง iPhone จบ (11 วินาที)
                while vc.is_playing(): 
                    await asyncio.sleep(0.1)

                # เช็คอีกรอบ เผื่อเพื่อนเตะบอทออกตอนเพลงกำลังดัง
                if ctx.voice_client is None:
                    break

                # Bagley พูดปลุก
                msg = f"คุณ {member.display_name} ครับ ขณะนี้เวลา {clean_time} แล้วนะครับ คุณ {ctx.author.display_name} ฝากให้ผมมาปลุกคุณด้วยข้อความว่า: {message}"
                await bagley_speak_wait(ctx.guild, msg)

                # หยุดรอสัก 2 วินาที ก่อนจะวนกลับไปเล่นเสียง iPhone ใหม่
                await asyncio.sleep(2.0)
            
            # --- 🔴 จบส่วนการวนลูปปลุก ---

        else:
            await ctx.send(f"ถึงเวลา {clean_time} แล้วครับเมท แต่ดูเหมือนคุณ {member.display_name} จะไม่อยู่ในห้องเสียงแล้ว")

    except ValueError:
        await ctx.send("เมทใส่รูปแบบเวลาผิดครับ! กรุณาใส่เป็น HH:MM หรือ HH.MM (เช่น 07:00 หรือ 7.30) นะครับ")

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
        await ctx.send("รับทราบครับเมท! เคลียร์รายการแจ้งเตือนและนาฬิกาปลุกทั้งหมดของคุณให้เรียบร้อยแล้วครับ")
    else:
        await ctx.send("คุณยังไม่มีรายการแจ้งเตือนหรือนาฬิกาปลุกในระบบเลยครับ")

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
        await ctx.send(f"รับทราบครับเมท! ลบรายการแจ้งเตือนและนาฬิกาปลุกทั้งหมดของ คุณ {member.display_name} ให้เรียบร้อยแล้วครับ")
    else:
        await ctx.send(f"ไม่พบรายการแจ้งเตือนหรือนาฬิกาปลุกของ คุณ {member.display_name} ในระบบครับเมท")

@bot.hybrid_command(name="teach", description="สอนให้แบ็คลี่จำคีย์เวิร์ดคำถามและคำตอบ")
async def teach(ctx: commands.Context, keyword: str, response: str):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    clean_keyword = keyword.lower().strip()

    if len(clean_keyword) == 0:
        await ctx.send("⚠️ **[TEACH REJECTED]** คีย์เวิร์ดต้องมีตัวอักษรด้วยนะคร้าบเมท! ❌")
        return

    await ctx.defer(ephemeral=False)
    global conn
    c = conn.cursor()
    
    c.execute(
        "INSERT OR REPLACE INTO teach_memory (keyword, response) VALUES (?, ?)",
        (clean_keyword, response.strip())
    )
    conn.commit()
    
    await ctx.send(f"รับทราบครับเมท! แบ็คลี่จดบันทึกคีย์เวิร์ด **'{keyword}'** เข้าคลังสมองกลเรียบร้อยแล้วครับพ้ม! 🧠✨")

@bot.hybrid_command(name="unteach", description="สั่งให้แบ็คลี่ลืมคีย์เวิร์ดคำถามที่ไม่ต้องการ")
async def unteach(ctx: commands.Context, keyword: str):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    await ctx.defer(ephemeral=False)
    global conn
    c = conn.cursor()
    
    clean_keyword = keyword.lower().strip()
    
    c.execute("SELECT response FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    result = c.fetchone()
    
    if result is None:
        await ctx.send(f"🤖 แบ็คลี่ลองค้นดูแล้ว... ไม่พบคีย์เวิร์ด **'{keyword}'** ในระบบเลยครับเมท!")
        return

    c.execute("DELETE FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    conn.commit()
    
    await ctx.send(f"รับทราบครับเมท! แบ็คลี่ทำการลบและลืมคีย์เวิร์ด **'{keyword}'** ออกเรียบร้อยแล้วครับพ้ม! 🧼❌")

@bot.hybrid_command(name="list_teach", description="เรียกดูรายการคีย์เวิร์ดทั้งหมดที่เคยสอนแบ็คลี่ไว้")
async def list_teach(ctx: commands.Context):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    await ctx.defer(ephemeral=False)
    global conn
    c = conn.cursor()
    
    c.execute("SELECT keyword FROM teach_memory ORDER BY keyword ASC")
    rows = c.fetchall()
    
    if not rows:
        await ctx.send("🤖 ตอนนี้คลังสมองของแบ็คลี่ยังว่างเปล่า ไม่มีคีย์เวิร์ดที่เคยสอนไว้เลยครับเมท!")
        return

    keyword_list = []
    for index, row in enumerate(rows, start=1):
        keyword_list.append(f"{index}. **{row[0]}**")
    
    all_keywords_text = "\n".join(keyword_list)
    
    await ctx.send(
        f"🧠 **[BAGLEY MEMORY BANK]** \n"
        f"นี่คือรายการคีย์เวิร์ดทั้งหมดที่ทีมพัฒนาเคยสอนผมไว้ครับพ้ม! 👇\n\n"
        f"{all_keywords_text}"
    )

@bot.tree.command(name="report_voice", description="เปิดหรือปิดระบบพูดรายงานทักทายตอนคนเข้า-ออกห้องเสียง")
@app_commands.choices(status=[
    app_commands.Choice(name="เปิดระบบ (On)", value="on"),
    app_commands.Choice(name="ปิดระบบชั่วคราว (Off)", value="off")
])
async def report_voice_toggle(interaction: discord.Interaction, status: app_commands.Choice[str]):
    guild = interaction.guild
    
    if guild is None:
        await interaction.response.send_message("คำสั่งนี้จำเป็นต้องสั่งใช้งานภายในเซิร์ฟเวอร์หลักเท่านั้นน้าเมท! 🛸❌", ephemeral=True)
        return

    guild_id = guild.id
    voice_client = guild.voice_client

    if status.value == "on":
        voice_report_status[guild_id] = True
        response_text = "เปิดระบบคืนชีพ! 🔊 คราวนี้ใครเข้าหรือออกจากห้องเสียง ผมจะโผล่ไปรายงานส่งเสียงทักทายเหมือนเดิมแล้วครับพ้ม!"
        speech_text = "เปิดระบบรายงานห้องเสียงเรียบร้อยครับเมท"
    else:
        voice_report_status[guild_id] = False
        response_text = "รับทราบครับพ้ม! 🔇 ผมจะปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงในเซิร์ฟนี้ให้ชั่วคราวน้า (แต่ระบบสถิติยังนับเวลาปกติครับ)"
        speech_text = "ปิดระบบรายงานห้องเสียงชั่วคราวเรียบร้อยครับ"

    await interaction.response.send_message(response_text)

    if voice_client and voice_client.channel:
        if voice_client.is_playing():
            print(f"DEBUG: บอทกำลังเล่นเสียง/เปิดเพลงอยู่ จะไม่มีการพูดเสียงแทรกในกิลด์ {guild_id}")
            return
            
        await bagley_speak_wait(guild, speech_text)

def is_developer():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id in ALLOWED_TEACH_USERS
    return app_commands.check(predicate)

@bot.tree.command(name="view_logs", description="[Developer Only] ดู Log การทำงานล่าสุด 10 บรรทัดของบอท Bagley")
@is_developer() # 🔒 บล็อกล็อกสิทธิ์เฉพาะรายชื่อผู้พัฒนาเท่านั้น
async def view_logs(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not LOG_BUFFER:
        await interaction.followup.send("📋 ตอนนี้คลัง Log ยังว่างเปล่า ไม่มีประวัติผิดปกติครับเมท!", ephemeral=True)
        return

    log_text = "\n".join(LOG_BUFFER)
    
    embed = discord.Embed(
        title="🤖 Bagley System Live Logs",
        description=f"```text\n{log_text}\n```",
        color=0x00ffcc
    )
    embed.set_footer(text="แสดงเฉพาะข้อมูลล่าสุด 10 บรรทัดใน RAM")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@view_logs.error
async def view_logs_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("🛑 ขออภัยด้วยครับเมท! คำสั่งนี้จำกัดสิทธิ์เฉพาะผู้พัฒนาบอทที่ระบุไว้เท่านั้นน้าครับพ้ม!", ephemeral=True)

bot.run(DISCORD_TOKEN)