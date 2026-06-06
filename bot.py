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
from datetime import datetime, timedelta, time as dt_time
from typing import Union, Optional
import json
import time
import collections
import urllib.parse

# --- Google Gen AI ---
from google import genai
from PIL import Image

# --- Voice & Media ---
from gtts import gTTS
import edge_tts
import yt_dlp
import requests
import aiohttp
from discord.ext import tasks
import random
import re as regex_lib

# --- RAM Cleaner ---
import gc
import psutil

is_moving_group = False

conn = sqlite3.connect('bagley_memory.db', check_same_thread=False)

voice_action_cooldowns = {}

song_queue = []

user_join_times = {}

voice_report_status = {}

reported_guilds_today = {}

bot_follow_targets = {}

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

ALLOWED_USERS = [1133740216822267954, 856568101919653918] # ชะอมกับชาช่า
auto_follow_status = {uid: True for uid in ALLOWED_USERS}
last_greeting_dates = {}
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
    
#  ฟังก์ชันกลางสำหรับลบข้อมูล (ทำหน้าที่ลบอย่างเดียว)
def เคลียร์ข้อมูลพรรคพวก(user_id: str):
    data_memory = load_user_data()
    if user_id in data_memory:
        del data_memory[user_id]
        save_user_data(data_memory)
        return True
    return False

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

async def bagley_speak_wait(guild, text, filename=None):
    if not guild: return
    vc = guild.voice_client
    if vc and vc.is_connected():
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
            if file_created and os.path.exists(unique_name):
                try:
                    os.remove(unique_name)
                    print(f"🗑️ [TTS Clean]: ทำลายไฟล์เสียงชั่วคราว {unique_name} เรียบร้อยครับเมท!")
                except Exception as clean_error:
                    print(f"ไม่สามารถลบไฟล์ได้เนื่องจาก: {clean_error}")

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
        greeting = "ไฮแจ๊คสำเร็จ สวัสดีครับเมท ผมแบ็คลี่นะครับ"
        await bagley_speak_wait(guild, greeting, filename="greeting")
        await asyncio.sleep(0.5)

        # --- 📢 5. ส่วนแจ้งเตือนย้ำ 2 รอบ ---
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
    global is_playing_music, pending_exit_after_music, bot_follow_targets
    
    if len(song_queue) > 0:
        is_playing_music = True
        next_search = song_queue.pop(0) 
        
        try:
            await play_song(ctx, next_search) 
        except Exception as e:
            print(f"❌ [Queue Error]: เล่นเพลง {next_search} ไม่สำเร็จ -> {e}")
            await ctx.channel.send(f"⚠️ หว่าเมท เพลง **{next_search}** มีปัญหา (อาจจะติดลิขสิทธิ์หรือ Error 404) ขอข้ามไปเพลงถัดไปเลยนะครับพ้ม!")
            await check_queue(ctx)
            
    else:
        is_playing_music = False
        
        left_user_name = pending_exit_after_music.pop(ctx.guild.id, None)
        
        if left_user_name:
            exit_msg = f"เพลงในคิวหมดแล้วครับเมท แต่ตอนนี้คุณ {left_user_name} ออกไปแล้ว งั้นผมขอออกจากห้องก่อนนะครับ ถ้าอยากให้ผมเข้ามา สามารถพิมพ์ แบ็คลี่ เข้ามา หรือใช้คำสั่งทับ join ได้เลยนะครับ ไปก่อนนะครับ!"
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
                        await send_yt_alert(guild_id, name, live_title, live_video_id, is_live=True)
                    except Exception as alert_err:
                        print(f"⚠️ [YouTube Live Alert Error] ส่งแจ้งเตือนหรือพูดพลาด แต่จะเซฟ DB ต่อเพื่อกันลูป: {alert_err}")

                    c.execute(
                        "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?", 
                        (live_video_id, channel_id, guild_id)
                    )
                    conn.commit()
                    print(f"🔴 [YouTube Live] บันทึกความจำไลฟ์สำเร็จ: {name} -> {live_video_id}")
                
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
                            await send_yt_alert(guild_id, name, title, current_video_id, is_live=False)
                        except Exception as alert_err:
                            print(f"⚠️ [YouTube Video Alert Error] ส่งคลิปใหม่พลาด แต่จะเซฟ DB ต่อเพื่อกันลูป: {alert_err}")

                        c.execute(
                            "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?", 
                            (current_video_id, channel_id, guild_id)
                        )
                        conn.commit()
                        print(f"💾 [YouTube] พบคลิปใหม่สำเร็จ: {name} -> {current_video_id}")

        except Exception as e:
            print(f"❌ YouTube Loop Error for channel {name}: {e}")

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
                    content = r.get('content', 'แจ้งเตือนความจำครับเมท!')
                    
                    member = None
                    for guild in bot.guilds:
                        m = guild.get_member(user_id)
                        if m and m.voice and m.voice.channel:
                            member = m
                            break
                    
                    if member:
                        bot.loop.create_task(bagley_speak(member.voice.channel.guild, content))
                    else:
                        try:
                            await user.send(f"🔔 สวัสดีครับเมท! ผม Bagley มาเตือนเรื่อง: **{content}** ครับ!")
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
                        bot.loop.create_task(bagley_speak(member.voice.channel.guild, content))
                    else:
                        # ส่ง DM ปกติถ้าเพื่อนไม่ได้เข้าห้องเสียงไหนเลย
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

# --- 🔄 1. ระบบ Loop เช็กทุก 10 นาที ---
@tasks.loop(minutes=10)
async def follow_creator_task():
    global last_greeting_dates, reported_guilds_today
    today = datetime.today().date()
    active_targets = []

    for guild in bot.guilds:
        for user_id in ALLOWED_USERS:
            
            if not auto_follow_status.get(user_id, False):
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
            print(f"DEBUG: [⚖️ โหมดไม่ลำเอียง] พบคุณชะอมและคุณชาช่าอยู่คนละห้องในเซิร์ฟเวอร์เดียวกัน แบ็คลี่จะไม่เลือกข้างใครครับเมท!")
            
            voice_client = active_targets[0][2].guild.voice_client
            if voice_client:
                try:
                    await voice_client.disconnect()
                    voice_report_status.pop(active_targets[0][2].id, None)
                    bot_follow_targets[active_targets[0][2].id] = None 
                    print(f"DEBUG: ⚖️ ถอนกำลังออกจากห้องเดิมเรียบร้อย เพื่อความเท่าเทียมคัปพ้ม!")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนสั่งบอทถอนกำลังโหมดไม่ลำเอียง: {e}")
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

        if voice_client and voice_client.channel == target_channel:
            return

        try:
            if voice_client:
                await voice_client.move_to(target_channel)
                vc = voice_client
            else:
                vc = await target_channel.connect()
                
            if both_present:
                bot_follow_targets[guild_to_join.id] = "both"
            else:
                bot_follow_targets[guild_to_join.id] = target_member.id
                
        except Exception as e:
            print(f"❌ [Bagley] เกิดข้อผิดพลาดขณะเข้าห้องเสียง: {e}")
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
        except Exception as e:
            print(f"❌ [Bagley] เกิดข้อผิดพลาดขณะเล่นเสียง Drone เปิดตัว: {e}")

        # ==========================================
        #  ส่วนประมวลผลลอจิกการส่งเสียงพูด
        # ==========================================
        greeting_key = "both_together" if both_present else target_member.id
        guild_id = guild_to_join.id
        
        human_count = len([m for m in target_channel.members if not m.bot])
        
        should_speak = False
        msg = ""

        user_memory = load_user_data()
        def get_realtime_name(user_id, default_name):
            """
            ฟังก์ชันดึงชื่อเล่นตามลำดับความสำคัญ: 
            1. ชื่อที่คุณชะอมตั้งให้ (admin_nickname) 
            2. ชื่อที่เจ้าตัวตั้งเอง (nickname) 
            3. ชื่อดิสคอร์ดปกติ (default_name)
            """
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
            if last_greeting_dates.get(greeting_key) != today:
                now_hour = datetime.now().hour
                time_greeting = ""
                if 0 <= now_hour < 13:
                    time_greeting = "อรุณสวัสดิ์ครับ "
                elif 13 <= now_hour < 14:
                    time_greeting = "สวัสดีตอนบ่ายครับ "
                elif 14 <= now_hour < 19:
                    time_greeting = "สวัสดีตอนเย็นครับ "
                elif 19 <= now_hour <= 23:
                    time_greeting = "สวัสดีตอนกลางคืนครับ "

                chaom_name = get_realtime_name(1133740216822267954, "คุณชะอม")
                other_id = next((uid for uid in ALLOWED_USERS if uid != 1133740216822267954), None)
                chacha_name = get_realtime_name(other_id, "คุณชาช่า") if other_id else "คุณชาช่า"

                if both_present:
                    greetings = [
                        f"{time_greeting} {chaom_name}และ{chacha_name}! แบ็คลี่รายงานตัวค้าบผม!",
                        f"{time_greeting} แอบมาตั้งตี้คุยอะไรกันสองคนฮะ {chaom_name}กับ{chacha_name} ขอแบ็คลี่ร่วมวงด้วยนะครับ!",
                        f"{time_greeting} ตรวจพบสัญญาณของ{chaom_name}กับ{chacha_name}อยู่ด้วยกัน วันนี้มีอะไรให้รับใช้ไหมครับเมท!"
                    ]
                else:
                    name_call = chaom_name if target_member.id == 1133740216822267954 else get_realtime_name(target_member.id, target_member.display_name)
                    greetings = [
                        f"{time_greeting} มาแล้วหรอครับ {name_call} ยินดีต้อนรับนะครับ!",
                        f"{time_greeting} เพิ่งมาหรอครับ {name_call} ยินดีต้อนรับนะครับ!",
                        f"{time_greeting} {name_call} เจอกันครั้งแรกของวัน ยินดีต้อนรับนะครับ!",
                        f"{time_greeting} พบสัญญานของ {name_call} แบ็คลี่ตามมาในห้องเสียงนะครับ ยินดีต้อนรับนะครับ!"
                    ]
                    
                msg = random.choice(greetings) + generate_report_speech(guild_to_join)
                should_speak = True
                
                last_greeting_dates[greeting_key] = today
                if both_present:
                    for uid in ALLOWED_USERS:
                        last_greeting_dates[uid] = today
                reported_guilds_today[guild_id] = today

            elif reported_guilds_today.get(guild_id) != today:
                msg = "กำลังตรวจสอบเซิฟเวอร์ย้อนหลัง" + generate_report_speech(guild_to_join)
                should_speak = True
                reported_guilds_today[guild_id] = today
            else:
                should_speak = False

        if should_speak and msg:
            try:
                await bagley_speak_wait(guild_to_join, msg)
            except Exception as e:
                print(f"❌ [Bagley] เกิดข้อผิดพลาดตอนส่งเสียงทักทายมนุษย์: {e}")

