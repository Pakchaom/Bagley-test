# ============================================================
# 🤖 AI Command Router
# ============================================================
# วางไฟล์นี้ไว้ข้าง bot.py แล้ว import เข้าไป หรือจะ copy โค้ดทั้งหมด
# แปะต่อท้ายในไฟล์ bot.py เลยก็ได้ (ต้องอยู่หลังจุดที่ประกาศ `bot`, `client`,
# `find_member_by_name` และคำสั่งทุกตัวถูกลงทะเบียนแล้ว)
#
# วิธีทำงาน:
#   1. สแกน bot.commands (เฉพาะ HybridCommand) แล้วสร้าง Gemini FunctionDeclaration
#      ให้อัตโนมัติจาก name / description / parameters ของแต่ละคำสั่ง
#   2. ส่งข้อความผู้ใช้ให้ Gemini เลือกว่าควรเรียกคำสั่งไหน (หรือไม่เรียกเลย)
#   3. พารามิเตอร์ที่เป็น discord.Member / VoiceChannel / TextChannel / Role
#      จะถูก "resolve" จากชื่อ/ข้อความดิบ กลับเป็น object จริงผ่านตัวช่วยที่มีอยู่แล้ว
#      ในบอทคุณ (find_member_by_name) กันไม่ให้ AI เดา ID เอง
#   4. เรียกคำสั่งจริงผ่าน ctx.invoke(...) เหมือนผู้ใช้พิมพ์ /คำสั่งเอง
#
# หมายเหตุสำคัญ:
#   - คำสั่งที่ประกาศด้วย @bot.tree.command ล้วน (ไม่ใช่ hybrid_command) เช่น
#     shutdown, report_voice, view_logs, forget, invite_voice, remind
#     จะไม่ถูกสแกน เพราะรับพารามิเตอร์เป็น discord.Interaction ตรง ๆ
#     เรียกผ่าน ctx.invoke ไม่ได้ ถ้าอยากให้ AI สั่งได้ด้วยต้องแปลงเป็น
#     hybrid_command ก่อน (บอกได้ถ้าอยากให้ช่วยแปลง)
#   - คำสั่งอันตราย/สงวนสิทธิ์ ใส่ชื่อไว้ใน AI_ROUTER_EXCLUDED_COMMANDS
#     เพื่อกันไม่ให้ AI เรียกเองโดยไม่ตั้งใจ (ยังสั่งตรงผ่าน /คำสั่ง ได้ปกติ)
# ============================================================

import re as regex_lib
import discord
from discord.ext import commands
from google.genai import types as genai_types

# --------------------------------------------------------------
# ตั้งค่า: คำสั่งที่ไม่ต้องการให้ AI เรียกเองจากแชทธรรมดา
# (ยังคงใช้งานได้ปกติผ่าน /คำสั่ง ตรง ๆ เหมือนเดิมทุกประการ)
# --------------------------------------------------------------
AI_ROUTER_EXCLUDED_COMMANDS = {
    "shutdown", "update_bot", "sync", "sys_cleanup",
    "reg_config", "set_alert", "set_yt_channel",
}

# แคช tool schema ไว้ ไม่ต้องสร้างใหม่ทุกครั้งที่มีข้อความเข้ามา
_COMMAND_TOOLS_CACHE = None


