"""bagley/commands/fun.py — คำสั่งสนุกๆ: เล่าเรื่อง วาดรูป สุ่ม แบ่งทีม"""
import asyncio
import random
from discord import app_commands
from discord.ext import commands
from typing import Optional

from bagley.core import state
from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.features.stories import StoryChoiceView
from bagley.features.teams import TeamSplitView, _parse_item_list
from bagley.phrases import say
from bagley.services.images import generate_and_send_image
from bagley.voice.tts import bagley_speak


@bot.hybrid_command(
    name="tell_story",
    description="ให้แบ็คลี่เล่าเรื่อง (ผี/ลึกลับ/ตลก) ถามก่อนว่าเปิดคลิป YouTube หรือหาเรื่องจากเว็บมาเล่าเอง",
)
@app_commands.describe(topic="หัวข้อ/แนวเรื่อง (ถ้ามี) เช่น 'เรื่องผี' หรือ 'เรื่องตลก' ไม่ระบุ = แบ็คลี่เลือกเอง")
async def tell_story(ctx: commands.Context, *, topic: Optional[str] = None):
    view = StoryChoiceView(ctx, topic)
    prompt_text = "จะให้ผมหาคลิปเรื่องเล่ามาเปิดให้ฟัง หรือให้ผมหาเรื่องเล่าจากในเว็บมาเล่าเองดีครับ?"
    await ctx.send(prompt_text, view=view)


@bot.hybrid_command(name="imagine", description="สั่งให้แบ็คลี่วาดภาพจากจินตนาการและข้อความ")
@app_commands.describe(prompt="พิมพ์อธิบายภาพที่อยากให้แบ็คลี่วาดได้เลยครับ")
async def imagine(ctx: commands.Context, *, prompt: str):
    await ctx.defer()

    await generate_and_send_image(ctx, prompt)


@bot.hybrid_command(
    name="back",
    description="พาทุกคนที่แบ็คลี่แยกห้องออกไปตอนสุ่มทีม กลับมารวมกันที่ห้องเดิม (ใช้ได้เฉพาะคนที่ถูกแยกไปเท่านั้น)"
)
async def back_from_teams(ctx: commands.Context):

    if not ctx.guild:
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะในดิสคอร์ดเซิร์ฟเวอร์เท่านั้นครับ")

    session = state.active_team_splits.get(ctx.guild.id)
    if not session:
        return await ctx.send("❌ ตอนนี้ไม่มีการแยกห้องทีมที่แบ็คลี่จัดไว้อยู่เลยครับ")

    author_voice_channel_id = (
        ctx.author.voice.channel.id if ctx.author.voice and ctx.author.voice.channel else None
    )
    # 🔒 พิมพ์ back ได้เฉพาะจากห้องที่แบ็คลี่แยกออกไป หรือห้องที่แบ็คลี่รออยู่เท่านั้น
    allowed_channel_ids = set(session["team_channel_ids"]) | {session["origin_channel_id"]}
    if author_voice_channel_id not in allowed_channel_ids:
        return await ctx.send(
            "❌ ต้องอยู่ในห้องที่แบ็คลี่แยกออกไป หรือห้องที่แบ็คลี่รออยู่ ถึงจะสั่ง `back` ได้ครับ"
        )

    # 🔒 ใช้ได้เฉพาะคนที่ถูกแบ็คลี่แยกห้องออกไปตอนสุ่มทีมรอบนี้เท่านั้น
    if ctx.author.id not in session["moved_member_ids"]:
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะคนที่ถูกแบ็คลี่แยกห้องออกไปตอนสุ่มทีมเท่านั้นครับ")

    origin_channel = ctx.guild.get_channel(session["origin_channel_id"])
    if not origin_channel:
        state.active_team_splits.pop(ctx.guild.id, None)
        return await ctx.send("❌ ห้องเดิมหายไปแล้วครับ (อาจถูกลบ) เลยพากลับไม่ได้ ขอโทษด้วยนะครับ")

    state.is_moving_group = True  # 🔇 กันไม่ให้แบ็คลี่รายงานทีละคนตอนพากลับกันยกทีม
    moved_back = 0
    try:
        for member_id in list(session["moved_member_ids"]):
            member = ctx.guild.get_member(member_id)
            if member and member.voice and member.voice.channel and member.voice.channel.id in session["team_channel_ids"]:
                try:
                    await member.edit(voice_channel=origin_channel)
                    moved_back += 1
                except Exception as e:
                    print(f"❌ พา {member.display_name} กลับห้องเดิมไม่ได้: {e}")

        # 🧹 เก็บกวาดห้องทีมที่สร้างไว้ทิ้งทั้งหมด (จบรอบแล้ว ไม่ใช้ต่อ)
        for channel_id in session["team_channel_ids"]:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete(reason="จบรอบแยกห้องทีม - แบ็คลี่พาทุกคนกลับหมดแล้ว")
                except Exception as e:
                    print(f"❌ ลบห้องทีม {channel.name} ไม่ได้: {e}")
            if channel_id in state.created_party_channels:
                state.created_party_channels.remove(channel_id)
    finally:
        await asyncio.sleep(1)
        state.is_moving_group = False

    state.active_team_splits.pop(ctx.guild.id, None)

    # 🛡️ คืนค่าโหมดเฝ้าห้องกลับไปเป็นแบบที่ตั้งไว้ก่อนหน้ารอบแยกทีม (ถ้าเดิมปิดอยู่ก็ปิดคืนให้)
    state.room_guard_status[ctx.guild.id] = session.get("prev_guard_status", False)

    # 🚫 ไม่รายงานทีละคนว่าใครเข้ามาบ้าง พูดสรุปทีเดียวจบตามที่ขอเป๊ะ ๆ
    await ctx.send(say("back_from_teams") + " 🎉")

    if ctx.guild.voice_client:
        try:
            await bagley_speak(ctx.guild, say("back_from_teams"))
        except Exception as e:
            print(f"Back command speak error: {e}")


