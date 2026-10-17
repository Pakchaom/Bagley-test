"""bagley/commands/music.py — คำสั่งเพลง + อ่านแชทสด YouTube"""
from discord import app_commands
from discord.ext import commands
from typing import Optional

from bagley.ai.classifiers import ai_check_live_chat_message, ai_extract_yt_intro_name, ai_reply_to_live_chat_mention
from bagley.core import state
from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.music.player import play_song
from bagley.music.spotify import parse_spotify_link, resolve_spotify_link
from bagley.phrases import say
from bagley.services import youtube_live_chat as ylc
from bagley.voice.client import connect_voice
from bagley.voice.tts import bagley_speak


# --- คำสั่ง Play  ---
@bot.hybrid_command(name="play", description="ให้ Bagley เปิดเพลงจากชื่อ ลิ้งค์ YouTube หรือลิ้งค์ Spotify (เพลงเดี่ยว/อัลบั้ม/เพลย์ลิสต์/ศิลปิน)")
async def play(ctx: commands.Context, *, search: str):

    await ctx.defer()

    if not ctx.voice_client:
        if ctx.author.voice:
            await connect_voice(ctx.author.voice.channel)
        else:
            await ctx.send(say("need_voice"))
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
        if state.is_playing_music:
            # ถ้าเล่นอยู่ ให้เพิ่มเข้าคิวทั้งหมด (ทั้งเพลงเดี่ยวหรือทุกเพลงในอัลบั้ม)
            state.song_queue.append(first_query)
            state.song_queue.extend(rest_queries)
            await ctx.send("🎵 " + say("music_added", n=len(state.song_queue)))
        else:
            ctx.voice_client.stop()
            state.is_playing_music = True
            state.song_queue.extend(rest_queries)  # เพลงที่เหลือในอัลบั้มต่อเข้าคิว
            await play_song(ctx, first_query)
    else:
        state.is_playing_music = True
        state.song_queue.extend(rest_queries)  # เพลงที่เหลือในอัลบั้มต่อเข้าคิว
        await play_song(ctx, first_query)


@bot.hybrid_command(name="watch_live_chat", description="ให้แบ็คลี่เริ่มอ่านแชทสดจากไลฟ์ YouTube (ทุกข้อความ เว้นแต่ตั้งคำกรองไว้)")
@app_commands.describe(video="ลิงก์ไลฟ์ YouTube หรือ video id หรือ channel id/handle ของช่องที่กำลังไลฟ์อยู่")
async def watch_live_chat(ctx: commands.Context, video: str):
    if ctx.interaction:
        await ctx.interaction.response.defer()

    if not ctx.guild:
        msg = "คำสั่งนี้ใช้ได้แค่ในเซิร์ฟเวอร์เท่านั้นครับ"
    elif not ctx.guild.voice_client:
        msg = "แบ็คลี่ต้องอยู่ในห้องเสียงก่อนถึงจะพูดแชทให้ได้นะครับ เข้าห้องเสียงให้แบ็คลี่ก่อนครับ"
    else:
        async def _announce(text):
            print(f"📺 [Live Chat Watcher] {text}")
            try:
                await ctx.send(text)
            except Exception:
                pass

        await ylc.start_watch(
            ctx.guild, video, bagley_speak, _announce, ai_check_live_chat_message,
            ai_reply_to_live_chat_mention, ai_extract_yt_intro_name,
        )
        if ylc.LIVE_CHAT_KEYWORDS:
            msg = f"เริ่มอ่านแชทสดแล้วครับ! กำลังฟังคำว่า: {', '.join(ylc.LIVE_CHAT_KEYWORDS)}"
        else:
            msg = "เริ่มอ่านแชทสดแล้วครับ! จะพูดทุกข้อความที่เข้ามาเลยนะครับ"

    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


@bot.hybrid_command(name="toggle_live_chat", description="สลับสถานะอ่านแชทสด: ยังไม่เริ่ม->เริ่ม (ต้องแปะลิงก์), กำลังพูด->หยุดชั่วคราว, หยุดชั่วคราว->พูดต่อ")
@app_commands.describe(video="ต้องแปะลิงก์/รหัสไลฟ์เฉพาะรอบแรกที่ยังไม่เคยเริ่ม ถ้ากำลังอ่านอยู่แล้วไม่ต้องใส่")
async def toggle_live_chat(ctx: commands.Context, video: Optional[str] = None):
    """
    คำสั่งเดียวกดสลับ 3 สถานะ เหมือนคีย์ลัดของดาเรน แต่เป็นแบบพิมพ์คำสั่งแทน (เพราะแบ็คลี่ไม่มีแอพ
    ที่ตั้งค่าคีย์ลัดได้เหมือนดาเรน):
      ยังไม่เริ่ม -> ต้องแปะลิงก์สตรีมมาด้วย ถึงจะเริ่มอ่านแชทสดได้
      กำลังพูดอยู่ -> พิมพ์คำสั่งซ้ำ (ไม่ต้องใส่ลิงก์) เพื่อหยุดพูดชั่วคราว (ยังฟังอยู่เบื้องหลัง)
      หยุดชั่วคราวอยู่ -> พิมพ์คำสั่งซ้ำอีกครั้ง เพื่อพูดแชทที่ค้างคิวไว้ต่อ แล้วพูดแชทสดใหม่ต่อตามปกติ
    """
    if ctx.interaction:
        await ctx.interaction.response.defer()

    if not ctx.guild:
        msg = "คำสั่งนี้ใช้ได้แค่ในเซิร์ฟเวอร์เท่านั้นครับ"
    elif not ctx.guild.voice_client:
        msg = "แบ็คลี่ต้องอยู่ในห้องเสียงก่อนถึงจะพูดแชทให้ได้นะครับ เข้าห้องเสียงให้แบ็คลี่ก่อนครับ"
    elif not ylc.is_watching(ctx.guild.id) and not video:
        msg = "ยังไม่เคยเริ่มอ่านแชทสดเลยครับ ต้องพิมพ์คำสั่งนี้พร้อมแปะลิงก์ไลฟ์มาด้วยรอบแรกครับ (เช่น `/toggle_live_chat video:<ลิงก์>`)"
    else:
        async def _announce(text):
            print(f"📺 [Live Chat Watcher] {text}")
            try:
                await ctx.send(text)
            except Exception:
                pass

        result = await ylc.toggle_watch(
            ctx.guild, video or "", bagley_speak, _announce, ai_check_live_chat_message,
            ai_reply_to_live_chat_mention, ai_extract_yt_intro_name,
        )
        if result == "started":
            if ylc.LIVE_CHAT_KEYWORDS:
                msg = f"เริ่มอ่านแชทสดแล้วครับ! กำลังฟังคำว่า: {', '.join(ylc.LIVE_CHAT_KEYWORDS)}"
            else:
                msg = "เริ่มอ่านแชทสดแล้วครับ! จะพูดทุกข้อความที่เข้ามาเลยนะครับ"
        elif result == "paused":
            msg = "หยุดพูดแชทสดชั่วคราวแล้วครับ (ยังฟังอยู่เบื้องหลัง พิมพ์คำสั่งเดิมอีกครั้งเพื่อพูดต่อ)"
        else:
            msg = "พูดแชทสดต่อแล้วครับ (จะพูดที่ค้างไว้ก่อน แล้วพูดแชทใหม่ต่อ)"

    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


