# ============================================================
# ⚡ Ephemeral Tools — คำสั่ง/ความสามารถชั่วคราวที่ AI เขียนสดสำหรับงานเฉพาะครั้ง
# ============================================================
# แนวคิด: เมื่อ ai_command_router หา hybrid_command ที่ตรงไม่เจอ แต่ผู้ใช้ขอให้ทำ
# อะไรที่ทำได้ด้วยชุด "ความสามารถปลอดภัย" (SafeAPI) ด้านล่าง ให้ Gemini เขียนฟังก์ชัน
# Python สั้นๆ ที่เรียกผ่าน api.xxx(...) เท่านั้น (ห้าม import, ห้ามแตะไฟล์/เน็ต/token)
# ฟังก์ชันที่สร้างขึ้นอยู่ใน dict บน RAM เท่านั้น ใช้เสร็จลบทิ้งทันที ไม่เขียนลงดิสก์เลย
# รีสตาร์ทบอทก็หายไปเองโดยธรรมชาติอยู่แล้ว (เพราะไม่เคย persist ตั้งแต่ต้น)
#
# 🔒 ข้อควรระวังสำคัญ (อ่านก่อนใช้จริง):
#   - โค้ดที่ AI เขียนมาเสี่ยงเสมอ ถึงจะ sandbox แล้วก็ไม่ปลอดภัย 100%
#   - สิทธิ์ "สร้างความสามารถใหม่" มี 2 ทางเข้าถึงพร้อมกัน (ดู _is_dynamic_allowed ด้านล่าง):
#       1) อยู่ใน ALLOWED_DYNAMIC_USERS ตรงๆ (เช่น owner/ผู้ดูแลที่เพิ่มมือ) -> ได้สิทธิ์ทันที
#       2) หรือ "คุ้นเคยกับแบ็คลี่พอ" ตามเกณฑ์ใน bagley_trust.py (คุยมานานพอ + บ่อยพอ)
#          ทำให้คนทั่วไปที่คุยกับบอทสม่ำเสมอ ไม่ต้องรอ admin เพิ่มชื่อเองก็ใช้ได้
#     คนที่โดน block (blocked_users ใน bot.py) จะถูกตัดสิทธิ์ทาง trust-based ทันที ไม่ว่าคุยมานานแค่ไหน
#   - SafeAPI ด้านล่างจงใจไม่ให้เข้าถึง bot token, os, subprocess, ไฟล์ระบบ หรือ discord object ตรงๆ
#     เปิดเฉพาะ method ที่ปลอดภัยและจำกัดผลกระทบเท่านั้น — ไม่มี kick/ban/delete ผ่านทางนี้เด็ดขาด
#
# วิธีติดตั้ง (ใน bot.py):
#   1. import ephemeral_tools, bagley_trust
#   2. ใน on_ready: bagley_trust.configure(conn); bagley_trust.init_trust_db(conn)
#                    ephemeral_tools.configure(client, is_user_blocked_fn=is_user_blocked)
#                    ephemeral_tools.ALLOWED_DYNAMIC_USERS = set(ALLOWED_TEACH_USERS)  # หรือกำหนดเอง
#   3. ใน on_message ทุกครั้งที่เอ่ยถึงแบ็คลี่: bagley_trust.track_interaction(message.author.id, message.guild.id)
#   4. หลัง ai_route_and_execute คืน False (ไม่ตรงคำสั่งไหนเลย) และข้อความเอ่ยถึงแบ็คลี่:
#         handled = await ephemeral_tools.try_create_and_run(message, message.content)
#         if handled:
#             return
# ============================================================

import asyncio
import secrets
import discord
import bagley_trust

# ใครสร้างความสามารถใหม่ได้บ้าง — ตั้งค่าจาก bot.py ตอน configure
# คนใน list นี้ได้สิทธิ์ทันทีเสมอ (เช่น owner/ผู้ดูแล) ส่วนคนอื่นๆ จะได้สิทธิ์อัตโนมัติ
# ถ้าคุยกับแบ็คลี่คุ้นเคยพอตามเกณฑ์ใน bagley_trust.py (ดู is_trusted_for_dynamic_tools)
ALLOWED_DYNAMIC_USERS: set[int] = set()