@bot.hybrid_command(name="split_team", description="สั่งให้แบ็คลี่สุ่มแบ่งทีมจากคนในห้องเสียงปัจจุบัน (แค่บอกผลในแชท ไม่ย้ายห้องใคร)")
@app_commands.describe(teams="จำนวนทีมที่ต้องการแบ่ง (ค่าเริ่มต้น 2 ทีม)")
async def split_team(ctx: commands.Context, teams: int = 2):
    # 🛡️ กันเคส AI Command Router ส่ง teams มาเป็น string (เช่น "3") แทนที่จะเป็น int
    try:
        teams = int(teams)
    except (TypeError, ValueError):
        return await ctx.send("❌ จำนวนทีมต้องเป็นตัวเลขนะครับ เช่น 2, 3, 4")

    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงก่อนนะครับ แบ็คลี่ถึงจะรู้ว่าจะสุ่มทีมจากห้องไหน!")

    if teams < 2:
        return await ctx.send("❌ ต้องแบ่งอย่างน้อย 2 ทีมนะครับ!")

    voice_channel = ctx.author.voice.channel
    members = [m for m in voice_channel.members if not m.bot]

    if len(members) < teams:
        return await ctx.send(f"❌ ในห้องเสียง **{voice_channel.name}** มีแค่ {len(members)} คน แต่จะแบ่ง {teams} ทีมไม่พอครับ!")

    view = TeamSplitView(ctx.author, members, teams, origin_channel=voice_channel)
    await ctx.send(
        f"🎲 พร้อมสุ่มทีมจากห้อง **{voice_channel.name}** แล้วครับ! (ตอนนี้เลือกไว้ทุกคน {len(members)} คน แบ่งเป็น {teams} ทีม)\n"
        f"ถ้ามีใครไม่ได้เล่นด้วย ติ๊กเลือกใหม่ในเมนูด้านล่างเพื่อถอดออกได้เลยครับ\n"
        f"แล้วเลือกโหมด: กด **'🎲 สุ่มทีเดียว (แยกทีมให้เลย)'** ถ้าอยากรู้ผลรวดเดียว หรือกด **'🎯 สุ่มทีละคน (ตื่นเต้นกว่า)'** "
        f"ถ้าอยากให้แบ็คลี่จับสลากทีละคนให้ลุ้นกันไปทีละฝั่ง!",
        view=view
    )

    # 🔊 พูดออกไมค์ด้วยว่าพร้อมสุ่มทีมแล้ว ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว
    if ctx.guild.voice_client:
        try:
            await bagley_speak(
                ctx.guild,
                f"พร้อมสุ่มทีมจากห้อง {voice_channel.name} แล้วครับ เลือกโหมดในแชทได้เลย"
            )
        except Exception as e:
            print(f"Split team invite speak error: {e}")


@bot.hybrid_command(
    name="random",
    description="สุ่มอะไรก็ได้จากรายการที่พิมพ์มา เช่น ชื่อแมพ ชื่อคน หรือเลข (คั่นด้วย , หรือขึ้นบรรทัดใหม่)"
)
@app_commands.describe(
    items="รายการที่จะสุ่ม คั่นด้วยจุลภาค (,) เช่น Bind, Haven, Ascent, Icebox หรือ 1, 2, 3, 4, 5",
    count="จำนวนที่อยากให้สุ่ม (ค่าเริ่มต้น 1)"
)
async def random_pick(ctx: commands.Context, items: str, count: int = 1):
    # 🛡️ กันเคส AI Command Router ส่ง count มาเป็น string (เช่น "2") แทนที่จะเป็น int
    try:
        count = int(count)
    except (TypeError, ValueError):
        return await ctx.send("❌ จำนวนที่จะสุ่มต้องเป็นตัวเลขนะครับ เช่น 1, 2, 3")

    item_list = _parse_item_list(items)

    if len(item_list) < 2:
        return await ctx.send(
            "❌ พิมพ์รายการมาหลาย ๆ อันหน่อยครับ คั่นด้วยจุลภาค (,) หรือขึ้นบรรทัดใหม่ก็ได้ "
            "เช่น `/random items: Bind, Haven, Ascent, Icebox` หรือจะสุ่มชื่อคน สุ่มเลข ก็ใส่รายการมาได้เลยครับ"
        )

    count = max(1, min(count, len(item_list)))

    if count >= len(item_list):
        picked = item_list[:]
        random.shuffle(picked)
    else:
        picked = random.sample(item_list, count)

    if len(picked) == 1:
        result_text = f"🎲 สุ่มจากทั้งหมด {len(item_list)} รายการที่ให้มา... ได้ **{picked[0]}** ครับ!"
    else:
        lines = "\n".join(f"{i}. {m}" for i, m in enumerate(picked, 1))
        result_text = f"🎲 สุ่มจากทั้งหมด {len(item_list)} รายการที่ให้มา ได้ {len(picked)} อย่างครับ!\n{lines}"

    await ctx.send(result_text)

    if ctx.guild:
        try:
            await bagley_speak(ctx.guild, say("random_result", picked=', '.join(picked)))
        except Exception as e:
            print(f"Random pick speak error: {e}")
