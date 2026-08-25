# ============================================================
# 📜 Bagley Rules — สอนแบ็คลี่ด้วยการ "พิมพ์คุยเฉยๆ" (ไม่ต้องพิมพ์ /teach)
# ============================================================
# แนวคิด: เวลามีคนพิมพ์อะไรทำนอง "จำไว้ว่า...", "ห้ามทำ...", "ต่อไปนี้ให้..." ใส่แบ็คลี่ตรงๆ
# ให้ AI ช่วยตัดสินใจว่านี่คือ "คำสั่งสอน/กำหนดกฎ" จริงมั้ย (ไม่ใช่แค่คุยเล่นทั่วไปที่บังเอิญมีคำว่า
# ห้าม/อย่า) ถ้าใช่ ให้สรุปเป็นกฎสั้นๆ 1 ประโยคแล้วจำไว้ "ทุกเซิร์ฟเวอร์ที่บอทอยู่" (ตาราง learned_rules
# ไม่มี guild_id ผูกไว้ เหมือนกับ teach_memory เดิม เพราะเป็น DB ไฟล์เดียวของบอทตัวเดียว)
#
# 🔒 ทำไมต้องกรอง 2 ชั้น (ไม่ใช่ให้ AI ตัดสินใจเองล้วนๆ):
#   ชั้น 1 (heuristic คำใบ้): กรองก่อนว่าข้อความมีลักษณะเป็นคำสั่งสอนมั้ย (มีคำอย่าง "จำไว้"/"ห้าม"/
#           "ต่อไปนี้") กันไม่ให้ยิง AI เรียกทุกข้อความที่เอ่ยถึงแบ็คลี่ (สิ้นเปลือง + เสี่ยง false positive)
#   ชั้น 2 (สิทธิ์/trust): ใช้เกณฑ์เดียวกับ ephemeral_tools (ALLOWED_TEACH_USERS ได้สิทธิ์ทันที
#           หรือคนอื่นที่ "คุ้นเคยกับแบ็คลี่พอ" ตาม bagley_trust) กันไม่ให้คนแปลกหน้า/โทรลโผล่มาแล้ว
#           สั่งสอนพฤติกรรมบอทได้ทันที เพราะกฎที่จำไปจะมีผล "ทุกเซิร์ฟเวอร์" ไม่ใช่แค่ห้องเดียว
#   ชั้น 3 (AI ตัดสินใจสุดท้าย): ให้ AI เช็คอีกทีว่าข้อความนี้ตั้งใจสั่งสอนบอทจริง (ไม่ใช่พูดกับคนอื่น
#           หรือพูดเล่น) และเช็คว่าไม่ใช่คำสั่งที่ให้บอทไปทำร้าย/คุกคาม/เหยียดใคร ถ้าเข้าข่ายอันตราย
#           ให้ปฏิเสธไม่บันทึก
#
# 🧹 ช่องทางลบ/ตรวจสอบ: มีคำสั่ง /list_rules และ /forget_rule (จำกัดสิทธิ์เหมือน /teach /unteach)
#   ไว้เป็นทางแก้เผื่อ AI จำอะไรผิดพลาดหรือมีคนแอบสอนเรื่องแปลกๆ เข้ามา
#
# วิธีติดตั้ง (ใน bot.py):
#   1. import bagley_rules
#   2. ใน on_ready: bagley_rules.configure(client, conn)
#                    bagley_rules.init_rules_db(conn)
#   3. ใน on_message ตรงจุดที่รู้แล้วว่าข้อความนี้ "เอ่ยถึง/คุยกับแบ็คลี่ตรงๆ" (is_message_addressed_to_bagley)
#      ก่อนจะไหลลงไป teach_memory / free chat ตามปกติ:
#         learned_ack = await bagley_rules.maybe_learn_from_message(message, get_realtime_name)
#         if learned_ack:
#             await message.reply(learned_ack)
#             return
#   4. ตอนสร้าง prompt คุยเล่น/ตอบคำถามปกติ (free_chat_prompt ฯลฯ) แปะกฎที่จำไว้เข้าไปด้วย:
#         {bagley_rules.format_rules_for_prompt()}
# ============================================================

import re
import sqlite3
import discord

import bagley_trust

_client = None
_conn = None

# คนที่ได้สิทธิ์สอนกฎแบบพิมพ์คุยเฉยๆ ทันที (ตั้งจาก bot.py ตอน configure — แนะนำให้ใช้ชุดเดียวกับ ALLOWED_TEACH_USERS)
ALLOWED_RULE_TEACHERS: set[int] = set()
_is_user_blocked_fn = None  # ส่งมาจาก bot.py กัน circular import — คนโดน block ห้ามสอนกฎเด็ดขาด

