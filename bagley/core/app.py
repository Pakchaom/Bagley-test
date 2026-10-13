"""bagley/core/app.py — ตัวบอท Discord, intents และตัวเชื่อม AI (สร้างครั้งเดียว ทุกโมดูล import จากที่นี่)"""
import discord
from discord.ext import commands

from bagley.ai.provider import ai as client  # noqa: F401 - ชื่อ `client` ที่โค้ดเดิมใช้เรียก AI

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guild_messages = True
intents.dm_messages = True
# 🎮 ต้องเปิดสวิตช์ PRESENCE INTENT ใน Discord Developer Portal ด้วย ไม่งั้นจะเชื่อมต่อไม่ได้
intents.presences = True

# max_messages ลดจากค่าเริ่มต้น 1000 -> 200 ประหยัด RAM (บอทไม่ได้ใช้แคชข้อความเก่า)
bot = commands.Bot(command_prefix="!", intents=intents, max_messages=200)
tree = bot.tree
