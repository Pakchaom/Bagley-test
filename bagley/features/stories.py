"""bagley/features/stories.py — เล่าเรื่อง (คลิป YouTube หรือเรื่องจาก AI)"""
import discord
from discord import ui
from discord.ext import commands
from typing import Optional

from bagley.ai import persona
from bagley.core import state
from bagley.core.app import client
from bagley.core.logutil import print
from bagley.music.player import play_song
from bagley.voice.tts import bagley_speak_wait


# ============================================================
# 📖 ระบบเล่าเรื่อง (แบ็คลี่หาเรื่องมาเล่าให้ฟังได้)
# ============================================================
async def _send_long_text(destination, text: str, limit: int = 1900):
    """ส่งข้อความยาวๆ แบบเต็มไม่ตัดทอนเลย โดยหั่นเป็นหลายข้อความถ้าเกิน limit ตัวอักษร
    (Discord จำกัดข้อความละไม่เกิน 2000 ตัวอักษร) ใช้ตอนแบ็คลี่ต้องเล่าเรื่องยาวๆ เป็นตัวหนังสือ
    เหมือนตอนหาข้อมูล/อธิบายอะไรยาวๆ ให้ ไม่ต้องกลัวเนื้อเรื่องขาดหาย"""
    text = (text or "").strip()
    if not text:
        return

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit * 0.5:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)

    for chunk in chunks:
        if chunk:
            await destination.send(chunk)


async def _generate_story_text(topic: Optional[str]) -> str:
    """ให้ AI (เปิดความสามารถค้นเว็บจริงด้วย Google Search) หาเรื่องเล่าจริงจากเว็บมาปรับสำนวน
    เป็นน้ำเสียงของแบ็คลี่ แล้วคืนค่าเป็นเนื้อเรื่องพร้อมเล่า"""
    if topic:
        topic_line = f"หัวข้อ/แนวเรื่องที่ผู้ใช้ขอมา: {topic}"
    else:
        topic_line = (
            "ผู้ใช้ไม่ได้ระบุหัวข้อมา ให้เลือกแนวเรื่องเล่าที่น่าสนใจเอง "
            "(เช่น เรื่องผี เรื่องลึกลับ เรื่องเล่าสยองขวัญ หรือเรื่องเล่าตลกขำขัน)"
        )

    prompt = f"""
    {persona.BRIEF}
สถานการณ์: คุณกำลังจะเล่าเรื่องให้เพื่อนๆ ฟังในห้องเสียงดิสคอร์ด
    {topic_line}

    ให้ค้นหาเรื่องเล่า/เหตุการณ์จริงจากเว็บมาก่อน แล้วเรียบเรียงใหม่เป็นสำนวนเล่าเรื่องของตัวเอง
    (ห้ามลอกข้อความต้นฉบับคำต่อคำ) เขียนเป็นเรื่องเล่าต่อเนื่อง มีบทนำ เนื้อเรื่อง และจุดจบที่ชัดเจน
    ความยาวพอเหมาะกับการเล่าปากเปล่า (ประมาณ 150-400 คำ)
    ใช้น้ำเสียงเป็นกันเอง ชวนติดตาม ลงท้ายประโยคด้วย 'ครับ' บ้างแบบเป็นธรรมชาติ (ไม่ต้องทุกประโยค)
    ตอบมาแค่เนื้อเรื่องที่จะใช้เล่าเท่านั้น ห้ามมีคำนำ/คำอธิบายอื่นปนมา ห้ามใส่หัวข้อหรือบูลเล็ตพอยต์
    """

    no_web = prompt.replace(
        "ให้ค้นหาเรื่องเล่า/เหตุการณ์จริงจากเว็บมาก่อน แล้วเรียบเรียงใหม่เป็นสำนวนเล่าเรื่องของตัวเอง",
        "เลือกเรื่องเล่า/ตำนานที่คุณรู้จักจริง (ห้ามแต่งเรื่องเท็จแล้วอ้างว่าเป็นเรื่องจริง ถ้าเป็นเรื่องแต่งให้บอกว่าเป็นเรื่องเล่า) แล้วเรียบเรียงใหม่เป็นสำนวนเล่าเรื่องของตัวเอง")
    response = await client.ask_with_search(prompt, fallback_prompt=no_web)
    return (response.text or "").strip()