_MAX_RULES_IN_PROMPT = 25  # กันพรอมต์บวมถ้ามีกฎสะสมเยอะมากในอนาคต (ใช้กฎล่าสุดก่อน)

# ชั้น 1: คำใบ้คร่าวๆ ว่าข้อความอาจเป็นการ "สั่งสอน/กำหนดกฎ" — ยังไม่ใช่ตัวตัดสินสุดท้าย
# (มีทั้งไทย/อังกฤษ จงใจให้กว้างไว้ก่อน เพราะขั้นต่อไปมี AI + trust กรองซ้ำอยู่แล้ว)
_TEACH_HINT_KEYWORDS = (
    "จำไว้", "จดไว้", "จงจำ", "ต่อไปนี้ให้", "ตั้งแต่นี้ไป", "ห้าม", "อย่า",
    "กฎ", "กติกา", "ข้อห้าม",
    "remember this", "remember that", "from now on", "never", "always remember", "don't ever",
)


def configure(client, conn, is_user_blocked_fn=None):
    global _client, _conn, _is_user_blocked_fn
    _client = client
    _conn = conn
    _is_user_blocked_fn = is_user_blocked_fn


def init_rules_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learned_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text TEXT NOT NULL,
            source_guild_id INTEGER,
            source_user_id INTEGER,
            source_name TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _looks_like_teach_hint(lower_text: str) -> bool:
    return any(kw in lower_text for kw in _TEACH_HINT_KEYWORDS)


# 🧠 [ปรับปรุง] เดิมฟังก์ชันนี้ใช้ heuristic แบบดิบๆ (แค่เช็คว่ามีคำว่า "จำไว้ว่า" อยู่ในข้อความมั้ย)
# แล้วโยนทุกอย่างที่มีคำนี้ไปให้ execute_remember_logic (ระบบบันทึกชื่อเล่น/วันเกิด) ทันที ทำให้ข้อความ
# แบบ "จำไว้ว่าห้ามพูดคำหยาบ" ที่ควรเป็นกฎถาวร หรือ "จำไว้ว่าพรุ่งนี้มีสอบ" ที่ควรเป็นการตั้งเตือน
# ถูกเข้าใจผิดเป็น "บันทึกชื่อเล่น" ไปหมด (AI มีแค่ตัวเลือก nickname/birthday/hobby ให้เลือก ไม่มี
# ตัวเลือกอื่นเลย) ตอนนี้เปลี่ยนมาใช้ _classify_remember_message() ให้ AI ช่วยแยกหมวดหมู่แทน
# (ดูฟังก์ชันด้านล่าง) โดยยังคง heuristic ชั้น 1 (_looks_like_teach_hint) ไว้เป็นตัวกรองก่อนยิง AI
# เหมือนเดิม เพื่อประหยัด quota ไม่ต้องยิงทุกข้อความ

_REMEMBER_CLASSIFY_PROMPT = """\
ข้อความนี้มาจากคนที่พิมพ์คุยกับบอทดิสคอร์ดชื่อแบ็คลี่ (Bagley) ตรงๆ (มักขึ้นต้นด้วยคำว่า "จำไว้ว่า" หรือทำนองเดียวกัน):
"{message_text}"

ให้จัดหมวดหมู่ข้อความนี้เป็นอย่างใดอย่างหนึ่งต่อไปนี้เท่านั้น (เลือกได้แค่ 1 อย่าง):

1. PERSONAL — ขอให้จำ "ข้อมูลส่วนตัวของคนคนหนึ่ง" เช่น ชื่อเล่น/ฉายา, วันเกิด, สิ่งที่ชอบ/งานอดิเรก/ของกินที่ชอบ
   ตัวอย่าง: "จำไว้ว่า 123456789012345678 คือ ตัส", "จำไว้ว่ากูชื่อนิโคลัส", "จำไว้ว่าคนนี้ชอบกินส้มตำ", "จำไว้ว่าเขาเกิดวันที่ 5 พ.ค."
2. RULE — สั่งให้บอทเปลี่ยนพฤติกรรม/กำหนดกฎเกณฑ์ที่บอทต้องทำตาม "ถาวร" ไม่เกี่ยวกับข้อมูลของคนใดคนหนึ่ง
   ตัวอย่าง: "จำไว้ว่าห้ามพูดคำหยาบ", "ต่อไปนี้ห้ามพูดคำว่า...", "จำไว้ว่าอย่าเรียกกูว่าเจ้านาย"
3. REMINDER — พูดถึงเหตุการณ์/นัดหมายในอนาคตที่ควรมีการตั้งเตือนความจำให้ ไม่ใช่กฎถาวรของบอทและไม่ใช่ข้อมูลส่วนตัวของใคร
   ตัวอย่าง: "จำไว้ว่าพรุ่งนี้มีสอบ", "จำไว้ว่าวันศุกร์มีนัดหมอ", "จำไว้ว่าอาทิตย์หน้ามีประชุม"
4. NONE — ไม่เข้าข่ายข้างต้นเลย, คุยเล่นทั่วไป, ถามคำถามธรรมดา, หรือเป็นคำสั่งอันตราย/ให้บอทไปด่าทอ-คุกคาม-เหยียดใคร (แม้พูดเล่นก็ตัดสินเป็น NONE)

ตอบกลับรูปแบบเดียวเท่านั้น บรรทัดเดียว ห้ามมีคำอธิบายอื่นปน:
- ถ้าเป็น PERSONAL ให้ตอบคำเดียว: PERSONAL
- ถ้าเป็น RULE ให้ตอบ: RULE::<สรุปกฎสั้นๆ 1 ประโยค เขียนเป็นคำสั่งที่บอทเอาไปเตือนตัวเองได้ทันที>
- ถ้าเป็น REMINDER ให้ตอบ: REMINDER::<สรุปเนื้อหาเหตุการณ์สั้นๆ ไม่เกิน 1 ประโยค>
- ถ้าเป็น NONE ให้ตอบคำเดียว: NONE
"""


