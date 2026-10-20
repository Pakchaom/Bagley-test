"""bagley/commands/games.py — คำสั่งเกมในแชท: /uno /uno_end /xo /hangman /hangman_end /wordle /wordle_end /rps  (แบ็คลี่ร่วมเล่นเป็นผู้เล่นได้)"""
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bagley.core.app import bot
from bagley.features.games import hangman as hangman_game, rps as rps_game, uno as uno_game, wordle as wordle_game, xo as xo_game


@bot.hybrid_command(name="uno", description="เปิดห้องเล่น UNO ในแชท (ชวนเพื่อนมากดเข้าร่วม และให้แบ็คลี่ร่วมเล่นด้วยได้)")
async def uno_cmd(ctx: commands.Context):
    if not ctx.guild:
        return await ctx.send("❌ เล่น UNO ได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")
    await uno_game.open_uno_lobby(ctx.channel, ctx.author, bot.user.id, send=ctx.send)


@bot.hybrid_command(name="uno_end", description="จบเกม/ปิดห้อง UNO ที่ค้างอยู่ในช่องนี้ (เจ้าของห้องหรือแอดมินเท่านั้น)")
async def uno_end(ctx: commands.Context):
    session = uno_game.get_session(ctx.channel.id)
    if session is None:
        return await ctx.send("ช่องนี้ไม่มีห้อง UNO เปิดอยู่ครับ")
    perms = getattr(ctx.author, "guild_permissions", None)
    if ctx.author.id != session.host.id and not (perms and perms.manage_messages):
        return await ctx.send("❌ เฉพาะเจ้าของห้องหรือแอดมินที่จบเกมได้ครับ")
    await ctx.send("🛑 จบเกม UNO ให้แล้วครับ")
    await session.end_by(ctx.author)


@bot.hybrid_command(name="xo", description="เล่น XO กับแบ็คลี่ (เลือกความเก่งได้) หรือท้าเพื่อนสู้กันในแชท")
@app_commands.describe(opponent="ท้าเพื่อนคนไหน (ไม่ระบุ = เล่นกับแบ็คลี่)",
                       level="ความเก่งของแบ็คลี่ (ใช้เมื่อเล่นกับแบ็คลี่)")
async def xo_cmd(ctx: commands.Context, opponent: Optional[discord.Member] = None,
                 level: Literal["ง่าย", "กลาง", "ยาก"] = "กลาง"):
    if not ctx.guild:
        return await ctx.send("❌ เล่น XO ได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")
    await xo_game.start_xo(ctx.send, ctx.author, opponent, level)


def _can_end(ctx: commands.Context, host) -> bool:
    perms = getattr(ctx.author, "guild_permissions", None)
    return ctx.author.id == host.id or bool(perms and perms.manage_messages)


@bot.hybrid_command(name="hangman", description="เล่น Hangman ทายคำลับ ช่วยกันทั้งช่อง (แบ็คลี่ช่วยเดา/ใบ้ได้)")
@app_commands.describe(language="ภาษาของคำลับ (ไม่ระบุ = อังกฤษ)")
async def hangman_cmd(ctx: commands.Context, language: Literal["อังกฤษ", "ไทย"] = "อังกฤษ"):
    if not ctx.guild:
        return await ctx.send("❌ เล่น Hangman ได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")
    await hangman_game.start_hangman(ctx.send, ctx.channel.id, ctx.author, hangman_game.norm_lang(language))


@bot.hybrid_command(name="hangman_end", description="จบเกม Hangman ที่ค้างอยู่ในช่องนี้ (คนเปิดเกมหรือแอดมินเท่านั้น)")
async def hangman_end(ctx: commands.Context):
    view = hangman_game.get_active(ctx.channel.id)
    if view is None:
        return await ctx.send("ช่องนี้ไม่มี Hangman เปิดอยู่ครับ")
    if not _can_end(ctx, view.host):
        return await ctx.send("❌ เฉพาะคนเปิดเกมหรือแอดมินที่จบเกมได้ครับ")
    await hangman_game.force_end(ctx.channel.id, ctx.author.display_name)
    await ctx.send("🛑 จบเกม Hangman ให้แล้วครับ")


@bot.hybrid_command(name="wordle", description="เกมทายคำอังกฤษ 5 ตัวแบบ Wordle ช่วยกันทายทั้งช่อง (แบ็คลี่ช่วยเดาได้)")
async def wordle_cmd(ctx: commands.Context):
    if not ctx.guild:
        return await ctx.send("❌ เล่นเกมทายคำได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")
    await wordle_game.start_wordle(ctx.send, ctx.channel.id, ctx.author)


@bot.hybrid_command(name="wordle_end", description="จบเกมทายคำที่ค้างอยู่ในช่องนี้ (คนเปิดเกมหรือแอดมินเท่านั้น)")
async def wordle_end(ctx: commands.Context):
    view = wordle_game.get_active(ctx.channel.id)
    if view is None:
        return await ctx.send("ช่องนี้ไม่มีเกมทายคำเปิดอยู่ครับ")
    if not _can_end(ctx, view.host):
        return await ctx.send("❌ เฉพาะคนเปิดเกมหรือแอดมินที่จบเกมได้ครับ")
    await wordle_game.force_end(ctx.channel.id, ctx.author.display_name)
    await ctx.send("🛑 จบเกมทายคำให้แล้วครับ")


@bot.hybrid_command(name="rps", description="เป่ายิ้งฉุบกับแบ็คลี่ เก็บแต้มใครชนะก่อนเป็นผู้ชนะ")
@app_commands.describe(best_of="จำนวนตาสูงสุด เช่น 3 = ชนะก่อน 2 ตา (1/3/5/7)",
                       level="ความเก่งของแบ็คลี่ (ยาก = จับทางคุณได้บ้าง)")
async def rps_cmd(ctx: commands.Context, best_of: int = 3, level: Literal["ง่าย", "ยาก"] = "ยาก"):
    if not ctx.guild:
        return await ctx.send("❌ เล่นเป่ายิ้งฉุบได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")
    best_of = min(rps_game.BEST_OF, key=lambda b: abs(b - best_of))
    await rps_game.start_rps(ctx.send, ctx.author, best_of, level)
