"""bagley/commands/youtube.py — คำสั่งตั้งค่าติดตามช่อง YouTube"""
import discord
from discord import app_commands
from discord.ext import commands

from bagley.core.app import bot
from bagley.core.config import YT_API_KEY
from bagley.core.http import get_json as http_get_json
from bagley.core.logutil import print
from bagley.db import conn
from bagley.services.youtube import YTCheckView
from bagley.ui.views import IdentityListPaginator
from bagley.voice.tts import bagley_speak


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
    res = await http_get_json(url)
    
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
                # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
                await bagley_speak(ctx.guild, f"ติดตั้งระบบสอดแนมช่อง {name} เรียบร้อยแล้วครับ")
            except Exception as e:
                msg = f"เกิดข้อผิดพลาดในการบันทึกข้อมูลครับ!"
                print(f"Error: {e}")
        
    else:
        msg = "หาช่องไม่เจอ! ตรวจสอบ Channel ID อีกทีนะครับ"
        await bagley_speak(ctx.guild, "หาช่องไม่เจอครับ ตรวจสอบไอดีอีกทีนะ")

    # การตอบกลับ
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)


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