async def _classify_remember_message(message_text: str) -> tuple[str, str | None]:
    """ให้ AI ตัดสินใจว่าข้อความ (ที่ผ่านคำใบ้ชั้น 1 มาแล้ว) เข้าข่ายหมวดไหน คืน (category, payload):
       - ("personal", None)       -> ให้ bot.py เรียก execute_remember_logic (บันทึกชื่อเล่น/วันเกิด/สิ่งที่ชอบ) ต่อ
       - ("rule", "<กฎสรุป>")     -> เป็นกฎถาวรให้บอททำตาม
       - ("reminder", "<เหตุการณ์>") -> เป็นเรื่องที่ควรตั้งเตือนความจำ
       - ("none", None)          -> ไม่เข้าข่ายอะไรเลย"""
    if _client is None:
        return "none", None
    try:
        resp = await _client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=_REMEMBER_CLASSIFY_PROMPT.format(message_text=message_text),
        )
        text = (getattr(resp, "text", "") or "").strip().strip('"')
    except Exception as e:
        print(f"⚠️ [Rules] AI จัดหมวดข้อความ 'จำไว้ว่า' พลาด: {e}")
        return "none", None

    if not text:
        return "none", None

    upper = text.upper()
    if upper.startswith("PERSONAL"):
        return "personal", None
    if upper.startswith("RULE"):
        payload = text.split("::", 1)[1].strip() if "::" in text else ""
        return ("rule", payload[:300]) if payload else ("none", None)
    if upper.startswith("REMINDER"):
        payload = text.split("::", 1)[1].strip() if "::" in text else ""
        return ("reminder", payload[:200]) if payload else ("none", None)
    return "none", None


def _is_teaching_allowed(message: discord.Message) -> bool:
    """เกณฑ์สิทธิ์เดียวกับ ephemeral_tools._is_dynamic_allowed — เพราะผลกระทบพอกัน
    (กฎที่จำไปมีผลข้ามเซิร์ฟเวอร์ ไม่ใช่แค่คนคุยกันเล่นในห้องเดียว)"""
    user_id = message.author.id
    if user_id in ALLOWED_RULE_TEACHERS:
        return True
    if _is_user_blocked_fn is not None and _is_user_blocked_fn(str(user_id)):
        return False
    if not message.guild:
        return False
    return bagley_trust.is_trusted_for_dynamic_tools(user_id, message.guild.id)


def _save_rule(rule_text: str, message: discord.Message):
    if _conn is None:
        return
    _conn.execute(
        "INSERT INTO learned_rules (rule_text, source_guild_id, source_user_id, source_name) VALUES (?, ?, ?, ?)",
        (
            rule_text,
            message.guild.id if message.guild else None,
            message.author.id,
            str(message.author),
        ),
    )
    _conn.commit()
    print(f"📜 [Rules] จดกฎใหม่ (จาก {message.author}): {rule_text}")


