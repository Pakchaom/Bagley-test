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
    # 🔒 เพิ่มคำสั่งที่จำกัดสิทธิ์เฉพาะทีมพัฒนา (ALLOWED_TEACH_USERS) / Developer Only
    # เหตุผล: คนทั่วไปพูดคำที่ดูใกล้เคียง (เช่น "บอก...หน่อย", "ฝันดี...") แล้วโดน AI Router
    # ตีความมั่วเป็นคำสั่งพวกนี้ ผลคือได้แต่ข้อความ [ACCESS DENIED] แบบงงๆ ทั้งที่ผู้ใช้ไม่ได้
    # ตั้งใจจะสั่งคำสั่งระดับนี้เลย ตัดออกจาก AI Router ไปเลยดีกว่า (ยังสั่งตรงผ่าน /คำสั่ง ได้ปกติ
    # สำหรับคนที่มีสิทธิ์จริง)
    "teach", "unteach", "list_teach", "view_logs",
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
                desc = (f"{base_desc} — ชื่อห้องตามที่ผู้ใช้พูดถึง (ไม่ต้องแปลงเป็น ID) "
                         f"ถ้าผู้ใช้พูดว่า 'ห้องนี้', 'ตรงนี้', 'ที่นี่' หรือคำใกล้เคียงที่หมายถึง "
                         f"ห้องเสียงที่ตัวเองอยู่อยู่แล้ว ให้ใส่คำนั้นตามที่พูดมาเป๊ะๆ ไม่ต้องเดาชื่อห้องเอง")
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


# คำที่ผู้ใช้มักพูดแทน "ห้องเสียงที่ตัวเองอยู่ตอนนี้" (ไม่ใช่ชื่อห้องจริง ๆ)
# ถ้า AI แกะพารามิเตอร์มาได้ตรงกับคำเหล่านี้ ให้ตีความเป็นห้องที่ผู้พูดอยู่ตอนนี้เลย
# ไม่ต้องไปหาห้องที่ชื่อ "ห้องนี้" ในเซิร์ฟเวอร์ (ซึ่งไม่มีอยู่จริง)
_CURRENT_ROOM_KEYWORDS = (
    "ห้องนี้", "ห้องเดียวกัน", "ห้องเดียวกับผม", "ห้องเดียวกับฉัน", "ห้องเดียวกับเรา",
    "ตรงนี้", "ที่นี่", "มาที่นี่", "ห้องปัจจุบัน", "ห้องที่ผมอยู่", "ห้องที่ฉันอยู่",
    "this room", "this channel", "here",
)


async def _resolve_voice_channel_param(message, raw_value: str, find_member_by_name=None):
    if not message.guild or not raw_value:
        return None
    target = raw_value.strip().lower()

    # เข้าใจ "ห้องนี้ / ตรงนี้ / ที่นี่" ฯลฯ ว่าหมายถึงห้องเสียงที่ผู้พูดอยู่ตอนนี้
    if any(keyword in target for keyword in _CURRENT_ROOM_KEYWORDS):
        author_voice = getattr(message.author, "voice", None)
        if author_voice and author_voice.channel:
            return author_voice.channel
        # ถ้าผู้พูดไม่ได้อยู่ในห้องเสียงเลย ให้ลองใช้ห้องที่บอทอยู่ตอนนี้แทน
        voice_client = message.guild.voice_client
        if voice_client and voice_client.channel:
            return voice_client.channel
        return None

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

def _looks_like_personal_reminder(text: str) -> bool:
    """เช็คว่าข้อความนี้น่าจะเป็นรูปแบบ 'เตือนฉันตอน...' / 'เตือน @เพื่อน ตอน...' ที่ควรปล่อยให้ระบบ
    เตือนตัวเอง/เพื่อน (reminders) ของ bot.py จัดการเอง แทนที่จะให้ AI Router เดามาเรียก /remind แทน

    เหตุผล: /remind เก็บลง 'schedules' (ตารางนัด) ซึ่งเดิม AI ชอบทายวันที่มาไม่ตรง (เช่นใส่คำว่า
    'วันนี้' ดิบๆ) แล้วยังทำงานคนละแบบกับระบบเตือนตัวเอง/เพื่อนที่มีลูปเช็คทุกนาทีและวาร์ปเข้าห้อง
    เสียงมาเตือนจริง (bagley_hijack_alert) ทำให้สองระบบชนกันและพฤติกรรมไม่สม่ำเสมอ
    เงื่อนไขตรงนี้ต้องตรงกับเงื่อนไขในบล็อก 'ส่วนที่ 2' ของ bot.py เป๊ะๆ (มีคำว่า 'เตือน' และมีคำว่า
    'ตอน' หรือ 'เวลา') เพื่อให้แน่ใจว่าข้อความที่ตกไปให้ระบบเดิมจัดการ จะไม่ถูก AI Router แย่งไปก่อน"""
    lowered = text.lower()
    return "เตือน" in lowered and ("ตอน" in lowered or "เวลา" in lowered)