@bot.hybrid_command(name="stop_live_chat", description="หยุดให้แบ็คลี่อ่านแชทสดจากไลฟ์ YouTube (เลิกฟังไปเลย ไม่ใช่แค่หยุดชั่วคราว)")
async def stop_live_chat(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer()

    if ctx.guild and ylc.is_watching(ctx.guild.id):
        await ylc.stop_watch(ctx.guild)
        msg = "หยุดอ่านแชทสดแล้วครับ"
    else:
        msg = "ตอนนี้แบ็คลี่ไม่ได้อ่านแชทสดอยู่ครับ"

    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


@bot.hybrid_command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
async def skip(ctx: commands.Context):
    if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
        return await ctx.send(say("music_none_to_skip"))

    await ctx.send("⏭️ " + say("music_skipped"))

    # 2. สั่งหยุดเพลงปัจจุบัน (การ stop() นี้จะไปสั่งให้ callback `_after` ใน play_song()
    # เรียก check_queue() ให้เล่นเพลงถัดไปเองอัตโนมัติอยู่แล้ว)
    # 🔧 [แก้บั๊ก] เดิมโค้ดตรงนี้เรียก `await check_queue(ctx)` ซ้ำอีกรอบด้านล่าง ทำให้
    # check_queue() ถูกเรียกพร้อมกัน 2 ที่ (ทั้งจาก callback และจากตรงนี้) แย่งกัน pop
    # เพลงถัดไปออกจากคิวไปเล่นซ้อนกัน ทำให้บางทีข้ามเพลงเกินไป 1 เพลง หรือเสียงเพลงสองเพลง
    # เล่นชนกัน ตอนนี้ปล่อยให้ callback อัตโนมัติจัดการเล่นเพลงถัดไปแทนโดยไม่ต้องเรียกซ้ำเอง
    ctx.voice_client.stop()


@bot.hybrid_command(name="queue", description="ดูรายการเพลงในคิว")
async def queue(ctx: commands.Context):
    if len(state.song_queue) == 0:
        # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
        await bagley_speak(ctx.guild, say("music_queue_empty"))
        return await ctx.send(say("music_queue_empty"))
    
    msg = "**🎵 รายการเพลงในคิวตอนนี้:**\n"
    for i, song in enumerate(state.song_queue, 1):
        msg += f"{i}. {song}\n"
    
    await ctx.send(msg)


# --- คำสั่ง Stop  ---
@bot.hybrid_command(name="stop", description="สั่งให้ Bagley หยุดส่งเสียงรบกวน")
async def stop(ctx: commands.Context):
    if ctx.voice_client:
        # 1. เพิ่มบรรทัดนี้: ล้างเพลงที่ค้างอยู่ในคิวทั้งหมดทิ้งไป!
        state.song_queue.clear() 

        # 2. ถ้าเพลงกำลังเล่นอยู่ ก็สั่งให้หยุด
        if ctx.voice_client.is_playing():
            # 🔇 [ใหม่] ปักธงไว้ก่อนว่ากิลด์นี้เพิ่งสั่ง /stop มาเอง เพื่อให้ check_queue()
            # (ที่จะถูกเรียกอัตโนมัติจาก callback ตอนเพลงหยุด) รู้ว่าไม่ต้องพูด "คิวหมดแล้วครับ"
            # ซ้ำอีกรอบ เดี๋ยวข้างล่างจะพูด say("music_stopped") แค่ประโยคเดียวพอ
            state.manual_stop_guilds.add(ctx.guild.id)
            ctx.voice_client.stop()
        
        msg = "หยุดเล่นเพลงและล้างคิวทั้งหมดเรียบร้อยครับ!"
        
        if ctx.interaction: 
            await ctx.interaction.response.send_message(msg)
        else: 
            await ctx.send(msg)
        
        await bagley_speak(ctx.guild, say("music_stopped"))
    else:
        await ctx.send(say("music_stop_nothing"))