# คนที่เคยถูก block (blocked_users ใน bot.py) ห้ามผ่านทาง trust-based เด็ดขาด แม้คุยมาเยอะแล้วก็ตาม
# ส่งฟังก์ชันเช็คมาจาก bot.py ตอน configure เพื่อไม่ต้อง import bot.py กลับเข้ามา (กัน circular import)
_is_user_blocked_fn = None


def _is_dynamic_allowed(message: discord.Message) -> bool:
    user_id = message.author.id
    if user_id in ALLOWED_DYNAMIC_USERS:
        return True
    if _is_user_blocked_fn is not None and _is_user_blocked_fn(str(user_id)):
        return False  # โดน block ไว้ ตัดสิทธิ์ trust-based ทันที ไม่ต้องเช็คต่อ
    if not message.guild:
        return False
    return bagley_trust.is_trusted_for_dynamic_tools(user_id, message.guild.id)

_client = None
_EXEC_TIMEOUT_SECONDS = 5

# RAM เท่านั้น ไม่เขียนไฟล์ — ใช้ครั้งเดียวแล้ว pop ทิ้งทันทีในทุก path (สำเร็จ/error/timeout)
ephemeral_tools: dict[str, callable] = {}

# ป้องกันชั้นที่ 2: ถ้า AI แอบเขียนคำเหล่านี้มาในโค้ด ไม่ให้รันเด็ดขาด (ชั้นหลักคือไม่มี __builtins__ อยู่แล้ว)
_FORBIDDEN_TOKENS = (
    "import", "__", "open(", "exec(", "eval(", "os.", "sys.",
    "subprocess", "socket", "requests", "getattr", "setattr",
)


def configure(client, is_user_blocked_fn=None):
    global _client, _is_user_blocked_fn
    _client = client
    _is_user_blocked_fn = is_user_blocked_fn


class SafeAPI:
    """ชุดความสามารถที่ปลอดภัยให้โค้ดของ AI เรียกได้ — ไม่ใช่ bot object ตรงๆ
    เพิ่ม method ใหม่ได้เรื่อยๆ ตามต้องการ แต่ห้ามเพิ่ม method ที่กระทบคนอื่นแบบย้อนกลับไม่ได้
    (kick/ban/delete) ผ่านทางนี้ ถ้าจำเป็นต้องมี ให้ทำเป็น hybrid_command ถาวรที่รีวิวโค้ดแล้วแทน
    """

    def __init__(self, message: discord.Message):
        self._message = message
        self._guild = message.guild

    async def send(self, text: str):
        """ส่งข้อความในห้องแชทที่คุยอยู่"""
        await self._message.channel.send(str(text)[:2000])

    async def move_member_to_channel(self, member_name: str, channel_name: str) -> bool:
        """ย้ายสมาชิก (ที่อยู่ในห้องเสียงอยู่แล้ว) ไปอีกห้องเสียงในกิลด์เดียวกัน"""
        if not self._guild:
            return False
        member = discord.utils.find(
            lambda m: member_name.lower() in m.display_name.lower(), self._guild.members
        )
        channel = discord.utils.find(
            lambda c: channel_name.lower() in c.name.lower(), self._guild.voice_channels
        )
        if member and channel and member.voice and member.voice.channel:
            await member.edit(voice_channel=channel)
            return True
        return False

    async def rename_current_voice_channel(self, new_name: str) -> bool:
        """เปลี่ยนชื่อห้องเสียงที่แบ็คลี่อยู่ตอนนี้ (ชั่วคราว)"""
        if not self._guild or not self._guild.voice_client:
            return False
        vc = self._guild.voice_client
        if vc.channel:
            await vc.channel.edit(name=new_name[:100])
            return True
        return False

    async def add_reaction(self, emoji: str):
        """แสดงอารมณ์ต่อข้อความล่าสุดที่คุยด้วย"""
        try:
            await self._message.add_reaction(emoji)
            return True
        except Exception:
            return False