async def maybe_learn_from_message(message: discord.Message, get_realtime_name=None) -> tuple[str, str | None] | None:
    """เรียกจาก on_message ตรงจุดที่ข้อความนี้ 'เอ่ยถึง/คุยกับแบ็คลี่ตรงๆ' แล้ว —
    คืน tuple (category, payload) ถ้าเข้าข่ายต้องจัดการต่อ ให้ bot.py แยกไปทำงานตาม category:
       - ("rule", "<ข้อความ ack>")      -> จดกฎสำเร็จแล้ว ให้ bot.py reply payload แล้ว return เลย
       - ("personal", None)             -> ให้ bot.py เรียก execute_remember_logic เอง (บันทึกชื่อเล่น/วันเกิด/สิ่งที่ชอบ)
       - ("reminder", "<เหตุการณ์>")     -> ให้ bot.py จัดการตั้งเตือน (ถามเวลาต่อถ้ายังไม่มีในข้อความ)
    คืน None ถ้าไม่เข้าข่ายอะไรเลย (ปล่อยให้ไหลลงไปทำงานปกติต่อ)"""
    if _client is None or _conn is None:
        return None
    content = (message.content or "").strip()
    if not content:
        return None

    lower_content = content.lower()

    # 🛡️ [กันบั๊กชนกัน] ถ้าข้อความเข้าข่ายรูปแบบ "เตือนฉันตอน.../เตือน @เพื่อน ตอน..." อยู่แล้ว ให้ปล่อยผ่าน
    # ไปให้ระบบเตือนตัวเอง/เพื่อนเดิมที่ [ส่วนที่ 2] ของ bot.py จัดการแต่ผู้เดียว (มี regex จับเวลา +
    # วาร์ปเข้าห้องเสียงมาเตือนจริงอยู่แล้ว) ไม่ให้ระบบ REMINDER ใหม่ของที่นี่ (ซึ่งจะถามเวลาเองอีกรอบ)
    # มาแย่งตีความซ้อนกัน เพราะจะทำให้ผลลัพธ์ไม่สม่ำเสมอว่าข้อความเดียวกันจะโดนระบบไหนจับก่อน
    # (เงื่อนไขนี้ต้องตรงกับ ai_command_router.looks_like_personal_reminder เป๊ะๆ)
    if "เตือน" in lower_content and ("ตอน" in lower_content or "เวลา" in lower_content):
        return None

    if not _looks_like_teach_hint(lower_content):
        return None  # ชั้น 1: ไม่มีคำใบ้เลย ไม่ต้องเสียเวลายิง AI

    category, payload = await _classify_remember_message(content)  # ชั้น 2 (AI แยกหมวด)

    if category == "personal":
        return "personal", None

    if category == "reminder":
        if not payload:
            return None
        return "reminder", payload

    if category == "rule":
        if not payload:
            return None
        if not _is_teaching_allowed(message):
            return None  # ชั้น 3: ไม่มีสิทธิ์สอนกฎข้ามเซิร์ฟเวอร์ — เงียบๆ ปล่อยให้ไหลไปคุยเล่นปกติแทน
        _save_rule(payload, message)
        caller_name = get_realtime_name(message.author.id, message.author.display_name) if get_realtime_name else message.author.display_name
        ack = (
            f"รับทราบครับคุณ {caller_name}! จดกฎนี้ไว้ในคลังสมองแล้ว: **\"{payload}\"** 🧠📜 "
            "จะจำไปใช้ทุกเซิร์ฟเวอร์ที่ผมอยู่เลยครับ (ถ้าอยากให้ลืม ใช้ /list_rules กับ /forget_rule ได้)"
        )
        return "rule", ack

    return None


def get_rule_texts(limit: int = _MAX_RULES_IN_PROMPT) -> list[str]:
    if _conn is None:
        return []
    rows = _conn.execute(
        "SELECT rule_text FROM learned_rules ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [r[0] for r in rows][::-1]


def format_rules_for_prompt() -> str:
    """ข้อความพร้อมแปะเข้า system/free-chat prompt — คืนสตริงว่างถ้ายังไม่มีกฎที่จำไว้เลย"""
    rules = get_rule_texts()
    if not rules:
        return ""
    bullet_list = "\n".join(f"- {r}" for r in rules)
    return (
        "\n📜 กฎที่เคยถูกสอนไว้ (ต้องทำตามเสมอ ไม่ว่าจะอยู่เซิร์ฟเวอร์ไหน):\n" + bullet_list + "\n"
    )


def list_rules_text() -> str:
    if _conn is None:
        return "ยังไม่มีกฎที่จดไว้เลยครับ"
    rows = _conn.execute(
        "SELECT id, rule_text, source_name FROM learned_rules ORDER BY id ASC"
    ).fetchall()
    if not rows:
        return "ยังไม่มีกฎที่จดไว้เลยครับ"
    lines = [f"`#{rid}` {text}  _(สอนโดย {name})_" for rid, text, name in rows]
    return "\n".join(lines)


def forget_rule(rule_id: int) -> bool:
    if _conn is None:
        return False
    row = _conn.execute("SELECT id FROM learned_rules WHERE id = ?", (rule_id,)).fetchone()
    if not row:
        return False
    _conn.execute("DELETE FROM learned_rules WHERE id = ?", (rule_id,))
    _conn.commit()
    return True
