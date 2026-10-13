"""bagley/services/images.py — ดูรูป (caption) และวาดรูปด้วย Pollinations"""
import aiohttp
import discord
import io
import random
import urllib.parse
from PIL import Image

from bagley.core import state
from bagley.core.app import client
from bagley.core.config import _IMAGE_CAPTION_CACHE_MAX
from bagley.core.http import get_bytes as http_get_bytes
from bagley.core.logutil import print
from bagley.phrases import say
from bagley.voice.tts import bagley_speak


def _remember_image_caption(message_id: int, caption: str | None):
    """จำ caption ของรูปภาพไว้ผูกกับ message_id — เรียกทุกครั้งที่วิเคราะห์รูปสำเร็จ ไม่ว่าจะจากจุดไหนในไฟล์นี้"""
    if not caption:
        return
    state._image_caption_cache[message_id] = caption
    if len(state._image_caption_cache) > _IMAGE_CAPTION_CACHE_MAX:
        # ตัดอันที่เก่าที่สุดทิ้ง (dict ใน Python 3.7+ เรียงตามลำดับที่ใส่เข้ามา)
        oldest_id = next(iter(state._image_caption_cache))
        state._image_caption_cache.pop(oldest_id, None)


def _get_cached_image_caption(message_id: int) -> str | None:
    return state._image_caption_cache.get(message_id)


async def get_quick_image_caption(image_url: str) -> str | None:
    """🖼️ [ใหม่] แคปชั่นรูปภาพแบบสั้นๆ เร็วๆ (1 ประโยค) เอาไว้ป้อนเข้า bagley_learning/bagley_autonomy
    เท่านั้น (ไม่ใช่คำตอบที่จะส่งให้ user เห็นตรงๆ) — ใช้ตอนมีคนโพสต์รูปในห้องที่บอทเคยเกี่ยวข้องด้วย
    โดยไม่ได้เรียกชื่อบอทตรงๆ (ถ้าเรียกชื่อบอทตรงๆ ระบบสแกนรูปเต็มรูปแบบด้านล่างจะจัดการให้เองอยู่แล้ว
    ไม่ต้องเรียกฟังก์ชันนี้ซ้ำ) เพื่อให้ระบบ 'ชวนคุย' ของบอทมองเห็นว่ามีรูปอะไรถูกโพสต์ไปด้วย
    คืนค่า None เงียบๆ ถ้าดึง/วิเคราะห์รูปไม่สำเร็จ (ไม่ต้องการให้ error ตรงนี้ไปรบกวน flow หลักของ on_message)"""
    try:
        img_bytes = await http_get_bytes(image_url, timeout=10)
        img = Image.open(io.BytesIO(img_bytes))
        prompt = (
            "อธิบายสิ่งที่เห็นในรูปภาพนี้สั้นๆ แค่ 1 ประโยคเท่านั้น เป็นภาษาไทย เน้นข้อเท็จจริงที่เห็นจริงในภาพ "
            "ห้ามใส่มุกตลก คำแซว หรือความเห็นส่วนตัวใดๆ เพราะข้อความนี้จะถูกเก็บไว้เป็นความจำเบื้องหลังของบอทเฉยๆ "
            "ไม่ได้ส่งให้ใครอ่านตรงๆ"
        )
        response = await client.aio.models.generate_content(
            model="chat",
            contents=[prompt, img],
        )
        caption = (response.text or "").strip()
        return caption or None
    except Exception as e:
        print(f"⚠️ [ImageCaption] แคปชั่นรูปภาพสำหรับระบบเรียนรู้พลาด: {e}")
        return None


async def generate_and_send_image(ctx_or_interaction, prompt: str):
    
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
                        if not state.is_playing_music and not guild.voice_client.is_playing():
                            await bagley_speak(guild, say("image_ready"))
                else:
                    raise Exception(f"เซิร์ฟเวอร์ตอบกลับด้วยสถานะ {response.status}")

    except Exception as e:
        error_text = f"❌ หว่า... แบ็คลี่ดึงภาพไม่สำเร็จเนื่องจาก: {e}"
        if is_interaction:
            await ctx_or_interaction.followup.send(error_text, ephemeral=True)
        else:
            await ctx_or_interaction.send(error_text)