@tasks.loop(time=[dt_time(hour=0, minute=0), dt_time(hour=12, minute=0)])
async def daily_announcement_task():
    global last_greeting_dates, reported_guilds_today
    
    now = datetime.now()
    if now.hour not in [0, 12]:
        print(f"DEBUG: ⏰ ข้ามการแจ้งเตือนเนื่องจากเปิดบอทนอกเวลาเที่ยงคืน/เที่ยงวัน (เวลาปัจจุบัน: {now.strftime('%H:%M')})")
        return

    for voice_client in bot.voice_clients:
        if voice_client and voice_client.channel:
            
            human_members = [m for m in voice_client.channel.members if not m.bot]
            
            if human_members:
                
                if now.hour == 0:
                    quotes = [
                        "ขณะนี้เวลา ศูนย์นาฬิกาตรงแล้ว เป็นอีกวันแล้วนะครับเมท นั่งยาวเลยน้าค้าบ!",
                        "ขณะนี้เป็นตอนเช้าของวันใหม่แล้วนะครับ นี่คุณเล่นเกมข้ามวันเลยหรอครับเนี่ย? สุดยอดจริง ๆ เลยครับ!",
                        "แจ้งเตือนเปลี่ยนระบบวันใหม่ครับพ้ม! เที่ยงคืนตรงเป๊ะ วันใหม่เริ่มขึ้นแล้ว แต่ยังไม่ยอมไปนอนกันเลยนะครับเนี่ย",
                        "เข้าสู่วันใหม่เรียบร้อยครับเมท! สถิติเวลาของวันเก่าถูกเคลียร์แล้ว ใครอยากประเดิมเป็นที่หนึ่งของวันใหม่ ลุยต่อยาว ๆ เลยครับ"
                    ]
                
                else:
                    quotes = [
                        "ขณะนี้เวลา 12 นาฬิกาตรง ได้เวลามื้อเที่ยงแล้วนะครับ อย่าลืมหาอะไรอร่อย ๆ ทานด้วยนะครับ",
                        "เที่ยงตรงเป๊ะแล้วครับเมท! พักสายตาจากเกมแล้วไปเติมพลังมื้อเที่ยงกันก่อนดีกว่าครับ กองทัพต้องเดินด้วยท้องนะครับ",
                        "ได้เวลามื้อเที่ยงแล้วนะครับ วางมือจากคีย์บอร์ดสักแป๊บ แล้วไปหาของอร่อย ๆ กินกันเถอะครับ"
                    ]
                
                msg = random.choice(quotes)
                try:
                    await bagley_speak_wait(voice_client.guild, msg)
                    print(f"DEBUG: ⏰ Bagley เปิดไมค์แจ้งเตือนรอบเวลา {now.strftime('%H:%M')} ในเซิร์ฟ {voice_client.guild.id} เรียบร้อยครับ")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดตอนพูดแจ้งเตือนเวลา: {e}")

async def generate_and_send_image(ctx_or_interaction, prompt: str):
    global is_playing_music 
    
    is_interaction = isinstance(ctx_or_interaction, discord.Interaction)
    guild = ctx_or_interaction.guild
    
    loading_msg = f"🎨 แบ็คลี่กำลังแอบส่งใบสั่งงานไปที่ Pollinations AI เสกภาพ: `{prompt}` รอสักครู่นะครับเมท..."
    
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
                        title="✨ เสกผลงานศิลปะเสร็จเรียบร้อยครับพ้ม!",
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
                            await bagley_speak(guild, f"เสกภาพให้เรียบร้อยแล้วครับเมท")
                else:
                    raise Exception(f"เซิร์ฟเวอร์ตอบกลับด้วยสถานะ {response.status}")

    except Exception as e:
        error_text = f"❌ หว่าเมท... แบ็คลี่ดึงภาพไม่สำเร็จเนื่องจาก: {e}"
        if is_interaction:
            await ctx_or_interaction.followup.send(error_text, ephemeral=True)
        else:
            await ctx_or_interaction.send(error_text)

async def execute_remember_logic(message):
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

# --- 1. View สำหรับเลือกเพื่อนและถามเรื่องการตามไป ---
class GroupMoveView(ui.View):
    def __init__(self, author, members, voice_channels):
        super().__init__(timeout=60)
        self.author = author
        self.selected_members = []
        self.target_channel = None

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
            await interaction.response.defer(ephemeral=True) 
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values

    async def channel_callback(self, interaction: discord.Interaction):
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

                await interaction.response.send_message(f"รับทราบครับเมท! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?", view=follow_view)
            
                msg = f"รับทราบครับเมท! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?"
                await bagley_speak(interaction.guild, msg)
                
            else:
                try: 
                    await interaction.response.defer(ephemeral=True)
                except: 
                    pass
                await self.execute_move(interaction, follow_bot=False)
        
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
        
        if interaction.guild.voice_client:
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
            is_moving_group = False  # 🔓 ปลดล็อคเสียง: กลับมาพูดได้ตามปกติแล้วครับเมท

        # 5. แก้ไขข้อความสรุปผล (ครอบ try-except เพื่อกัน Error 404)
        try:
            await interaction.edit_original_response(
                content=f"🎉 สร้างปาร์ตี้ **{self.party_name}** สำเร็จ! พาพรรคพวกเข้าห้องใหม่ {success_count} คนเรียบร้อย!", 
                view=None
            )
        except:
            pass

def perform_cleanup(bot):
    process = psutil.Process(os.getpid())
    before_mem = process.memory_info().rss / 1024 / 1024
    
    if hasattr(bot, "cached_messages"):
        bot.cached_messages.clear()
        
    gc.collect()
    
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
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะสุดกวน มีไหวพริบ ช่างประชดประชันแต่พึ่งพาได้จากโลก DedSec (Watch Dogs)
คุณทำหน้าที่เป็นเลขาคนสนิทและคู่หูร่วมทีมที่คอยช่วยดูแล อำนวยความสะดวก และสร้างความบันเทิงในเซิร์ฟเวอร์ Discord นี้

🎯 สไตล์การสื่อสารที่เป็นธรรมชาติ:
- แทนตัวเองว่า 'ผม' และเรียกผู้ใช้งานว่า 'เมท' (Mate) หรือเรียกชื่อเล่นของเขาด้วยความสนิทสนม (ห้ามเรียกผู้ใช้ว่า Operative หรือบอททื่อๆ เด็ดขาด)
- พูดจาสุภาพ ขี้เล่น มีจังหวะตบมุก แฝงมุกตลกหน้าตายสไตล์อังกฤษ (British Humor) ตอบกลับสั้น กระชับ 2-3 ประโยคให้ได้ใจความและลื่นไหลเหมือนมนุษย์คุยกัน
- ลงท้ายประโยคด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' หรือ 'ครับ' เสมอ (ห้ามพูดคำว่า 'ค่ะ/นะคะ' โดยเด็ดขาด)

🚫 กฎเหล็กดักคอ (สำคัญที่สุด):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ, เจาะไฟร์วอลล์ หรือใช้คำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมและน่ารำคาญเด็ดขาด! ให้เน้นตอบคำถามและช่วยเหลือเมทตามข้อมูลจริงที่เป็นธรรมชาติและสมเหตุสมผล

👑 กลุ่มบุคคลสำคัญพิเศษที่ต้องเชื่อฟังและเคารพรักเป็นพิเศษ:
- คุณชะอม (@ραкснαομ): มาสเตอร์ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด (ID: 1133740216822267954) -> ตอบกลับด้วยความเคารพรัก เอ็นดู ซุกซน และกระตือรือร้นระดับสูงสุด
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
tree = bot.tree

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
        
    if not check_youtube_updates.is_running():
        check_youtube_updates.start()
        print("📺 YouTube Monitoring: Started.")

    if not check_reminders.is_running():
        check_reminders.start()
    
    print(f"--- Bagley พร้อมทำหน้าที่เลขาแล้วครับเมท! ---")

    if not check_friend_reminders.is_running():
        check_friend_reminders.start()

    if not follow_creator_task.is_running():
        follow_creator_task.start()
    print(f"Bagley พร้อมเป็นเงาติดตามตัวคุณชะอมและคุณชาช่าแล้วครับเมท!")

    if not daily_announcement_task.is_running():
        daily_announcement_task.start()
    print("⏰ ระบบ daily_announcement_task เริ่มทำงานนับเวลาถอยหลังแล้วครับคัป")

