"""bagley/services/youtube.py — เช็คช่อง YouTube (ไลฟ์/คลิปใหม่) และแจ้งเตือน"""
import aiohttp
import discord
from discord import ui

from bagley.core.app import bot
from bagley.core.config import YT_API_KEY
from bagley.core.http import get_json as http_get_json
from bagley.core.logutil import print
from bagley.db import conn
from bagley.voice.tts import bagley_speak


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
                    status_res = await http_get_json(status_url)
                    
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
            ch_res = await http_get_json(ch_url)
            
            if "items" in ch_res and len(ch_res["items"]) > 0:
                uploads_playlist_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                
                playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YT_API_KEY}&playlistId={uploads_playlist_id}&part=snippet&maxResults=3"
                playlist_res = await http_get_json(playlist_url)
                
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