class StoryChoiceView(ui.View):
    """ปุ่มให้เลือกว่าจะให้แบ็คลี่หาคลิปเรื่องเล่ามาเปิด หรือหาเรื่องเล่าจากเว็บมาเล่าเอง"""
    def __init__(self, ctx: commands.Context, topic: Optional[str]):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.topic = topic

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("ปุ่มนี้ไม่ใช่ของคุณนะครับ 😅", ephemeral=True)
            return False
        return True

    @ui.button(label="🎬 หาคลิปมาเปิดให้ฟัง", style=discord.ButtonStyle.primary)
    async def pick_clip(self, interaction: discord.Interaction, button: ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await _run_story_clip(self.ctx, self.topic, interaction)

    @ui.button(label="📖 หาเรื่องเล่าจากเว็บ", style=discord.ButtonStyle.secondary)
    async def pick_web_story(self, interaction: discord.Interaction, button: ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await _run_story_web(self.ctx, self.topic, interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def _run_story_clip(ctx: commands.Context, topic: Optional[str], interaction: Optional[discord.Interaction] = None):
    """โหมด 'หาคลิป': เข้าห้องเสียง (ถ้ายังไม่ได้เข้า) แล้วค้นหาคลิปเรื่องเล่าจาก YouTube มาเปิดให้ฟัง"""

    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            text = "คุณต้องเข้าห้องเสียงก่อนนะครับ ผมถึงจะเปิดคลิปเรื่องเล่าให้ฟังได้!"
            if interaction:
                await interaction.followup.send(text)
            else:
                await ctx.send(text)
            return

    search_query = f"{topic} เรื่องเล่า" if topic else "เรื่องเล่าสยองขวัญ ผี เรื่องจริง"

    text = f"เดี๋ยวผมหาคลิป **{search_query}** จาก YouTube มาเปิดให้ฟังเลยนะครับ"
    if interaction:
        await interaction.followup.send(text)
    else:
        await ctx.send(text)

    state.is_playing_music = True
    await play_song(ctx, search_query)


async def _run_story_web(ctx: commands.Context, topic: Optional[str], interaction: Optional[discord.Interaction] = None):
    """โหมด 'หาเรื่องเล่าจากเว็บ': ให้ AI ค้นเรื่องเล่ามา แล้วพูดในห้องเสียงแบบช้าลง (ถ้าอยู่ในห้องเสียง)
    ถ้าไม่มีห้องเสียงให้พูด ค่อยส่งเป็นข้อความเต็มๆ ในแชทแทน (ไม่ตัดทอน ไม่จำกัดความยาว) กันไม่ให้สแปมแชท
    ถ้าพูดในห้องเสียงได้อยู่แล้ว ก็จะส่งแค่ข้อความสั้นๆ บอกว่ากำลังเล่าให้ฟัง"""
    thinking_text = f"เดี๋ยวผมไปหาเรื่องเล่ามาก่อนนะครับ รอแป๊บ..." if not topic else f"เดี๋ยวผมไปหาเรื่องเล่าเกี่ยวกับ '{topic}' มาก่อนนะครับ รอแป๊บ..."
    if interaction:
        await interaction.followup.send(thinking_text)
    else:
        await ctx.send(thinking_text)

    try:
        story_text = await _generate_story_text(topic)
    except Exception as e:
        print(f"❌ [Story] หาเรื่องเล่าจากเว็บไม่สำเร็จ: {e}")
        story_text = ""

    if not story_text:
        await ctx.send("ขอโทษครับ วันนี้หาเรื่องมาเล่าไม่สำเร็จ ลองใหม่อีกทีได้มั้ยครับ")
        return

    can_speak = bool(ctx.guild.voice_client and ctx.guild.voice_client.is_connected())

    if can_speak:
        # 🐢 พูดช้าลงตอนเล่าเรื่อง ฟังง่ายกว่าปกติ และไม่ต้องส่งข้อความยาวๆ ซ้ำในแชท (กันสแปม)
        await ctx.send("📖 กำลังเล่าให้ฟังในห้องเสียงครับ...")
        await bagley_speak_wait(ctx.guild, story_text, rate="-15%")
    else:
        # ไม่มีห้องเสียงให้พูด ก็ส่งเนื้อเรื่องเต็มๆ ในแชทแทน (เหมือนตอนหาข้อมูลให้ ไม่ตัดทอน)
        await _send_long_text(ctx.channel, story_text)
