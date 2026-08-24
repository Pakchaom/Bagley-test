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


async def _classify_and_extract(message_text: str) -> str | None:
    """ให้ AI ตัดสินใจชั้นสุดท้ายว่านี่คือคำสั่งสอน/กำหนดกฎให้แบ็คลี่จำจริงมั้ย ถ้าใช่คืนกฎสรุปสั้นๆ
    1 ประโยค ถ้าไม่ใช่ (หรือเข้าข่ายอันตราย/ไม่เหมาะสม) คืน None"""
    prompt = (
        "ข้อความนี้มาจากคนที่พิมพ์คุยกับบอทดิสคอร์ดชื่อแบ็คลี่ (Bagley) ตรงๆ:\n"
        f"\"{message_text}\"\n\n"
        "ตัดสินใจว่าข้อความนี้ 'ตั้งใจสั่งสอน/กำหนดกฎเกณฑ์ถาวร' ให้บอทจดจำไว้ทำตามตลอดไปหรือไม่ "
        "(เช่น บอกให้จำอะไรบางอย่าง, ห้ามบอททำอะไรบางอย่าง, สั่งให้บอทเปลี่ยนพฤติกรรมถาวรตั้งแต่นี้ไป)\n"
        "ไม่ใช่กรณีนี้ (ให้ตอบ NONE): คุยเล่นทั่วไป, ถามคำถาม, สั่งบอทให้ทำงานครั้งเดียวตอนนี้ (ไม่ใช่กฎถาวร), "
        "พูดถึง 'ห้าม/อย่า' กับเรื่องอื่นที่ไม่เกี่ยวกับพฤติกรรมบอท, หรือเป็นคำสั่งที่จะให้บอทไปคุกคาม/ด่าทอ/"
        "เหยียดหยาม/ทำร้ายใครก็ตาม (แม้จะพูดเล่นๆ ก็ปฏิเสธ)\n"
        "ถ้าใช่จริง ให้สรุปเป็นกฎสั้นๆ 1 ประโยค เขียนเป็นคำสั่งที่บอทจะเอาไปใช้เตือนตัวเองได้ทันที\n"
        "ตอบกลับแค่บรรทัดเดียว: ถ้าไม่ใช่ตอบคำว่า NONE เท่านั้น ถ้าใช่ให้ตอบเป็นตัวกฎเลย ห้ามมีคำอธิบายอื่นปน"
    )
    try:
        resp = await _client.aio.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        text = (getattr(resp, "text", "") or "").strip().strip('"')
        if not text or text.upper() == "NONE":
            return None
        return text[:300]
    except Exception as e:
        print(f"⚠️ [Rules] AI ตัดสินใจกฎพลาด: {e}")
        return None


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


async def maybe_learn_from_message(message: discord.Message, get_realtime_name=None) -> str | None:
    """เรียกจาก on_message ตรงจุดที่ข้อความนี้ 'เอ่ยถึง/คุยกับแบ็คลี่ตรงๆ' แล้ว —
    คืนข้อความ ack ถ้าจดกฎใหม่สำเร็จ (ให้ bot.py reply แล้ว return เลย ไม่ต้องไหลไปคุยเล่น/หาคำสั่งต่อ)
    คืน None ถ้าไม่เข้าข่าย (ปล่อยให้ไหลลงไปทำงานปกติต่อ)"""
    if _client is None or _conn is None:
        return None
    content = (message.content or "").strip()
    if not content:
        return None

    lower_content = content.lower()
    if not _looks_like_teach_hint(lower_content):
        return None  # ชั้น 1: ไม่มีคำใบ้เลย ไม่ต้องเสียเวลายิง AI

    if not _is_teaching_allowed(message):
        return None  # ชั้น 2: ไม่มีสิทธิ์สอนกฎข้ามเซิร์ฟเวอร์ — เงียบๆ ปล่อยให้ไหลไปคุยเล่นปกติแทน

    rule_text = await _classify_and_extract(content)  # ชั้น 3
    if not rule_text:
        return None

    _save_rule(rule_text, message)
    caller_name = get_realtime_name(message.author.id, message.author.display_name) if get_realtime_name else message.author.display_name
    return (
        f"รับทราบครับคุณ {caller_name}! จดกฎนี้ไว้ในคลังสมองแล้ว: **\"{rule_text}\"** 🧠📜 "
        "จะจำไปใช้ทุกเซิร์ฟเวอร์ที่ผมอยู่เลยครับ (ถ้าอยากให้ลืม ใช้ /list_rules กับ /forget_rule ได้)"
    )


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