def _code_is_safe(code: str) -> bool:
    lowered = code.lower()
    return not any(tok in lowered for tok in _FORBIDDEN_TOKENS)


async def try_create_and_run(message: discord.Message, task_description: str) -> bool:
    """คืน True ถ้าตีความว่าเป็นงานที่ควรสร้างความสามารถชั่วคราว
    (ไม่ว่าจะสำเร็จ, ปฏิเสธเพราะไม่ปลอดภัย, หรือ error ก็ตอบผู้ใช้ไปแล้วในทุกกรณี)
    """
    if not _is_dynamic_allowed(message):
        return False
    if _client is None:
        return False

    prompt = (
        "คุณกำลังเขียนฟังก์ชัน Python ชื่อ run(api) (เป็น async function) สำหรับบอทดิสคอร์ดชื่อแบ็คลี่\n"
        "ห้ามใช้ import ใดๆ ทั้งสิ้น ห้ามเข้าถึงไฟล์ ห้ามเข้าถึงเน็ตเวิร์ก ห้ามใช้ getattr/setattr\n"
        "คุณมีตัวแปร api ที่มี method (เรียกด้วย await เสมอ) ให้ใช้ได้เท่านั้น:\n"
        "  await api.send(text)\n"
        "  await api.move_member_to_channel(member_name, channel_name) -> bool\n"
        "  await api.rename_current_voice_channel(new_name) -> bool\n"
        "  await api.add_reaction(emoji)\n\n"
        f"งานที่ผู้ใช้ขอ: {task_description}\n"
        "ถ้าทำไม่ได้ด้วย method ที่มี ให้เขียน run(api) ที่แค่ await api.send(...) อธิบายว่าทำไม่ได้\n"
        "ตอบเฉพาะโค้ดของฟังก์ชัน async def run(api): ... เท่านั้น ห้ามมีคำอธิบายอื่นนอกโค้ด"
    )

    try:
        resp = await _client.aio.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        code = (getattr(resp, "text", "") or "").strip()
        code = code.strip("`")
        if code.lower().startswith("python"):
            code = code[len("python"):].strip()
    except Exception as e:
        print(f"⚠️ [Ephemeral] ขอโค้ดจาก AI พลาด: {e}")
        return False

    if "async def run" not in code or not _code_is_safe(code):
        await message.channel.send("❌ แบ็คลี่คิดวิธีทำงานนี้แบบปลอดภัยไม่ได้ครับ ขอโทษด้วยนะครับ")
        return True

    tool_id = secrets.token_hex(4)
    print(f"🧪 [Ephemeral] {message.author} ({message.author.id}) สั่งงานชั่วคราว: {task_description}\n--- code ---\n{code}\n------------")

    try:
        local_ns = {}
        # ไม่มี __builtins__ เลย -> ป้องกันชั้นหลัก ต่อให้หลุด _FORBIDDEN_TOKENS มาก็รันไม่ได้จริง
        exec(code, {"__builtins__": {}}, local_ns)
        run_fn = local_ns.get("run")
        if run_fn is None:
            raise ValueError("ไม่พบฟังก์ชัน run(api) ในโค้ดที่ AI เขียนมา")

        ephemeral_tools[tool_id] = run_fn
        api = SafeAPI(message)
        await asyncio.wait_for(ephemeral_tools[tool_id](api), timeout=_EXEC_TIMEOUT_SECONDS)

    except asyncio.TimeoutError:
        await message.channel.send("❌ ทำงานนี้นานเกินไป แบ็คลี่ยกเลิกให้แล้วครับ")
    except Exception as e:
        print(f"⚠️ [Ephemeral] รันโค้ดพลาด: {e}")
        await message.channel.send(f"❌ แบ็คลี่ลองทำแล้วแต่ error ครับ: {e}")
    finally:
        # ใช้ครั้งเดียวแล้วลบทันที ไม่ต้องรอ TTL หรือรอบอทรีสตาร์ท
        ephemeral_tools.pop(tool_id, None)

    return True