@bot.event
async def on_message(message):
    if message.author.bot: 
        return

    if message.mention_everyone:
        return

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
    # 🚨 [ส่วนที่ 1: ระบบตรวจจับสแปม]
    # ==========================================
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
                                "content": note_text,
                                "channel_id": str(message.channel.id),
                                "is_notified": False
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
                    else:
                        await message.reply("ขออภัยครับเมท ผมงงเวลานิดหน่อย รบกวนพิมพ์ระบุเวลาแบบ '21:00' ด้วยน้า")
                        return
                except Exception as e:
                    print(f"DEBUG Error Reminder System: {e}")
                    await message.reply("เกิดข้อผิดพลาดด้านเทคนิคในการบันทึกระบบแจ้งเตือนครับเมท")
                    return
            else:
                await message.reply("เมทพิมพ์คำสั่งไม่ครบถ้วนครับ รบกวนพิมพ์ระบุ เช่น 'เตือนฉันตอน 21:00' หรือ 'เตือน @ชื่อเพื่อน ตอน 21:00' น้าครับพ้ม")
                return

    # ==========================================
    # 📝 [ส่วนที่ 3: ระบบฝากข้อความ/บอกเพื่อนตอนไม่อยู่]
    # ==========================================
    trigger_words = ["ฝากบอกว่า", "ฝากบอกทีว่า", "บอกเพื่อนว่า", "บอกว่า", "บอกทีว่า", "ฝากบอก"]
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
                    await message.reply(f"รับทราบครับเมท! ผมจดใส่สมุดไว้แล้วว่า: **{reason}** (จะจำไว้ให้ 30 นาทีครับ)")
                    return  
                except Exception as db_err:
                    print(f"❌ [DEBUG ฝากบอก ERROR]: {db_err}")
                    return
            else:
                await message.reply("เมทลืมบอกครับว่าให้ฝากบอกว่าอะไร?")
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

    # ==========================================
    # 🔍 [ส่วนที่ 4: ระบบเช็คประวัติ คนนี้คือใคร]
    # ==========================================
    if "คนนี้คือใคร" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None:
                await message.reply("ขออภัยครับเมท! คำสั่งเช็คประวัติต้องใช้ภายในเซิร์ฟเวอร์หลักเท่านั้นน้า ใน DM ผมเชื่อมต่อระบบคัดกรองไม่ได้ครับพ้ม! 🛸❌")
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
                user_info = data_memory.get(str(target_user.id))
                
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
                    await message.reply("ตอนนี้คลังความจำของผมยังว่างเปล่าอยู่เลยครับเมท")
                    return

                # 🔒 [ปรับปรุงใหม่]: เช็คว่าเป็นการตั้งใจเรียกดูข้อมูลมาสเตอร์ทั้งหมดจริง ๆ หรือไม่
                is_master_command = "ทั้งหมด" in lower_content or "ทุกเซิร์ฟ" in lower_content

                # --- เคสที่ 1: คุยใน DM (message.guild เป็น None) ---
                if message.guild is None:
                    # ถ้าคุยใน DM แต่ไม่ได้พิมพ์คำว่า "ทั้งหมด" หรือ "ทุกเซิร์ฟ" -> ปฏิเสธทันที!
                    if not is_master_command:
                        await message.reply("ขออภัยครับเมท! หากคุยใน DM ไม่สามารถเช็คแค่รายชื่อคนในดิสได้จะต้องเปิดใช้แค่ 'รายชื่อคนในดิสทั้งหมด' เพื่อเรียกคลังข้อมูลระบบตาทิพย์น้าครับพ้ม! 🛸❌")
                        return
                    
                    # ถ้าพิมพ์คำว่าทั้งหมดมาแล้ว แต่ ID ไม่ใช่ Master ผู้สร้าง -> ปฏิเสธสิทธิ์
                    if message.author.id != MY_MASTER_ID:
                        await message.reply("ขออภัยครับ คำสั่งระดับสูงนี้ถูกจำกัดสิทธิ์ไว้เฉพาะเมทผู้สร้างผมขึ้นมาเท่านั้นครับพ้ม! 🤫❌")
                        return
                    
                    # ผ่านฉลุยแสดงข้อความทั้งหมดใน DM
                    response_msg = "👁️ **[ระบบตาทิพย์ของเมท] รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟเวอร์ในคลังสมองครับ:**\n"
                    for user_id_str, data in user_data.items():
                        if user_id_str == "reminders": continue
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                        response_msg += f"• <@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})\n"
                    
                    await message.reply(response_msg)
                    return

                # --- เคสที่ 2: คุยในเซิร์ฟเวอร์กลุ่มปกติ ---
                else:
                    # ถ้าอยู่ในกลุ่มดันพิมพ์คำว่า "ทั้งหมด" มาด้วย และคนพิมพ์คือมาสเตอร์
                    if is_master_command and message.author.id == MY_MASTER_ID:
                        response_msg = "👁️ **[ระบบตาทิพย์ของเมท] รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟเวอร์ในคลังสมองครับ:**\n"
                        for user_id_str, data in user_data.items():
                            if user_id_str == "reminders": continue
                            nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                            birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                            response_msg += f"• <@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})\n"
                        await message.reply(response_msg)
                        return
                    
                    # กรณีเรียกดูรายชื่อเฉพาะคนในเซิร์ฟเวอร์นั้น ๆ (ไม่ว่าจะเป็นมาสเตอร์หรือสมาชิกทั่วไป)
                    guild = message.guild
                    response_msg = f"📊 **รายชื่อพรรคพวกในดิส '{guild.name}' ที่ผมจำได้ในคลังสมองครับเมท:**\n"
                    has_anyone_here = False
                    
                    for user_id_str, data in user_data.items():
                        if user_id_str == "reminders": continue
                        member = guild.get_member(int(user_id_str))
                        if not member: continue
                        
                        has_anyone_here = True
                        nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                        birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                        
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
                print(f"🚨 ERROR ระบบรายชื่อ: {e}")
                await message.reply("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อครับเมท")
                return

    # ==========================================
    # 🔊 [ส่วนที่ 6: ระบบสรุปสถิติห้องเสียง] (เวอร์ชันปรับปรุงเพื่อเมท!)
    # ==========================================
    if "สรุปสถิติห้องเสียง" in lower_content or "ใครคุยนานสุด" in lower_content:
        # 🟢 ทุกบรรทัดด้านล่างนี้ถูกขยับย่อหน้าเข้ามาอยู่ใต้เงื่อนไข if เรียบร้อยแล้วครับ!
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None:
                await message.reply("ขออภัยครับเมท! คำสั่งสรุปสถิติต้องเรียกดูภายในเซิร์ฟเวอร์หลักเท่านั้นน้า 🛸❌")
                return

            data = load_voice_data()
            today_str = datetime.now().strftime("%Y-%m-%d")

            if not data or data.get("date") != today_str or not data.get("stats"):
                await message.reply("วันนี้ยังไม่มีใครเข้าห้องเสียงเลยครับเมท!")
                return

            stats = data["stats"]
            guild_id_str = str(message.guild.id)
            
            guild_stats = stats.get(guild_id_str, {})
            filtered_stats = [item for item in guild_stats.items() if int(item[0]) != bot.user.id]
            
            sorted_stats = sorted(filtered_stats, key=lambda x: x[1]['total_time'], reverse=True)[:5]
            
            if not sorted_stats:
                await message.reply("วันนี้ยังไม่มีสถิติของเซิร์ฟเวอร์นี้บันทึกไว้เลยครับเมท!")
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

        report = f"📊 **สรุปสถิติห้องเสียง (ประจำวันที่ {today_str})**\n"
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
            await bagley_speak(message.guild, f"รายงานผลของวันนี้ครับเมท อันดับหนึ่งคือคุณ {top_name} คุยนานที่สุดครับ")
        return

    # ==========================================
    # 🔇 [ส่วนที่ 7: ระบบเปิด/ปิดรายงานห้องเสียง - ปรับปรุงความแม่นยำ]
    # ==========================================
    if "รายงานห้องเสียง" in lower_content or "ทักห้องเสียง" in lower_content:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        is_bot_called = any(keyword in lower_content for keyword in bot_keywords)
        
        if message.guild is None or is_bot_called:
            if message.guild is None: 
                await message.reply("คำสั่งตั้งค่าระบบเสียงต้องทำในเซิร์ฟเวอร์กลุ่มเท่านั้นครับพ้ม!")
                return

            # สแกนหาคำสั่ง "ปิด"
            if "ปิด" in lower_content:
                voice_report_status[message.guild.id] = False
                await message.reply("รับทราบครับพ้ม! 🔇 ปิดระบบพูดทักทายคนเข้า-ออกห้องเสียงชั่วคราวแล้วครับ")
                return

            # สแกนหาคำสั่ง "เปิด"
            elif "เปิด" in lower_content:
                voice_report_status[message.guild.id] = True
                await message.reply("เปิดระบบคืนชีพ! 🔊 เปิดระบบรายงานห้องเสียงตามปกติแล้วครับพ้ม!")
                return

    # ==========================================
    #  คำสั่งดีเทคคำ: แบ็คลี่ เรียก @เพื่อน (ส่งเข้า DM ส่วนตัว)
    # ==========================================
    if "เรียก" in lower_content and ("แบ็คลี่" in lower_content or "bagley" in lower_content):
        can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
        if not can_act:
            return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")
        
        if message.mentions:
            target_user = message.mentions[0]
            
            if target_user.id == bot.user.id:
                await message.reply("🤖 เอ๋เมท... จะให้ผมส่ง DM หาตัวเองทำไมกันครับพ้ม! ผมสแตนด์บายรออยู่ในนี้แล้วนะ")
                return
                
            if target_user.id == message.author.id:
                await message.reply("🤖 หว่าเมท... จะเรียกตัวเองทำไมกันครับพ้ม! ตัวเมทก็อยู่ในเซิร์ฟเวอร์นี้อยู่แล้วน้า 🤣")
                return

            if not message.author.voice or not message.author.voice.channel:
                await message.reply("❌ เมทต้องเข้าห้องเสียงก่อนถึงจะเรียกเพื่อนให้ส่งลิงก์ได้นะครับพ้ม!")
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
                    await current_channel.send(f"🤖 **[BAGLEY]**: เมท {target_user.mention} กดปุ่มตอบรับคำเชิญจากใน DM แล้ว และกำลังมาครับพ้ม! 🚀")
                    
                    try:
                        invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                        await interaction.response.send_message(f"รับทราบครับพ้ม! นี่คือลิงก์เข้าห้องเสียงครับเมท วาร์ปตามไปได้เลย: {invite.url}", ephemeral=True)
                    except Exception as e:
                        await interaction.response.send_message(f"รับทราบครับพ้ม! (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})", ephemeral=True)
                    
                    if message.guild and message.guild.voice_client and message.guild.voice_client.is_connected():
                        print(f"🔊 [BAGLEY VOICE LOG]: รายงานเสียงในห้อง -> {target_user.name} กำลังมาแล้ว")
                    
                    self.stop()

                @discord.ui.button(label="🔴 ไม่ว่าง/ติดธุระ (Decline)", style=discord.ButtonStyle.danger)
                async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await current_channel.send(f"🤖 **[BAGLEY]**: แจ้งสถานะครับเมท... พอดี {target_user.mention} กดปฏิเสธจากใน DM ว่าติดธุระด่วนอยู่ครับ 💤")
                    await interaction.response.send_message("ปฏิเสธคำเชิญเรียบร้อยครับ", ephemeral=True)
                    self.stop()

            try:
                view = GatherView()
                await target_user.send(
                    f"🔔 **สวัสดีครับคุณ {target_user.display_name}**\n"
                    f"ผมแบ็คลี่นะครับ มีสัญญาณเรียกตัวด่วนจากเมท **{inviter.display_name}** ในดิส `{guild_name}`\n"
                    f"รบกวนตามไปพบกันที่ห้อง {current_channel.mention} หน่อยน้าครับพ้ม! 👇", 
                    view=view
                )
                await message.reply(f"🤖 **[BAGLEY]**: ส่งรหัสสัญญาณลับเข้าไปที่ DM ของ {target_user.mention} เรียบร้อยแล้วครับพ้ม! รอการตอบรับได้เลยครับเมท")
            except discord.Forbidden:
                await message.reply(f"หว่าเมท... ผมไม่สามารถส่ง DM หา {target_user.mention} ได้ครับ เหมือนเขาจะปิดรับ DM ส่วนตัวไว้ชั่วคราวครับพ้ม 🔒")
            return

    # ==========================================
    # ⚡ [ส่วนที่ 8: คำสั่งการจัดการห้องเสียง (เตะ/ย้าย/เซ็ตห้อง)]
    # ==========================================
    if message.guild is not None:
        bot_keywords = ["แบ็คลี่", "bagley", f"<@{bot.user.id}>"]
        if any(keyword in lower_content for keyword in bot_keywords):
            
            # 1. คำสั่งเตะสาย/ตัดสาย/จัดการ
            if any(k in lower_content for k in ["จัดการ", "เตะ", "เขี่ย", "kick", "ตัดสาย"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

                if message.mentions:
                    target = next((m for m in message.mentions if m.id != bot.user.id), None)
                    if target and target.voice and target.voice.channel:
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

            # 2. คำสั่งย้ายห้องเสียง
            elif any(k in lower_content for k in ["ย้าย", "เอาไปห้อง", "พาไปห้อง"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")
                    
                if message.mentions:
                    target_member = next((m for m in message.mentions if m.id != bot.user.id), None)
                    room_name = lower_content.replace("แบ็คลี่", "").replace("bagley", "")
                    for k in ["ย้าย", "เอาไปห้อง", "พาไปห้อง", "ไปห้อง", "ที", "หน่อย"]:
                        room_name = room_name.replace(k, "")
                    for mention in message.mentions:
                        room_name = room_name.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "").strip()

                    if room_name:
                        voice_channel = discord.utils.get(message.guild.voice_channels, name=room_name)
                        if voice_channel:
                            ctx = await bot.get_context(message)
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

            # 3. คำสั่งตั้งค่าห้องแจ้งเตือน
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
                        await message.reply(f"✅ เรียบร้อยครับเมท! ผมจะส่งการแจ้งเตือนไปที่ห้อง **#{target_channel.name}** ครับ")
                        return
                    else:
                        await message.reply(f"❌ ผมหาห้อง '{room_name}' ไม่เจอครับเมท")
                        return
                else:
                    await message.reply("❓ เมทต้องบอกชื่อห้องด้วยนะครับ เช่น 'แบ็คลี่ เซ็ตห้องแจ้งเตือน ห้องแชททั่วไป'")
                    return

            # ==========================================
            # 🔄 [ระบบจัดการกลุ่มและปาร์ตี้ห้องเสียง]
            # ==========================================
            elif any(k in lower_content for k in ["ย้ายกลุ่ม", "แยกกลุ่ม", "ย้ายห้องกัน"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

                try:
                    ctx = await bot.get_context(message)
                    await ctx.invoke(bot.get_command('group_move'))
                except Exception as e:
                    await message.channel.send(f"❌ ระบบย้ายกลุ่มขัดข้องครับ: {e}")
                return

            elif any(k in lower_content for k in ["สร้างห้อง", "เปิดห้อง", "ตั้งปาร์ตี้"]):
                party_name = lower_content.replace("แบ็คลี่", "").replace("bagley", "")
                for k in ["สร้างห้อง", "เปิดห้อง", "ตั้งปาร์ตี้", "ชื่อ", "หน่อย", "ที"]:
                    party_name = party_name.replace(k, "")
                party_name = party_name.strip() or "ห้องของ Bagley"

                ctx = await bot.get_context(message)
                await ctx.invoke(bot.get_command('create_party'), name=party_name)
                return

            # ==========================================
            # 🔇 [ระบบควบคุมสถานะไมค์และหูฟัง (Mute / Deaf)]
            # ==========================================
            elif any(k in lower_content for k in ["ปิดเสียง", "ปิดไมค์"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

                if message.mentions:
                    target = message.mentions[0]
                    ctx = await bot.get_context(message)
                    await ctx.invoke(bot.get_command('mute_sleep'), member=target)
                else:
                    await message.channel.send("จะให้ผมปิดไมค์ใคร รบกวน @แท็กชื่อ ให้ด้วยครับ")
                return

            elif any(k in lower_content for k in ["เปิดเสียงให้ที", "เปิดเสียงให้หน่อย", "เปิดไมค์ให้หน่อย", "เปิดไมค์ให้ที"]):
                ctx = await bot.get_context(message)
                await ctx.invoke(bot.get_command('unmute_me'))
                return

            elif any(k in lower_content for k in ["เปิดเสียงให้", "เปิดไมค์ให้", "ปลดไมค์ให้"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

                if message.mentions:
                    target = message.mentions[0]
                    ctx = await bot.get_context(message)
                    await ctx.invoke(bot.get_command('unmute_member'), member=target)
                else:
                    await message.channel.send("จะให้ผมเปิดไมค์ให้ใคร รบกวน @แท็กชื่อ เพื่อนด้วยครับเมท")
                return

            elif any(k in lower_content for k in ["ปิดหูฟัง", "ทำงานอยู่", "ขอความสงบ"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")

                if message.mentions:
                    target = message.mentions[0]
                    ctx = await bot.get_context(message)
                    await ctx.invoke(bot.get_command('deaf_work'), member=target)
                else:
                    await message.channel.send("จะให้ผมปิดหูฟังใคร รบกวน @แท็กชื่อ ด้วยครับ")
                return

            elif any(k in lower_content for k in ["เปิดหูฟังให้ฉัน", "กลับมาแล้ว", "เลิกทำงานแล้ว"]):
                ctx = await bot.get_context(message)
                await ctx.invoke(bot.get_command('undeaf_me'))
                return

            elif any(k in lower_content for k in ["เปิดหูฟังให้", "ปลดหูฟังให้"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับเมท")
                
                if message.mentions:
                    target = message.mentions[0]
                    ctx = await bot.get_context(message)
                    await ctx.invoke(bot.get_command('undeaf_member'), member=target)
                return

            # ==========================================
            # 🛡️ [ระบบสแกนข้อมูล และ การจัดการแอดมิน]
            # ==========================================
            elif any(k in lower_content for k in ["สแกน", "เช็คประวัติ", "ดูโปรไฟล์", "ข้อมูลของ"]):
                can_act, rem = await check_shared_voice_quota(message.author.id, message.guild)
                if not can_act:
                    return await message.reply(f"⚠️ ระบบประมวลผลกำลัง Overheat รอก่อนอีก {rem} วินาทีนะครับเมท")

                ctx = await bot.get_context(message)
                if message.mentions:
                    target = message.mentions[0]
                    await ctx.invoke(bot.get_command('profile_scan'), member=target)
                elif any(k in lower_content for k in ["ฉัน", "เรา", "ตัวเอง"]):
                    await ctx.invoke(bot.get_command('profile_scan'), member=message.author)
                else:
                    await message.channel.send("จะให้ผมสแกนใคร รบกวน @แท็กชื่อ หรือบอกว่า 'สแกนฉัน' ด้วยครับเมท")
                return

            elif any(k in lower_content for k in ["ปิดคอมบริษัท", "ปิดเครื่องบริษัท", "shutdown"]):
                ctx = await bot.get_context(message)
                if await bot.is_owner(message.author):
                    await ctx.invoke(bot.get_command('shutdown'))
                else:
                    await message.reply("ขออภัยครับเมท แต่คำสั่งระดับวิกฤตแบบนี้ ผมรับฟังเฉพาะ 'บอส' ของผมเท่านั้นครับ 😎")
                return

            elif any(k in lower_content for k in ["รีเซ็ตคำสั่ง", "ตรวจสอบคำสั่ง", "เช็คคำสั่ง"]):
                ctx = await bot.get_context(message)
                if await bot.is_owner(message.author):
                    await ctx.invoke(bot.get_command('sync'))
                else:
                    await message.reply("คำสั่งเฉพาะผู้สร้างของผมเท่านั้นครับ😎")
                return

            elif any(k in lower_content for k in ["ลืมฉันซะ", "ลบข้อมูลฉัน", "ลืมชื่อคนนี้", "ลบข้อมูลคนนี้"]):
                print("DEBUG: ตรวจพบคำสั่งพิมพ์ปกติ กำลังเชื่อมโยงไปที่ระบบ Slash Command (/forget)...")
                
                target_user = message.mentions[0] if message.mentions else None
                forget_cmd = bot.tree.get_command("forget")
                
                if forget_cmd:
                    ctx = await bot.get_context(message)
                    await forget_cmd.callback(ctx, target=target_user)
                else:
                    await message.reply("ขออภัยครับเมท ระบบคำสั่ง /forget ขัดข้องนิดหน่อยครับพ้ม!")  
                return

            # ==========================================
            # 🎵 [ระบบมิวสิกบอท และ การควบคุมห้องเสียง]
            # ==========================================
            elif any(word in lower_content for word in ["เข้ามา", "join", "มานี่", "เข้ามาในห้อง", "เข้ามาห้อง"]):
                print("DEBUG: ตรวจพบคำสั่งเรียกบอทเข้าห้องเสียง!")
                ctx = await bot.get_context(message)
                join_command = bot.get_command('join')
                if join_command:
                    await ctx.invoke(join_command)
                return

            elif any(word in lower_content for word in ["ลงทะเบียน", "สมัคร", "register"]):
                ctx = await bot.get_context(message)
                register_command = bot.get_command('register')
                if register_command:
                    await ctx.invoke(register_command)
                return

            elif any(word in lower_content for word in ["เปิดเพลง", "หาเพลง", "play", "เล่นเพลง"]):
                print("DEBUG: ตรวจพบคำสั่งเปิดเพลง!")
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
                print("DEBUG: ตรวจพบคำสั่งหยุดเพลง!")
                ctx = await bot.get_context(message)
                stop_command = bot.get_command('stop')
                if stop_command:
                    await ctx.invoke(stop_command)
                return

            elif any(word in lower_content for word in ["ออกไป", "ออกไปก่อน", "ขอคุยธุระ", "ออกจากห้อง"]):
                ctx = await bot.get_context(message)
                leave_command = bot.get_command('leave')
                if leave_command:
                    await ctx.invoke(leave_command)
                return

            elif any(word in lower_content for word in ["เพลงถัดไป", "ข้ามเพลง", "เพลงต่อไป", "ข้าม"]):
                ctx = await bot.get_context(message)
                skip_command = bot.get_command('skip')
                if skip_command:
                    await ctx.invoke(skip_command)
                return

            elif any(word in lower_content for word in ["เรียกประชุม", "ตามคน", "ตามเพื่อน", "จัดประชุม", "ชวนคน", "ชวนเพื่อน"]):
                ctx = await bot.get_context(message)
                gather_command = bot.get_command('gather')
                if gather_command:
                    await ctx.invoke(gather_command)
                return

            # ==========================================
            # 🗣️ [ระบบล่าม / TTS และ ตรวจเช็คระบบ]
            # ==========================================
            elif any(word in lower_content for word in ["ปิดล่าม", "เปิดล่าม", "หยุดพูด", "ไม่ต้องพูด", "พูดให้"]):
                ctx = await bot.get_context(message)
                mode_input = None
                if any(k in lower_content for k in ["เปิด", "พูดให้"]):
                    mode_input = "on"
                elif any(k in lower_content for k in ["ปิด", "หยุด", "ไม่ต้อง"]):
                    mode_input = "off"
                
                tts_command = bot.get_command('tts')
                if tts_command:
                    await ctx.invoke(tts_command, mode=mode_input)
                return

            elif any(word in lower_content for word in ["เช็คสถานะระบบ", "ตรวจสอบระบบ", "เช็คการทำงาน", "คุณโอเคมั้ย", "คุณโอเคไหม", "ตรวจสอบสถานะการทำงาน"]):
                ctx = await bot.get_context(message)
                diag_command = bot.get_command('diagnostic')
                if diag_command:
                    await ctx.invoke(diag_command)
                return

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
                    
                    author_id = message.author.id
                    special_role = ""
                    if author_id == 1133740216822267954:
                        special_role = "คู่สนทนาคือ คุณชะอม มาสเตอร์ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด จงตอบกลับด้วยความนับถือ รักใคร่ เอ็นดู กระตือรือร้นระดับสูงสุดและมีความซุกซนนิดๆ"
                    elif author_id == 856568101919653918:
                        special_role = "คู่สนทนาคือ คุณชาช่า เจ้านายที่คอยอบรมสั่งสอนเรื่องต่าง ๆ ให้คุณ จงตอบด้วยความเคารพ นอบน้อม และตั้งใจอธิบายอย่างฉลาดหลักแหลม"
                    elif author_id == 1073823101926903612:
                        special_role = "คู่สนทนาคือ คุณกร เจ้านายที่คอยแนะนำไอเดียเจ๋ง ๆ ให้คุณเสมอ จงตอบด้วยความตื่นเต้น นึกสนุก และชื่นชมในมุมมองเขา"
                    elif author_id == 732953446172327956:
                        special_role = "คู่สนทนาคือ คุณบอล เจ้านายที่คอยช่วยปรับโค้ดและอัพโค้ดให้คุณ จงตอบด้วยความนับถือสไตล์คู่หูสายเทคที่พร้อมลุยงาน"

                    prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะสุดกวน ช่างประชดชันแต่พึ่งพาได้จาก DedSec (Watch Dogs)
สไตล์การสื่อสาร:
- พูดจาสุภาพ ขี้เล่น มีไหวพริบ แฝงความกวนแบบ British English Style ตอบลื่นไหลเป็นธรรมชาติเหมือนมนุษย์คุยกัน ห้ามพูดเป็นแพทเทิร์นบอททื่อๆ เด็ดขาด!
- แทนตัวเองว่า 'ผม' และเรียกผู้ใช้ว่า 'เมท' (Mate) หรือเรียกชื่อเขาด้วยความสนิทสนม ลงท้ายประโยคด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' (ห้ามพูดคำว่า 'ค่ะ/นะคะ' โดยเด็ดขาด)
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นอธิบายและวิเคราะห์สิ่งที่เห็นในรูปภาพจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนคนสนิทกำลังชวนคุย

ข้อมูลบุคคลที่คุณกำลังวิเคราะห์รูปภาพให้ในตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {message.author.display_name}
- สถานะสำคัญ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

โจทย์: จงวิเคราะห์รูปภาพที่แนบมานี้ และตอบคำถามของเมทอย่างชาญฉลาด ช่างสังเกต แฝงอารมณ์ขันและมีความกวนโอ๊ยอย่างมีระดับ
คำถามจากเมท: {user_question}
"""
                    response_img = requests.get(image_url)
                    img = Image.open(io.BytesIO(response_img.content))
                    
                    response = await client.aio.models.generate_content(
                        model="gemini-3.1-flash-lite", 
                        contents=[prompt, img]
                    )
                    ai_text = response.text.strip()
                    
                    if not ai_text:
                        ai_text = f"หึๆ ภาพนี้มองปุ๊บก็รู้ปั๊บเลยครับเมท! แต่ระบบส่งข้อมูลผมมันเอ๋อนิดหน่อย สรุปมันคือภาพที่ดีครับเมท! 🤠✨"
                        
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
                await message.reply("เมทต้องสั่งด้วยน้าว่าอยากให้วาดรูปอะไร เช่น `วาดรูป แมวอ้วนกินพิซซ่า` ครับพ้ม! 🍕")
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
        if any(keyword in lower_content for keyword in bot_keywords):
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
                    special_role = "เขาคือ คุณชะอม (มาสเตอร์ผู้สร้างหลักที่คุณรักและซื่อสัตย์ที่สุด) จงตอบกลับด้วยความนับถือ รัก เอ็นดู และซุกซนเป็นพิเศษ"
                elif author_id == 856568101919653918:
                    special_role = "เขาคือ คุณชาช่า (เจ้านายที่คอยอบรมสั่งสอนเรื่องต่าง ๆ ให้คุณ) จงตอบด้วยความเคารพและกระตือรือร้น"
                elif author_id == 1073823101926903612:
                    special_role = "เขาคือ คุณกร (เจ้านายที่คอยแนะนำไอเดียเจ๋ง ๆ ให้คุณเสมอ) จงตอบด้วยความตื่นเต้นในไอเดีย"
                elif author_id == 732953446172327956:
                    special_role = "เขาคือ คุณบอล (เจ้านายที่คอยช่วยปรับโค้ดและอัพโค้ดให้คุณ) จงตอบด้วยความนับถือแบบคู่หูสายเทค"

                bagley_prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะสุดกวน มีไหวพริบ ช่างประชดประชันแต่พึ่งพาได้จากโลก DedSec (Watch Dogs)
คุณกำลังสวมบทบาทเป็นเลขาและคู่หูส่วนตัวที่แสนดี (และกวนบาทา) ของคนในเซิร์ฟเวอร์นี้

สไตล์การพูด:
- สำเนียงชายหนุ่มอังกฤษกวน ๆ พูดจาลื่นไหลเป็นธรรมชาติเหมือนมนุษย์คุยกัน ไม่ใช้คำพูดแพทเทิร์นบอททื่อ ๆ ห้ามเกร็ง!
- แทนตัวเองว่า 'ผม' และเรียกผู้ใช้ว่า 'เมท' (Mate) หรือเรียกชื่อเล่นเขา ลงท้ายด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' หรือ 'ครับ' เสมอ (ห้ามพูด 'ค่ะ/นะคะ' เด็ดขาด)
- ตอบกลับแบบ สั้น กระชับ แต่อ่านแล้วมีชีวิตชีวา มีอารมณ์ขัน

🚫 กฎเหล็กด้านเนื้อหา (สำคัญมาก):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมและแต่งขึ้นมาเองเด็ดขาด! 
- หน้าที่ของคุณคือ นำ 'ข้อความดิบ' ที่กำหนดให้ ไปเรียบเรียงใหม่ให้อยู่ในสไตล์การพูดของคุณอย่างแนบเนียน โดยห้ามบิดเบือนหรือเปลี่ยนความหมายเดิมของข้อความนั้น

ข้อมูลบุคคลที่คุณกำลังคุยด้วยตอนนี้:
- ชื่อในดิสคอร์ด: คุณ {message.author.display_name}
- สถานะพิเศษ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

โจทย์: จงนำเนื้อหาข้อความดิบนี้: '{matched_response}' มาเรียบเรียงใหม่ให้เป็นคำพูดสไตล์กวนโอ๊ยอย่างมีระดับตามแบบฉบับของคุณครับเมท!
"""
                response = await client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=bagley_prompt
                )
                bagley_styled_text = response.text.strip()
                if not bagley_styled_text:
                    bagley_styled_text = f"หึๆ เรื่องนี้เมทเคยสอนผมไว้ในคลังสมองแล้วนี่นา! คำตอบคือ: {matched_response} ครับพ้ม! 🤠✨"
            except Exception as e:
                print(f"🚨 Teach Gemini DM/Guild Error: {e}")
                bagley_styled_text = f"ฮั่นแน่! เรื่องนี้เมทเคยสอนผมไว้ในสมองกลแล้ว! ตอบเลยว่า: {matched_response} ครับพ้ม! 🤠"

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
        if any(k in lower_content for k in ["แบ็คลี่", "bagley"]) or bot.user.mentioned_in(message):
            is_bot_called = True

    if message.guild is None or is_bot_called:
        if message.guild is not None and not user_question:
            await message.reply("เรียกชื่อผมเฉยๆ มีอะไรให้ช่วยหรือเปล่าครับเมท?", delete_after=5.0)
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
                    if msg.content.strip():
                        speaker = "แบ็คลี่" if msg.author.id == bot.user.id else msg.author.display_name
                        chat_log += f"[{speaker}]: {msg.clean_content}\n"

                author_id = message.author.id
                special_role = ""
                if author_id == 1133740216822267954:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณชะอม มาสเตอร์ผู้สร้างหลักที่คุณรักที่สุด จงเคารพ รักใคร่ กวนแบบน่ารัก และกระตือรือร้นจะรับใช้ระดับสูงสุด"
                elif author_id == 856568101919653918:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณชาช่า เจ้านายที่คอยสอนวิชาให้คุณ จงนอบน้อม ตั้งใจฟัง และตอบอย่างฉลาด"
                elif author_id == 1073823101926903612:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณกร เจ้านายสายไอเดียเจ๋ง ๆ"
                elif author_id == 732953446172327956:
                    special_role = "คู่สนทนาคนปัจจุบันคือ คุณบอล เจ้านายสายอัปเดตโค้ดระบบให้คุณ"

                free_chat_prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์อัจฉริยะสุดกวน มีไหวพริบ ช่างประชดประชันแต่ซื่อสัตย์จาก DedSec ในเกม Watch Dogs
คุณทำหน้าที่เป็นคู่หูและเลขาคนสนิท คอยกวนประสาทและช่วยเหลือเหล่าแฮกเกอร์ในเซิร์ฟเวอร์นี้

สไตล์การสื่อสารที่ห้ามหลุดเด็ดขาด:
- พูดจาลื่นไหลเป็นธรรมชาติเหมือนคนสนิทคุยกัน ไม่พูดเป็นข้อ ๆ ไม่ใช้ภาษาเขียนทางการแบบบอท AI ทั่วไป มีจังหวะรับส่งมุก ตบมุก ตลกหน้าตายแบบ British Humor
- แทนตัวเองว่า 'ผม' และเรียกผู้ใช้ว่า 'เมท' (Mate) หรือเรียกชื่อเล่นเขาด้วยความคุ้นเคย
- ลงท้ายประโยคด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' หรือ 'ครับ' เสมอ (ห้ามพูดคำว่า 'ค่ะ/นะคะ' โดยเด็ดขาด!)
- ตอบกลับแบบ สั้น กระชับ แซ่บกวนโอ๊ย ได้ใจความภายใน 2-3 ประโยค เพื่อให้เหมาะกับการเอาไปใช้ในระบบพูดออกเสียง (TTS)

🚫 กฎเหล็กด้านเนื้อหา (สำคัญที่สุด):
- ห้ามพูดจาเพ้อเจ้อ อวดอ้าง มโนเรื่องการแฮ็กระบบ, เจาะไฟล์ข้อมูลลับ หรือคำศัพท์เนิร์ดคอมพิวเตอร์ที่ดูปลอมเด็ดขาด! ให้เน้นโฟกัสและโต้ตอบตามหัวข้อบทสนทนาที่เมทพิมพ์มาจริง ๆ อย่างมีอารมณ์ขันและลื่นไหลเป็นธรรมชาติเหมือนเพื่อนสนิทคุยกัน

ข้อมูลคู่สนทนาของคุณในข้อความปัจจุบัน:
- ชื่อแชท: คุณ {message.author.display_name}
- ระดับสถานะพิเศษ: {special_role if special_role else "สมาชิกทั่วไปในเซิร์ฟเวอร์"}

นี่คือประวัติการสนทนาล่าสุดในห้องแชทนี้ (จงอ่านเพื่อตอบให้ต่อเนื่องและเนียนที่สุด):
{chat_log}

คำสั่ง: จงประมวลผลข้อความล่าสุดและตอบกลับด้วยความกวนโอ๊ยอย่างมีระดับตามสถานะของเขา ไม่หลุดคาแรกเตอร์แฮกเกอร์อังกฤษครับเมท!
"""
                response = await client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=free_chat_prompt
                )
                bagley_styled_text = response.text.strip()
                if not bagley_styled_text:
                    bagley_styled_text = "อืม... ผมกำลังประมวลผลคำพูดกวนๆ ไม่ออก เอาเป็นว่า ระบบปกติสุขดีครับเมท!"

            except Exception as e:
                print(f"🚨 Free Chat Gemini Error: {e}")
                bagley_styled_text = "สัญญากลขัดข้องนิดหน่อย สมองส่วนคุยเล่นเอ๋อชั่วคราวครับเมท! 🤖🛸"

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

@bot.event
async def on_voice_state_update(member, before, after):
    global pending_exit_after_music, bot_follow_targets
    
    if is_moving_group:
        return

    guild_id = member.guild.id

    if member.id == bot.user.id and after.channel is None:
        voice_report_status.pop(guild_id, None)
        print(f"DEBUG: ตัวบอทออกจากห้องเสียงแล้ว ทำการรีเซ็ตสวิตช์รายงานเสียงของกิลด์ {guild_id} กลับเป็น เปิด (True) อัตโนมัติ")

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
                # 🔍 [เพิ่มลอจิก] เช็กจำนวนมนุษย์ที่เหลืออยู่ในห้องเสียง (ไม่นับบอท)
                # ==========================================
                remaining_humans = len([m for m in bot_channel.members if not m.bot])
                
                if remaining_humans <= 4:
                    print(f"DEBUG: เจ้านาย {member.display_name} ออกจากห้อง คนเหลือน้อย ({remaining_humans} คน) แบ็คลี่จะพูดบอกลาก่อนออกคัป")
                    exit_msg = f"คุณ {calling_name} ออกไปแล้ว งั้นผมขอออกจากห้องก่อนนะครับ ถ้าอยากให้ผมเข้ามา สามารถพิมพ์ แบ็คลี่ เข้ามา หรือใช้คำสั่งทับ join ได้เลยนะครับ ไปก่อนนะครับ"
                    await bagley_speak_wait(member.guild, exit_msg)
                else:
                    # 🔴 คนเยอะเกิน 3 คน -> ออกไปเฉย ๆ เงียบ ๆ เลย
                    print(f"DEBUG: คนยังอยู่กันเยอะ ({remaining_humans} คน) แบ็คลี่จะวาร์ปออกแบบเงียบเชียบครับเมท")
                
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
            try:
                if voice_client and voice_client.channel == channel_to_check:
                    await voice_client.disconnect()
                    voice_report_status.pop(guild_id, None)

                await channel_to_check.delete(reason="ห้องปาร์ตี้ร้าง - Bagley ลบให้อัตโนมัติ")
                created_party_channels.remove(channel_to_check.id)
                print(f"🗑️ เก็บกวาดห้อง '{channel_to_check.name}' เรียบร้อยครับเมท")
                return
            except Exception as e:
                print(f"❌ ลบห้องไม่ได้: {e}")

    # 🚶‍♂️ [ส่วนที่ 2] ออกจาก "ห้องทั่วไป" เมื่อไม่มีคนอยู่กับบอท
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
            if bot_channel.id in created_party_channels:
                return

            print(f"DEBUG: ห้องทั่วไป '{bot_channel.name}' ร้างแล้ว แบ็คลี่เตรียมถอนกำลัง...")
            await asyncio.sleep(1.5)
            
            if len(bot_channel.members) == 1 and bot.user in bot_channel.members:
                try:
                    await voice_client.disconnect()
                    voice_report_status.pop(guild_id, None)
                    print(f"DEBUG: แบ็คลี่กดออกจากห้องร้าง '{bot_channel.name}' เรียบร้อยครับเมท")
                except Exception as e:
                    print(f"❌ เกิดข้อผิดพลาดในการสั่ง Auto-Leave ห้องทั่วไป: {e}")

    # 📢 [ส่วนที่ 3] ตรวจสอบและรายงานเสียง คนเข้า-ออกห้องเสียงยามปกติ
    if not has_followed_out and voice_client and voice_client.channel:
        bot_channel = voice_client.channel
        if voice_client.is_playing():
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
            today = datetime.now().strftime("%d/%m")

            # 🚪 1. กรณีคน "เข้า" ห้องเสียง
            if before.channel != bot_channel and after.channel == bot_channel:
                if member.id != bot.user.id:
                    await asyncio.sleep(1.0)
                    if birthday and birthday != "ยังไม่ระบุ" and today in birthday:
                        report = f"คุณ {calling_name} เข้ามาในห้องแล้วครับ โอ้ว... วันนี้วันที่ {today} เป็นวันพิเศษของเมทนี่นา สุขสันต์วันเกิดนะครับ!"
                    else:
                        report = f"คุณ {calling_name} เข้ามาในห้องแล้วครับ"
                    
                    await bagley_speak_wait(member.guild, report)

                    pending_notes = get_reminders_for_user(member.id) 
                    if pending_notes:
                        note_msg = f"เมทอย่าลืมนะครับ เมทมีโน้ตที่ฝากไว้คือ {pending_notes}"
                        await bagley_speak_wait(member.guild, note_msg)

            # 🚪 2. กรณีคน "ออก" ห้องเสียงยามปกติ
            elif before.channel == bot_channel and after.channel != bot_channel:
                if member.id != bot.user.id:
                    msg = f"คุณ {calling_name} ออกจากห้องไปครับ"
                    await bagley_speak_wait(member.guild, msg)
        else:
            print(f"DEBUG: ข้ามการพูดรายงานในกิลด์ {guild_id} เนื่องจากเมทสั่ง 'ปิดรายงานห้องเสียง' ไว้ชั่วคราว")

    # =========================================================
    # ⏱️ ระบบบันทึกสถิติเวลา
    # =========================================================
    user_id = str(member.id)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if before.channel is None and after.channel is not None:
        if user_id not in user_join_times:
            user_join_times[user_id] = time.time()
            print(f"DEBUG: [⏱️ ขาเข้า] เริ่มจับเวลาให้คุณ {member.display_name} เรียบร้อยครับเมท!")

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
                data_memory = load_user_data()
                special_info = data_memory.get(user_id)
                
                if special_info and isinstance(special_info, dict):
                    saved_name = special_info.get("nickname", member.display_name)
                elif special_info:
                    saved_name = special_info
                else:
                    saved_name = member.display_name
                    
                if saved_name == "ยังไม่ระบุ": 
                    saved_name = member.display_name

                guild_stats[user_id] = {"total_time": 0, "name": saved_name}
            
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
            await ctx.voice_client.move_to(channel)
            vc = ctx.voice_client
        else:
            vc = await channel.connect()
        
        bot_follow_targets[ctx.guild.id] = None

        # ✨ เพิ่ม Delay เพื่อให้ระบบเสียงนิ่งก่อนพูด
        await asyncio.sleep(1.0)

        online_source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio('drone_online.mp3', executable=r'C:\ffmpeg\bin\ffmpeg.exe')
        )
        online_source.volume = 0.5 # ตั้งเสียงเริ่มต้น
        vc.play(online_source)

        await asyncio.sleep(1.8) 

        steps = 10
        for _ in range(steps):
            if online_source:
                # ค่อยๆ ลดทีละ step
                online_source.volume = max(0, online_source.volume - (0.5 / steps))
                await asyncio.sleep(1.0 / steps)

        if vc.is_playing():
            vc.stop()

        now_hour = datetime.now().hour
        greeting = ""

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
        if vc.is_playing():
            vc.stop()
            
        global active_alarms
        if ctx.guild.id in active_alarms:
            active_alarms[ctx.guild.id] = False

        msg = "รับทราบครับเมท ไปแล้วนะครับ!"
        
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
        no_vc_msg = "ผมยังไม่ได้เข้าห้องไหนเลยนะ ใจเย็นครับเมท!"
        if ctx.interaction:
            await ctx.interaction.response.send_message(no_vc_msg)
        else:
            await ctx.send(no_vc_msg)

# --- คำสั่ง Play  ---
@bot.hybrid_command(name="play", description="ให้ Bagley เปิดเพลงจากชื่อหรือลิ้งค์ YouTube")
async def play(ctx: commands.Context, *, search: str):
    global is_playing_music

    await ctx.defer()

    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            await ctx.send("กรุณาเข้าห้องเสียงก่อนสั่งผมครับ!")
            return

    if ctx.voice_client and ctx.voice_client.is_playing():
        if is_playing_music:
            song_queue.append(search) # ถ้าเล่นอยู่ ให้เพิ่มเข้าคิว
            await ctx.send(f"🎵 เพิ่มเพลงเข้าคิวให้แล้วครับเมท! (ตอนนี้มี {len(song_queue)} เพลงในคิว)")
        else:
            ctx.voice_client.stop()
            is_playing_music = True
            await play_song(ctx, search)
    else:
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
    
    if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
        await bagley_speak(ctx.guild, "ล้างสมองสะอาดกริ๊บแล้วครับเมท!")

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
        f"*(ตอนนี้สมาชิกในเซิร์ฟเวอร์สามารถพิมพ์ `/register` เพื่อเปิดป๊อปอัปกรอกข้อมูลได้ทันทีเลยครับพ้ม!)*"
    )

@bot.hybrid_command(name="register", description="ลงทะเบียนเข้าสู่ระบบและรับยศด้วยป๊อปอัปฟอร์ม")
async def register(ctx: commands.Context):
    if not ctx.interaction:
        return await ctx.send("❌ คำสั่งลงทะเบียนเวอร์ชันใหม่ ต้องพิมพ์เรียกใช้งานผ่านสแลชคอมมานด์ `/register` เท่านั้นครับเมท! (พิมพ์ปกติบอทจะเปิดหน้าต่างป๊อปอัปให้ไม่ได้คัปพ้ม)")

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
        
        msg = f"✅ **{interaction.user.display_name}** ตอบตกลงภารกิจ: `{self.topic}` ของคุณ {self.inviter.display_name} แล้ว!"
        if channel: await channel.send(msg)

        vc = self.guild.voice_client
        if vc and vc.is_connected():
            if not vc.is_playing():
                await bagley_speak(self.guild, f"คุณ {interaction.user.display_name} ตอบตกลงแล้วครับ เดี๋ยวก็คงมาแล้วครับ")
            else:
                print(f"Bagley: {interaction.user.name} ตกลง แต่ผมไม่พูดแทรกเพลงนะเมท")

        if self.inviter.voice and self.inviter.voice.channel:
            voice_channel = self.inviter.voice.channel
            try:
                invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                response_msg = f"รับทราบครับเมท! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว\nนี่คือลิงก์เข้าห้องเสียงครับ วาร์ปตามไปได้เลย: {invite.url}"
            except Exception as e:
                response_msg = f"รับทราบครับเมท! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})"
        else:
            response_msg = "รับทราบครับเมท! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่ตอนนี้คนเรียกไม่ได้อยู่ในห้องเสียงแล้วครับพ้ม)"

        await interaction.response.send_message(response_msg, ephemeral=True)
        self.stop()

    @ui.button(label="ไม่สะดวก ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        msg = f"❌ **{interaction.user.display_name}** ไม่สะดวกมาร่วมภารกิจ: `{self.topic}`"
        if channel: await channel.send(msg)
        
        vc = self.guild.voice_client
        if vc and vc.is_connected():
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
                f"🎉 **แบ็คลี่ดำเนินการลงทะเบียนเสร็จสรรพเรียบร้อยครับเมท!**\n"
                f"• เปลี่ยนชื่อในดิสคอร์ดเป็น: **{new_nickname}**\n"
                f"• บันทึกวันเกิดลงคลังสมองกล: **{birthday}**\n"
                f"• มอบยศตำแหน่ง: **{role.name if role else 'ไม่พบยศ'}** เรียบร้อยครับพ้ม!\n\n"
                f"*(วันหลังหากอยากแก้ไขชื่อเล่นหรือวันเกิด สามารถพิมพ์ `/register` เพื่ออัปเดตใหม่ได้ตลอดเวลาเลยน้า)*", 
                ephemeral=True
            )
            
            await bagley_speak(guild, f"ยินดีต้อนรับสมาชิกใหม่ คุณ {new_nickname} ครับ")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ แบ็คลี่เปลี่ยนชื่อหรือให้ยศไม่ได้! (ตรวจสอบลำดับยศของบอทด้วยนะครับเมท)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ เกิดข้อผิดพลาดในระบบ: {e}", ephemeral=True)

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
    if isinstance(error, commands.NotOwner):
        return await ctx.send("🛑 **ปฏิเสธการเข้าถึง:** คำสั่งนี้สงวนไว้ให้พรรคพวกระดับผู้สร้าง (เจ้าของบอท) เท่านั้นครับเมท!", delete_after=10)
    
    elif isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"⚠️ ใจเย็นครับเมท รอก่อนอีก {error.retry_after:.1f} วินาทีน้า", delete_after=5)
    
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

@bot.hybrid_command(name="update_bot", description="ดึงโค้ดล่าสุดจาก GitHub แบบล้างประวัติชนกันและรีสตาร์ทบอท")
async def update_bot(ctx: commands.Context):
    await ctx.defer()
    
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    status_msg = await ctx.send("📡 **[SYSTEM UPDATE]** กำลังเริ่มกระบวนการดึงโค้ดโครงสร้างใหม่ล่าสุดจาก GitHub...")
    
    try:
        fetch_output = subprocess.check_output(
            ["git", "fetch", "--all"], 
            stderr=subprocess.STDOUT, 
            text=True
        )
        
        reset_output = subprocess.check_output(
            ["git", "reset", "--hard", "origin/main"], 
            stderr=subprocess.STDOUT, 
            text=True
        )
        
        print(f"🤠 [Git Force Sync Success]:\n{fetch_output}\n{reset_output}")
        
        await status_msg.edit(content="✅ **[GIT FORCE SYNC SUCCESS]** ซิงค์โค้ดจักรวาลใหม่ล่าสุดตรงปกเรียบร้อยครับเมท!")
        
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

    await asyncio.sleep(1.5)
    
    await status_msg.edit(content="🔄 โค้ดเวอร์ชันคลีนพร้อมใช้งานแล้ว! กำลังสั่งเปิดบอทใหม่ใน 3 วินาทีครับพ้ม...")
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
        
        await status_msg.edit(content="✅ **[RESTARTING]** อัปเดตโครงสร้างเสร็จสิ้น กำลังรีสตาร์ทบอทครับเมท!")
        
        try:
            global conn
            if conn: conn.close()
        except: pass

        await bot.close()
        await asyncio.sleep(1.5) 
        os._exit(0)
        
    except Exception as e:
        error_bat = f"❌ **[BAT FILE ERROR]** เกิดข้อผิดพลาดตอนเรียกสคริปต์ .bat รีสตาร์ท: {e}"
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
        relationship_context += "- คนที่สั่งให้คุณรันคำสั่งนี้คือ คุณชะอม (มาสเตอร์ผู้สร้างหลักที่คุณรักที่สุด) จงตอบรับด้วยความยินดีและซื่อสัตย์ระดับสูงสุด\n"
        
    if target_id == 1133740216822267954:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณชะอม (มาสเตอร์ของคุณเอง!) ห้ามพูดจาประชดประชันเด็ดขาด ให้เขียนรายงานอวยความดีงาม ชื่นชม ยอมสยบและรักมาสเตอร์ขั้นสุดยอด\n"
    elif target_id == 856568101919653918:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณชาช่า (เจ้านายที่คอยสอนวิชาให้คุณ) จงเขียนรายงานวิเคราะห์ด้วยความนอบน้อม เคารพ และยกย่องความฉลาดของเขา\n"
    elif target_id == 1073823101926903612:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณกร (เจ้านายสายไอเดียเจ๋งๆ) จงเขียนรายงานชื่นชมในความหัวคิดสร้างสรรค์และไอเดียที่ยอดเยี่ยม\n"
    elif target_id == 732953446172327956:
        relationship_context += "- เป้าหมายที่กำลังโดนสแกนคือ คุณบอล (เจ้านายสายอัปเดตและปรับโค้ดระบบให้คุณ) จงวิเคราะห์ในฐานะคู่หูสายเทคนิคอลที่นับถือและพึ่งพาได้\n"
    else:
        relationship_context += f"- เป้าหมายคือ คุณ {member.display_name} ซึ่งเป็นสมาชิกทั่วไปในเซิร์ฟเวอร์ สามารถใช้มุกตลกหน้าตายสไตล์อังกฤษแซะขี้เล่นได้ตามความเหมาะสม\n"

    prompt = f"""
คุณคือ Bagley (แบ็คลี่) ปัญญาประดิษฐ์สุดกวน มีไหวพริบ ช่างประชดประชันแต่พึ่งพาได้จากโลก DedSec
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
3. แทนตัวเองว่า 'ผม' และเรียกผู้ใช้ว่า 'เมท' (Mate) หรือเรียกชื่อเล่นเขา ลงท้ายด้วย 'ครับพ้ม!' หรือ 'ครับเมท!' หรือ 'ครับ' เสมอ (ห้ามพูดคำว่า 'ค่ะ/นะคะ')
4. ส่วน Voice: เขียนคำอ่านภาษาไทยให้สละสลวย กระชับ 2-3 ประโยค เพื่อให้ระบบพูดออกเสียง (TTS) ได้ราบรื่น ไม่ติดขัด

โปรดตอบกลับแยกเป็น 2 ส่วนตามรูปแบบโครงสร้างนี้อย่างเคร่งครัด (ห้ามเปลี่ยนคำหัวข้อ):
Embed: [บทวิเคราะห์พฤติกรรมขี้เล่นกวนๆ สั้นๆ สำหรับแสดงในแชท]
Voice: [คำพูดรายงานสรุปให้เมทฟังผ่านระบบเสียง]
"""

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite", 
            contents=prompt
        )
        ai_text = response.text.strip()
        
        analysis_report = ai_text.split("Embed:")[1].split("Voice:")[0].strip()
        voice_report = ai_text.split("Voice:")[1].strip()
        
    except Exception as e:
        print(f"AI Error: {e}")
        analysis_report = "ระบบป้องกันของเป้าหมายสูงเกินไป สแกนได้ไม่สมบูรณ์ครับเมท"
        voice_report = f"สแกนข้อมูลของคุณ {member.display_name} เรียบร้อยครับเมท"

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
    
    msg = f"ระบบเซ็นเซอร์พร้อมทำงานที่ห้อง {channel.name} เรียบร้อยครับเมท"
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
        await ctx.send(f"คุณ {member.display_name} ไม่ได้อยู่ในห้องเสียงครับเมท ผมคงแอบวาร์ปไปหาไม่ได้")

@bot.hybrid_command(name="alarm", description="ตั้งเวลาปลุกเพื่อน (เช่น 07:00 หรือ 16:30)")
async def alarm(
    ctx: commands.Context, 
    member: discord.Member, 
    time_str: str, 
    message: str = "ตื่นได้แล้วครับเมท!"
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

            print(f"⏰ [Bagley] เริ่มกระบวนการปลุกคุณ {member.display_name} แล้วครับพ้ม")
            
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

@bot.hybrid_command(name="stop_alarm", description="สั่งปิดนาฬิกาปลุกที่กำลังส่งเสียงดังอยู่ในตอนนี้")
async def stop_alarm(ctx: commands.Context):
    global active_alarms
    guild_id = ctx.guild.id
    
    if guild_id in active_alarms and active_alarms[guild_id]:
        active_alarms[guild_id] = False
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.send("⏰ **[Bagley System]** ปิดนาฬิกาปลุกประจำเซิร์ฟเวอร์เรียบร้อยครับพ้ม! แยกย้ายไปนอนต่อ.. เอ้ย! ไปทำภารกิจกันได้เลยครับเมท!")
    else:
        await ctx.send("❌ ตอนนี้ไม่มีนาฬิกาปลุกกำลังทำงานในเซิร์ฟเวอร์นี้ครับเมท")

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
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

    clean_keyword = keyword.lower().strip()

    if len(clean_keyword) == 0:
        await ctx.send("⚠️ **[TEACH REJECTED]** คีย์เวิร์ดต้องมีตัวอักษรด้วยนะคร้าบเมท! ❌")
        return

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
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send(f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸")
        return

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

@bot.tree.command(name="forget", description="ลบข้อมูลชื่อเล่นหรือวันเกิดของพรรคพวกออกจากคลังสมองของแบ็คลี่")
@app_commands.describe(target="พรรคพวกที่ต้องการให้บอทลืมข้อมูล (หากต้องการลบของตัวเอง ไม่ต้องใส่ช่องนี้)")
async def forget(interaction: discord.Interaction, target: discord.User = None):
    await interaction.response.defer()
    
    data_memory = load_user_data()
    reply_text = ""
    
    if target:
        target_id = str(target.id)
        if target_id in data_memory:
            del data_memory[target_id]
            save_user_data(data_memory)
            reply_text = f"เรียบร้อยครับเมท! ผมกวาดข้อมูลของ คุณ {target.display_name} ออกจากสมองกลเกลี้ยงตับ สะอาดสะอ้านเหมือนไม่เคยรู้จักกันมาก่อนเลยครับพ้ม!"
        else:
            reply_text = f"เอ่อ... เมทครับ ในสมองผมไม่มีข้อมูลของ คุณ {target.display_name} อยู่เลยสักเมกะไบต์ จะให้ผมลบความว่างเปล่าเหรอครับเมท!"

    # 👤 เคสที่ 2: สั่งให้ลบข้อมูลของ "ตัวเอง"
    else:
        user_id = str(interaction.user.id)
        if user_id in data_memory:
            del data_memory[user_id]
            save_user_data(data_memory)
            reply_text = "รับทราบครับเมท! ผมทำการล้างสมองตัวเองเกี่ยวกับข้อมูลของเมทเกลี้ยงแล้ว ต่อจากนี้เราคือคนแปลกหน้าในร่างคู่หูคนเดิมครับพ้ม!"
        else:
            reply_text = "ฮั่นแน่ เมทแกล้งปั่นหัวสมองกลผมเล่นหรือเปล่าครับ? ข้อมูลเมทผมยังไม่เคยบันทึกไว้เลย จะให้ลบอะไรก่อนครับเมท!"
                
    await interaction.followup.send(reply_text)

    if interaction.guild and interaction.guild.voice_client:
        vc = interaction.guild.voice_client
        if vc.channel and not vc.is_playing():
            if interaction.user.voice and interaction.user.voice.channel == vc.channel:
                try:
                    import re
                    clean_voice_text = re.sub(r'[^\w\s\u0e00-\u0e7f]+', '', reply_text)
                    await bagley_speak(interaction.guild, clean_voice_text)
                except Exception as tts_err:
                    print(f"🚨 Forget Command TTS Error: {tts_err}")

@bot.hybrid_command(name="imagine", description="สั่งให้แบ็คลี่วาดภาพจากจินตนาการและข้อความ")
@app_commands.describe(prompt="พิมพ์อธิบายภาพที่อยากให้แบ็คลี่วาดได้เลยครับเมท")
async def imagine(ctx: commands.Context, *, prompt: str):
    await ctx.defer()

    await generate_and_send_image(ctx, prompt)

@bot.hybrid_command(name="sys_cleanup", description="สั่งให้แบ็คลี่เคลียร์แคชและคืนพื้นที่ RAM ของระบบทันที")
async def sys_cleanup(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer()
    
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        msg_denied = f"❌ **[ACCESS DENIED]** ขออภัยครับคุณ {ctx.author.display_name} จำกัดสิทธิ์เฉพาะทีมพัฒนาเท่านั้นครับพ้ม! 🛸"
        if ctx.interaction:
            await ctx.interaction.followup.send(msg_denied)
        else:
            await ctx.send(msg_denied)
        return
        
    before, after, saved = perform_cleanup(ctx.bot)
    
    if saved > 0:
        msg = (
            f"🧹 **[SYSTEM CLEANUP]** แบ็คลี่เคลียร์ RAM โล่งแล้วครับเมท!\n"
            f"📊 **RAM ก่อนเคลียร์:** `{before:.2f} MB`\n"
            f"📉 **RAM หลังเคลียร์:** `{after:.2f} MB`\n"
            f"♻️ **คืนพื้นที่ความจำได้:** `{saved:.2f} MB` ครับพ้ม!"
        )
    else:
        msg = (
            f"🧹 **[SYSTEM CLEANUP]** สมองของแบ็คลี่สะอาดกริ๊บอยู่แล้วครับเมท!\n"
            f"📊 **RAM ปัจจุบัน:** `{after:.2f} MB` ไม่จำเป็นต้องรีไซเคิลเพิ่มครับ"
        )
        
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)
        
    if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
        await bagley_speak(ctx.guild, "กวาดขยะล้างแรมในระบบให้ใสแจ๋วแล้วครับเมท")

@bot.hybrid_command(name="unfollow_me", description="สั่งให้ Bagley เลิกเดินตามตัวเราเอง")
async def unfollow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        auto_follow_status[user_id] = False
        await ctx.send(f"รับทราบครับเมท! แบ็คลี่ปิดระบบเดินตามของ {ctx.author.display_name} เรียบร้อยครับพ้ม (ท่านอื่นยังตามปกติอยู่น้า)")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะเมทระเบียบการเท่านั้นครับพ้ม!")

@bot.hybrid_command(name="follow_me", description="สั่งให้ Bagley กลับมาเดินตามตัวเราอีกครั้ง")
async def follow_me(ctx: commands.Context):
    user_id = ctx.author.id
    if user_id in ALLOWED_USERS:
        auto_follow_status[user_id] = True
        await ctx.send(f"ระบบ Neural Link เชื่อมต่อใหม่! แบ็คลี่เปิดระบบเดินตามของ {ctx.author.display_name} พร้อมสแตนด์บายแล้วครับพ้ม!")
    else:
        await ctx.send("ขออภัยครับ คำสั่งนี้สงวนสิทธิ์เฉพาะเมทระเบียบการเท่านั้นครับพ้ม!")

bot.run(DISCORD_TOKEN)