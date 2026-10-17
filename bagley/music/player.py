"""bagley/music/player.py — เล่นเพลง (yt-dlp) และจัดการคิวเพลง"""
import asyncio
import discord
import yt_dlp

from bagley.core import state
from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.phrases import say
from bagley.voice.mixer import DuckingMixer
from bagley.voice.tts import FFMPEG_PATH, bagley_speak, bagley_speak_wait


async def play_song(ctx, search):
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'auto',
        'nocheckcertificate': True,
        # 🩹 FIX: YouTube เข้มงวดเรื่องกันบอทมากขึ้นเรื่อยๆ (ระลอกล่าสุด ส.ค. 2026)
        # การดึงข้อมูลผ่าน client เริ่มต้น (web) มักโดน 403 ทันทีตอนเปิดสตรีมจริง
        # (แม้จะดึงชื่อเพลง/ข้อมูลได้ปกติ) จึงสั่งให้ yt-dlp ลองหลาย client ตามลำดับ
        # ถ้า client แรกโดนบล็อก จะไปลอง client ถัดไปโดยอัตโนมัติ
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
            }
        },
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            if search.startswith("http"):
                info = await asyncio.to_thread(ydl.extract_info, search, download=False)
            else:
                info = (await asyncio.to_thread(ydl.extract_info, f"ytsearch:{search}", download=False))['entries'][0]

            if 'entries' in info:
                info = info['entries'][0]

            url = info['url']
            title = info['title']

            # 🩹 FIX: googlevideo ต้องได้ header (โดยเฉพาะ User-Agent) ตรงกับตอนที่ yt-dlp
            # ใช้ดึงข้อมูลมา ไม่งั้น YouTube จะตัดสตรีมทิ้งทันที (403 / 0 byte) ทำให้ ffmpeg
            # จบโปรเซสเกือบจะทันทีที่เริ่ม เป็นเหตุให้ discord.py เรียก after_playing()
            # เหมือนเพลงเล่นจบ ทั้งที่จริงๆ เสียงไม่เคยออกมาเลย แล้วก็ไปเจอคิวว่างพอดี
            # จึงพูดว่า "คิวหมดแล้ว" ทันทีหลังจากเพิ่งประกาศว่ากำลังเล่นเพลง
            req_headers = info.get('http_headers') or {}
            if req_headers:
                headers_str = ''.join(f'{k}: {v}\r\n' for k, v in req_headers.items())
                FFMPEG_OPTIONS['before_options'] += f' -headers "{headers_str}"'

            def after_playing(error):
                state.is_playing_music = False
                print(f"จบเพลง: {title}")
                if error:
                    print(f"Player error: {error}")

            state.is_playing_music = True
            # 🚨 [ใหม่] จำคำค้น/URL ของเพลงที่กำลังจะเล่นไว้ เผื่อโดนตัดจบกลางคันเพราะมีแจ้งเตือนสำคัญ
            # เข้ามา (เช่น ตารางนัด/reminder) จะได้เอากลับมาเล่นต่อ(ใหม่)ให้คุณได้หลังแจ้งเตือนเสร็จ
            state.current_playing_search[ctx.guild.id] = search
            raw_source = discord.FFmpegPCMAudio(
                url, 
                executable=FFMPEG_PATH, 
                **FFMPEG_OPTIONS
            )
            
            volume_controlled_source = discord.PCMVolumeTransformer(raw_source)
            volume_controlled_source.volume = 0.15

            def _after(e):
                # เดิม error ตรงนี้ถูกทิ้งเงียบๆ ทำให้เวลา ffmpeg ล้มเหลว (เช่นโดน 403
                # จากยูทูป) บอทจะตัดไปเช็คคิวทันทีโดยไม่มีร่องรอยให้ debug เลย
                if e:
                    print(f"❌ [FFmpeg after-callback error] เพลง '{title}' หยุดเล่นแบบผิดปกติ: {e}")
                bot.loop.create_task(check_queue(ctx))

            # ครอบด้วยตัวผสมเสียง: ตอนบอทพูด/ติ๊ด จะหรี่เพลงลงแล้วเอาเสียงมาซ้อน ไม่ต้องรอเพลงจบ
            ctx.voice_client.play(
                DuckingMixer(volume_controlled_source),
                after=_after
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
            state.is_playing_music = False
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

    # 🚨 [ใหม่] ถ้าตอนนี้กิลด์นี้กำลังมีการวาร์ปไปแจ้งเตือนสำคัญอยู่ (ตารางนัด/reminder ที่เพิ่งตัด
    # จบเพลงปัจจุบันเพื่อไปเตือนก่อน) ให้รอจนกว่าจะแจ้งเตือนเสร็จก่อน กันไม่ให้เพลงถัดไปเริ่มเล่นแทรก
    # ชนกับเสียงแจ้งเตือนที่กำลังพูดอยู่ในอีกห้องหนึ่ง (กันเผื่อค้างนานสุด ~60 วินาที)
    wait_ticks = 0
    while ctx.guild.id in state.priority_alert_active_guilds and wait_ticks < 300:
        await asyncio.sleep(0.2)
        wait_ticks += 1

    if len(state.song_queue) > 0:
        state.is_playing_music = True
        next_search = state.song_queue.pop(0) 
        
        try:
            await play_song(ctx, next_search) 
        except Exception as e:
            print(f"❌ [Queue Error]: เล่นเพลง {next_search} ไม่สำเร็จ -> {e}")
            await ctx.channel.send("⚠️ " + say("music_track_error", song=f"**{next_search}**"))
            await check_queue(ctx)
            
    else:
        state.is_playing_music = False

        # 🔇 [ใหม่] ถ้าคิวว่างเพราะเพิ่งสั่ง /stop มาเอง ไม่ใช่เพลงหมดคิวตามธรรมชาติ
        # ให้ข้ามการพูด "คิวหมดแล้วครับ" ไปเลย เพราะคำสั่ง stop พูด say("music_stopped")
        # ของตัวเองอยู่แล้ว พูดซ้ำสองประโยคติดกันมันเยิ่นเย้อเกินไป
        was_manual_stop = ctx.guild.id in state.manual_stop_guilds
        state.manual_stop_guilds.discard(ctx.guild.id)

        left_user_name = state.pending_exit_after_music.pop(ctx.guild.id, None)
        
        if left_user_name:
            exit_msg = f"เพลงในคิวหมดแล้วครับ แต่ตอนนี้คุณ {left_user_name} ออกไปแล้ว งั้นผมขอออกจากห้องก่อนนะ ถ้าอยากให้ผมเข้ามาใหม่ พิมพ์ แบ็คลี่ เข้ามา หรือใช้คำสั่งทับ join ได้เลย ไปก่อนนะ!"
            await bagley_speak_wait(ctx.guild, exit_msg)
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                state.voice_report_status.pop(ctx.guild.id, None)
                state.bot_follow_targets[ctx.guild.id] = None # ล้างสมุดจดบันทึกการตามในลูป 10 นาที
                print(f"DEBUG: 🎵 เพลงจบเซ็ต -> พบบันทึกเตือนจำ -> แบ็คลี่พูดรายงานคุณ {left_user_name} แล้ววาร์ปออกเรียบร้อย!")
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดตอนบอทตัดสายหลังคิวเพลงจบเซ็ต: {e}")
        elif was_manual_stop:
            print("DEBUG: 🔇 คิวว่างเพราะสั่ง /stop มาเอง ข้ามพูด 'คิวหมดแล้วครับ' กันพูดซ้ำกับข้อความของคำสั่ง stop")
        elif state.pending_speak_count.get(ctx.guild.id, 0) > 0:
            # 🔇 [ใหม่] ตอนนี้มีข้อความอื่น (เช่น คนเข้า-ออกห้องที่สะสมไว้ระหว่างเปิดเพลง) กำลังรอต่อคิว
            # พูดอยู่แล้ว ข้ามข้อความเติมเต็มของระบบเพลงไปเลย กันไม่ให้บอทพูดรัวเกินไป ส่วนข้อความ
            # คนเข้า-ออกที่รออยู่จะได้ต่อคิวพูดกันไปตามปกติ (พูดเสร็จทีละประโยคแล้วพูดต่อ)
            print(f"DEBUG: 🔇 มีข้อความอื่นรอต่อคิวพูดอยู่ {state.pending_speak_count.get(ctx.guild.id, 0)} รายการ ข้ามพูด 'คิวหมดแล้วครับ' กันพูดรัวเกินไป")
        else:
            await bagley_speak(ctx.guild, say("music_queue_end"))
            print("คิวว่างแล้วครับ Bagley พูดรายงานเรียบร้อย")