def _build_command_tools(bot: commands.Bot):
    """สแกนคำสั่ง hybrid_command ทั้งหมด แล้วแปลงเป็น Gemini FunctionDeclaration อัตโนมัติ"""
    declarations = []

    for cmd in bot.commands:
        if cmd.name in AI_ROUTER_EXCLUDED_COMMANDS:
            continue
        if not isinstance(cmd, commands.HybridCommand):
            # ข้าม tree.command ล้วน ๆ (รับ interaction ตรง ๆ เรียกผ่าน ctx.invoke ไม่ได้)
            continue

        properties = {}
        required = []

        for pname, param in cmd.clean_params.items():
            annotation = param.annotation
            base_desc = f"พารามิเตอร์ '{pname}' ของคำสั่ง /{cmd.name}"

            if annotation in (discord.Member, discord.User):
                desc = (f"{base_desc} — ชื่อเล่น/ชื่อดิสคอร์ดของสมาชิกเป้าหมาย "
                         f"ให้ใส่ตามที่ผู้ใช้พูดมาเป๊ะๆ ไม่ต้องแปลงเป็น ID เอง")
            elif annotation in (discord.VoiceChannel, discord.TextChannel):
                desc = f"{base_desc} — ชื่อห้องตามที่ผู้ใช้พูดถึง (ไม่ต้องแปลงเป็น ID)"
            elif annotation in (discord.Role,):
                desc = f"{base_desc} — ชื่อยศ/role ตามที่ผู้ใช้พูดถึง"
            else:
                desc = base_desc

            properties[pname] = {"type": "string", "description": desc}

            if param.default is param.empty:
                required.append(pname)

        declarations.append(
            genai_types.FunctionDeclaration(
                name=cmd.name,
                description=(cmd.description or cmd.help or cmd.name)[:1000],
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            )
        )

    return declarations


def get_command_tools(bot: commands.Bot):
    global _COMMAND_TOOLS_CACHE
    if _COMMAND_TOOLS_CACHE is None:
        _COMMAND_TOOLS_CACHE = [
            genai_types.Tool(function_declarations=_build_command_tools(bot))
        ]
    return _COMMAND_TOOLS_CACHE


def invalidate_command_tools_cache():
    """เรียกฟังก์ชันนี้ถ้ามีการเพิ่ม/ลบคำสั่งตอนรันไทม์ (ปกติไม่จำเป็น)"""
    global _COMMAND_TOOLS_CACHE
    _COMMAND_TOOLS_CACHE = None


# --------------------------------------------------------------
# ตัว resolve พารามิเตอร์ชนิดพิเศษ (Member / VoiceChannel / TextChannel / Role)
# จากข้อความดิบที่ AI แกะมาได้ ให้กลายเป็น object จริงของ Discord
# --------------------------------------------------------------

async def _resolve_member_param(message, raw_value: str, find_member_by_name):
    if not raw_value or not message.guild:
        return None

    id_match = regex_lib.search(r"\d{15,20}", raw_value)
    if id_match:
        member = message.guild.get_member(int(id_match.group()))
        if member:
            return member

    prefer_channel = None
    if getattr(message.author, "voice", None) and message.author.voice.channel:
        prefer_channel = message.author.voice.channel
    elif message.guild.voice_client:
        prefer_channel = message.guild.voice_client.channel

    exclude_ids = {message.guild.me.id} if message.guild.me else set()
    return find_member_by_name(
        message.guild,
        raw_value.strip().lower(),
        exclude_ids=exclude_ids,
        prefer_channel=prefer_channel,
    )


async def _resolve_voice_channel_param(message, raw_value: str, find_member_by_name=None):
    if not message.guild or not raw_value:
        return None
    target = raw_value.strip().lower()
    exact = discord.utils.find(lambda c: c.name.lower() == target, message.guild.voice_channels)
    if exact:
        return exact
    return discord.utils.find(lambda c: target in c.name.lower(), message.guild.voice_channels)


async def _resolve_text_channel_param(message, raw_value: str, find_member_by_name=None):
    if not message.guild or not raw_value:
        return None
    target = raw_value.strip().lower()
    exact = discord.utils.find(lambda c: c.name.lower() == target, message.guild.text_channels)
    if exact:
        return exact
    return discord.utils.find(lambda c: target in c.name.lower(), message.guild.text_channels)


async def _resolve_role_param(message, raw_value: str, find_member_by_name=None):
    if not message.guild or not raw_value:
        return None
    target = raw_value.strip().lower()
    return discord.utils.find(lambda r: target in r.name.lower(), message.guild.roles)


