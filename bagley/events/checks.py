"""bagley/events/checks.py — ด่านตรวจสิทธิ์ก่อนทุกคำสั่ง (แบน / โหมดสตรีม)"""
import discord
from discord.ext import commands

from bagley.core.app import bot
from bagley.core.security import is_stream_authorized, is_stream_mode_on, is_user_blocked
from bagley.phrases import say


# 🚫 ดักคำสั่ง slash (/) ทั้งหมดตั้งแต่ก่อนจะรันจริง ถ้าคนนั้นโดนแบนคำสั่งอยู่ ให้ตอบปฏิเสธแทน
async def _bagley_tree_interaction_check(interaction: discord.Interaction) -> bool:
    if is_user_blocked(str(interaction.user.id)):
        try:
            await interaction.response.send_message(
                f"{interaction.user.mention} " + say("blocked_cmd") + " 🙅‍♂️",
                ephemeral=True
            )
        except Exception:
            pass
        return False

    # 🎥 [โหมดสตรีม] ถ้ากิลด์นี้เปิดโหมดสตรีมอยู่ รับคำสั่งเฉพาะเจ้าของบอท/คนที่กำลังสตรีมเท่านั้น
    if (
        interaction.guild is not None
        and is_stream_mode_on(interaction.guild.id)
        and not is_stream_authorized(interaction.user, interaction.guild)
    ):
        try:
            await interaction.response.send_message(
                "🎥 " + say("stream_locked"),
                ephemeral=True
            )
        except Exception:
            pass
        return False

    return True


bot.tree.interaction_check = _bagley_tree_interaction_check


# 🎥 [โหมดสตรีม] เช็คสิทธิ์แบบเดียวกันนี้กับคำสั่งที่สั่งผ่านข้อความ (prefix "!"/hybrid command ทาง
# ข้อความ) ด้วย — ครอบคลุมทุกคำสั่งของบอทโดยอัตโนมัติ ไม่ต้องไปแก้ทีละคำสั่ง
@bot.check
async def _bagley_stream_mode_command_check(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return True
    if not is_stream_mode_on(ctx.guild.id):
        return True
    return is_stream_authorized(ctx.author, ctx.guild)