async def ai_route_and_execute(message, bot: commands.Bot, client, find_member_by_name, model="gemini-3.1-flash-lite") -> bool:
    """
    ให้ AI พิจารณาว่าข้อความนี้ควรสั่งคำสั่งไหนของบอท (ถ้ามี)

    Returns:
        True  -> ตีความเป็นคำสั่งแล้ว (ไม่ว่าจะสั่งสำเร็จ หรือหา entity ไม่เจอแล้วแจ้งผู้ใช้ไปแล้ว)
                 ผู้เรียกควร `return` ทันทีเพื่อไม่ให้ไหลลงไปทำ free-chat ต่อ
        False -> ไม่ใช่คำสั่ง ปล่อยให้ไหลไปทำงานส่วนอื่นต่อ (เช่น free chat / teach memory / ระบบเตือนตัวเอง-เพื่อน)
    """
    # 🛡️ กันไม่ให้ AI Router แย่งข้อความแบบ "เตือนฉันตอน.../เตือน @เพื่อน ตอน..." ไปเรียก /remind
    # ปล่อยให้ตกไปใช้ระบบเตือนตัวเอง/เพื่อนเดิมใน bot.py แทน (ส่วนที่ 2) ซึ่งทำงานถูกต้องกว่าและ
    # วาร์ปเข้าห้องเสียงมาเตือนจริงแล้ว (ผ่าน bagley_hijack_alert)
    if _looks_like_personal_reminder(message.content):
        return False

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=(
                "คุณคือระบบแยกแยะเจตนาให้บอทดิสคอร์ดชื่อ 'แบ็คลี่'\n"
                f'ข้อความจากผู้ใช้: "{message.content}"\n\n'
                "ให้เรียกฟังก์ชันก็ต่อเมื่อข้อความเป็น 'คำสั่งตรงตัว' ที่ต้องการให้บอททำงานบางอย่างจริงๆ "
                "(เช่น เปิดเพลง ย้ายห้อง เตะคน ปิดไมค์ ตั้งนาฬิกาปลุกที่บอกเวลามาชัดเจน ฯลฯ) "
                "และพารามิเตอร์ที่จำเป็น 'ต้องปรากฏอยู่ในข้อความจริงๆ' เท่านั้น\n\n"
                "❌ ห้ามเรียกฟังก์ชันเด็ดขาดในกรณีต่อไปนี้ (นี่คือสาเหตุหลักที่ทำให้ตีความผิดบ่อย ให้ระวังเป็นพิเศษ):\n"
                "  1. ข้อความเป็นคำอวยพร/ความรู้สึก/คำทักทาย/มุขตลก เช่น 'อวยพรให้ X ฝันดีด้วย', "
                "'บอก X ว่าฝันดีหน่อย', 'สวัสดี', 'เก่งมากเลย' — พวกนี้คือให้บอท 'พูดคุยตอบธรรมดา' "
                "ไม่ใช่คำสั่งเชิงระบบ (ไม่ใช่ /alarm ไม่ใช่ /remind ไม่ใช่ /teach) ถึงจะมีคำว่า 'ฝันดี', "
                "'ปลุก', 'เตือน' ปนอยู่ก็ตาม ถ้าไม่มีการระบุเวลา/การกระทำเชิงระบบที่ชัดเจน ให้ถือเป็นแชทธรรมดา\n"
                "  2. พารามิเตอร์ที่จำเป็น (เช่น เวลา, ชื่อห้อง) ไม่ได้ถูกพูดออกมาตรงๆในข้อความ "
                "ห้ามคิด/เดา/กุค่าขึ้นมาเองเด็ดขาด (เช่น ผู้ใช้ไม่ได้พูดเวลาเลย ห้ามใส่เวลาอะไรก็ได้ลงไปเอง) "
                "ถ้าจำเป็นต้องเดาค่าพารามิเตอร์ใดๆ ให้ถือว่าไม่ใช่คำสั่ง แล้วไม่เรียกฟังก์ชัน\n"
                "  3. ไม่มั่นใจว่าเป็นคำสั่งจริงหรือแค่คุยเล่น — ให้เอียงไปทาง 'ไม่เรียกฟังก์ชัน' เป็นค่าเริ่มต้นเสมอ\n\n"
                "ถ้าเรียกฟังก์ชัน ให้กรอกพารามิเตอร์ตามคำพูดของผู้ใช้แบบคงคำเดิมไว้เป๊ะๆ (ไม่ต้องแปล ไม่ต้องสรุปใหม่ "
                "ไม่ต้องเติมค่าที่ไม่ได้พูดมา)"
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

        # 🛡️ กันโมเดล hallucinate ค่าพารามิเตอร์ขึ้นมาเอง (เช่นกุเวลา '22:00' ที่ผู้ใช้ไม่ได้พูดถึงเลย)
        # เช็คว่าค่าที่ AI แกะมาได้ 'มีอยู่จริง' ในข้อความดิบของผู้ใช้ (ตัดช่องว่างเทียบแบบไม่สนตัวพิมพ์)
        # ถ้าค่าไหนไม่ปรากฏในข้อความเลย ถือว่า AI กุขึ้นมา -> ยกเลิกการตีความเป็นคำสั่งทั้งหมด ปล่อยเป็น free-chat แทน
        normalized_message = regex_lib.sub(r"\s+", "", message.content.lower())
        for pname, value in raw_args.items():
            value_str = str(value).strip()
            if not value_str:
                continue
            normalized_value = regex_lib.sub(r"\s+", "", value_str.lower())
            if normalized_value and normalized_value not in normalized_message:
                print(
                    f"⚠️ [AI Router] บล็อกการเรียก /{function_call.name} เพราะพารามิเตอร์ '{pname}'="
                    f"'{value_str}' ไม่ปรากฏในข้อความจริงของผู้ใช้ (ต้องสงสัยว่า AI กุขึ้นมาเอง)"
                )
                return False

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