_PARAM_RESOLVERS = {
    discord.Member: _resolve_member_param,
    discord.User: _resolve_member_param,  # /forget ฯลฯ ใช้ discord.User แต่ในกิลด์ resolve เหมือน Member ได้
    discord.VoiceChannel: _resolve_voice_channel_param,
    discord.TextChannel: _resolve_text_channel_param,
    discord.Role: _resolve_role_param,
}


# --------------------------------------------------------------
# ฟังก์ชันหลัก: เรียกใช้จาก on_message
# --------------------------------------------------------------

async def ai_route_and_execute(message, bot: commands.Bot, client, find_member_by_name, model="gemini-3.1-flash-lite") -> bool:
    """
    ให้ AI พิจารณาว่าข้อความนี้ควรสั่งคำสั่งไหนของบอท (ถ้ามี)

    Returns:
        True  -> ตีความเป็นคำสั่งแล้ว (ไม่ว่าจะสั่งสำเร็จ หรือหา entity ไม่เจอแล้วแจ้งผู้ใช้ไปแล้ว)
                 ผู้เรียกควร `return` ทันทีเพื่อไม่ให้ไหลลงไปทำ free-chat ต่อ
        False -> ไม่ใช่คำสั่ง ปล่อยให้ไหลไปทำงานส่วนอื่นต่อ (เช่น free chat / teach memory)
    """
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=(
                "คุณคือระบบแยกแยะเจตนาให้บอทดิสคอร์ดชื่อ 'แบ็คลี่'\n"
                f'ข้อความจากผู้ใช้: "{message.content}"\n\n'
                "ถ้าข้อความนี้ต้องการให้บอททำงานบางอย่าง (เช่น เปิดเพลง ย้ายห้อง เตะคน ปิดไมค์ ฯลฯ) "
                "ให้เรียกฟังก์ชันที่ตรงกับความต้องการมากที่สุดเพียงฟังก์ชันเดียว "
                "และกรอกพารามิเตอร์ตามคำพูดของผู้ใช้แบบคงคำเดิมไว้ (ไม่ต้องแปล ไม่ต้องสรุปใหม่)\n"
                "ถ้าข้อความนี้เป็นแค่การพูดคุยทั่วไป ไม่ได้ต้องการให้ทำอะไรเป็นชิ้นเป็นอัน ห้ามเรียกฟังก์ชันใดๆ เลย"
            ),
            config=genai_types.GenerateContentConfig(
                tools=get_command_tools(bot),
                tool_config=genai_types.ToolConfig(
                    function_calling_config=genai_types.FunctionCallingConfig(mode="AUTO")
                ),
            ),
        )

        function_call = None
        for part in response.candidates[0].content.parts:
            if getattr(part, "function_call", None):
                function_call = part.function_call
                break

        if not function_call:
            return False

        cmd = bot.get_command(function_call.name)
        if not cmd or not isinstance(cmd, commands.HybridCommand):
            return False

        raw_args = dict(function_call.args or {})
        resolved_kwargs = {}

        for pname, param in cmd.clean_params.items():
            if pname not in raw_args:
                continue

            resolver = _PARAM_RESOLVERS.get(param.annotation)
            if resolver:
                resolved = await resolver(message, str(raw_args[pname]), find_member_by_name)
                if resolved is None and param.default is param.empty:
                    await message.channel.send(
                        f"❌ แบ็คลี่หา '{raw_args[pname]}' ไม่เจอเลยครับ ลองพิมพ์ให้ชัดกว่านี้ได้มั้ยครับ"
                    )
                    return True
                resolved_kwargs[pname] = resolved
            else:
                resolved_kwargs[pname] = raw_args[pname]

        ctx = await bot.get_context(message)
        print(f"🤖 [AI Router] ตีความข้อความเป็นคำสั่ง /{cmd.name} args={resolved_kwargs}")
        await ctx.invoke(cmd, **resolved_kwargs)
        return True

    except Exception as e:
        print(f"⚠️ [AI Router] ทำงานผิดพลาด: {e}")
        return False
