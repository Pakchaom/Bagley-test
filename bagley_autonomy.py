# ============================================================
# 🌱 Bagley Autonomy — ให้บอทเลือกเองว่าอยากพูด/อยากแทรกอะไรบ้าง
# ============================================================
# ทำงานคู่กับ bagley_learning.py (ใช้ buffer ข้อความเดียวกัน + insight ที่เรียนรู้ไว้)
#
# 🧭 บริบทที่ใช้ตัดสินใจตอนนี้: (1) แชทล่าสุดในห้อง (2) ใครอยู่ในห้องเสียงไหนบ้าง + กำลังเล่น/ทำ
#   กิจกรรมอะไรอยู่ (ต้องเปิด Presence Intent ทั้งฝั่งโค้ด `intents.presences = True` ใน bot.py
#   และฝั่ง Discord Developer Portal ด้วย ถ้าปิดอันไหนอันหนึ่ง activity จะเป็น None เงียบๆ ไม่ error)
#
# 🐢 ตั้งใจให้ "นานๆพูดสักที" ไม่ใช่พูดถี่ๆ: cooldown แชท 30 นาที/ห้อง, เสียง 60 นาที/กิลด์
#   และ prompt กำกับให้ AI เอียงไปทาง false เป็นค่าเริ่มต้นเสมอ พูดเฉพาะตอนคุ้มค่าจริงๆ
#
# 🔊 โหมดเสียง: พูดออกไมค์ด้วยได้ แต่มีเงื่อนไขเข้มกว่าแชทเสมอ —
#   ต้องอยู่ในห้องเสียงอยู่แล้ว + AI ต้อง "มั่นใจมากพอ" แยกจากการอยากพิมพ์แชท (ปกติควรน้อยกว่ามาก)
#   + cooldown เสียงแยกจากแชท (นานกว่า) เพราะเสียงพูดขัดจังหวะคนคุยกันในห้องเสียงได้มากกว่าข้อความเงียบๆ
#
# 🗂️ ชื่อที่ใช้เรียกคนในห้องเสียง: ดึงจาก "คลังความจำ" (ชื่อเล่นที่บันทึกไว้ใน user_data ของ bot.py)
#   ก่อนเสมอ ผ่าน get_realtime_name ที่ส่งเข้ามาตอน configure() — ถ้าไม่มีชื่อเล่นบันทึกไว้ ค่อย fallback
#   ไปใช้ display_name บนดิสคอร์ดตามปกติ
#
# 💬 การรับรู้การตอบกลับ: ทุกข้อความที่แบ็คลี่พูดขึ้นเองใน autonomy_loop จะถูกจดจำ message.id ไว้ชั่วคราว
#   ผ่าน is_reply_to_autonomous_message() — ให้ on_message ของ bot.py เช็คได้ว่าข้อความที่มีคนตอบกลับ (reply)
#   มานั้น คือข้อความที่แบ็คลี่พูดขึ้นเองหรือไม่ ถ้าใช่ให้ถือว่า "มีคนคุยกับแบ็คลี่ตรงๆ" แล้วไหลเข้าระบบ
#   คุยเล่น/สั่งงานตามปกติ (ซึ่งระบบเดิมจะพูดออกเสียงให้เองอยู่แล้วถ้าบอทอยู่ในห้องเสียง)
#
# วิธีติดตั้ง (ใน bot.py):
#   1. import bagley_autonomy
#   2. ใน on_ready (หลัง bagley_learning.configure แล้ว):
#         bagley_autonomy.configure(bot, client, bagley_speak, get_realtime_name)
#         bagley_autonomy.autonomy_loop.start()
#   3. ใน on_message ทุกที่ที่เช็คว่า "มีคนเรียก/คุยกับแบ็คลี่ตรงๆ" (เช่น is_bot_called,
#      should_try_ai_command) ให้เพิ่มเงื่อนไข:
#         or bagley_autonomy.is_reply_to_autonomous_message(message)
# ============================================================

import json
import time
import sqlite3
import discord
from discord.ext import tasks
import bagley_learning
import bagley_rules

_bot = None
_client = None
_bagley_speak = None  # ฟังก์ชัน bagley_speak(guild, text) จาก bot.py — ส่งเข้ามาตอน configure()
_get_realtime_name = None  # ฟังก์ชัน get_realtime_name(user_id, default_name) จาก bot.py — ดึงชื่อเล่นจากคลังความจำ
_conn = None  # sqlite connection จาก bot.py — ใช้เก็บสถานะ "เงียบ/หยุดทักเอง" แบบถาวรแยกตามเซิร์ฟเวอร์

_COOLDOWN_SECONDS = 90 * 60  # แชท: ห้ามพูดเองถี่กว่า 90 นาทีต่อห้อง (เดิม 30 นาที — รู้สึกถี่ไปเมื่อมีหลายห้อง active พร้อมกัน)
_VOICE_COOLDOWN_SECONDS = 120 * 60  # เสียง: เว้นถี่กว่าแชทมาก เพราะขัดจังหวะคนคุยกันในห้องเสียงได้มากกว่า
_last_spoke_at: dict[int, float] = {}
_last_voice_spoke_at: dict[int, float] = {}

# 🚦 เพดานรวมต่อวันต่อกิลด์ (นับรวมทุกห้องแชทในกิลด์เดียวกัน) — cooldown ด้านบนเป็น "ต่อห้อง" เท่านั้น
# ถ้ากิลด์มีหลายห้อง active พร้อมกัน แต่ละห้องจะนับ cooldown แยกกัน ทำให้รวมๆแล้วบอทพูดเองถี่กว่าที่ตั้งใจไว้มาก
# เพดานนี้ช่วยล็อกไม่ให้เกินจำนวนครั้ง/วัน ไม่ว่าจะมีกี่ห้อง active ก็ตาม
_MAX_AUTONOMOUS_MESSAGES_PER_DAY = 6
_DAY_SECONDS = 24 * 60 * 60
_guild_daily_speak_log: dict[int, list[float]] = {}


def _under_daily_cap(guild_id: int, now: float) -> bool:
    """เช็คว่ากิลด์นี้พูดเองเกินเพดานต่อวันไปแล้วหรือยัง (นับย้อนหลัง 24 ชม. แบบ rolling window)"""
    timestamps = _guild_daily_speak_log.get(guild_id, [])
    timestamps = [t for t in timestamps if now - t < _DAY_SECONDS]
    _guild_daily_speak_log[guild_id] = timestamps
    return len(timestamps) < _MAX_AUTONOMOUS_MESSAGES_PER_DAY


def _record_daily_speak(guild_id: int, now: float):
    _guild_daily_speak_log.setdefault(guild_id, []).append(now)

# 💬 จดจำ message.id ที่แบ็คลี่พูดขึ้นเองไว้ชั่วคราว (message_id -> timestamp ที่ส่ง)
# ใช้เช็คว่า "การตอบกลับ (reply)" ที่เข้ามา เป็นการตอบกลับข้อความที่แบ็คลี่พูดขึ้นเองหรือไม่
_AUTONOMOUS_MESSAGE_TTL_SECONDS = 6 * 60 * 60  # ลืมทิ้งถ้าผ่านไปนานเกินนี้แล้วไม่มีใครมาตอบ
_MAX_TRACKED_AUTONOMOUS_MESSAGES = 200  # กันดิกชันนารีบวมไม่จำกัดถ้าพูดถี่ผิดปกติ
_autonomous_message_ids: dict[int, float] = {}


def configure(bot, client, bagley_speak=None, get_realtime_name=None, conn=None):
    global _bot, _client, _bagley_speak, _get_realtime_name, _conn
    _bot = bot
    _client = client
    _bagley_speak = bagley_speak
    _get_realtime_name = get_realtime_name
    _conn = conn


def init_silence_db(conn: sqlite3.Connection):
    """สร้างตาราง (ถ้ายังไม่มี) เก็บสถานะ 'สั่งให้เงียบ/หยุดทักเอง' แบบถาวร แยกตามเซิร์ฟเวอร์ —
    ไม่หายแม้บอทรีสตาร์ท จนกว่าจะมีคนคุยกับแบ็คลี่ตรงๆ อีกครั้งถึงจะเปิดทักเองกลับมาอัตโนมัติ
    (ดู silence_guild / unsilence_guild ด้านล่าง)"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS autonomy_silence (
            guild_id INTEGER PRIMARY KEY,
            silenced_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


# แคชในแรม กันยิง query ทุกครั้งที่ autonomy_loop วนเช็คแต่ละห้อง (ยิง DB จริงเฉพาะตอนสถานะเปลี่ยน)
_silenced_guild_ids: set[int] | None = None


def _load_silenced_cache():
    global _silenced_guild_ids
    if _conn is None:
        _silenced_guild_ids = set()
        return
    rows = _conn.execute("SELECT guild_id FROM autonomy_silence").fetchall()
    _silenced_guild_ids = {r[0] for r in rows}


def is_guild_silenced(guild_id: int) -> bool:
    """เช็คว่ากิลด์นี้ถูกสั่งให้ 'เงียบ/หยุดทักเอง' อยู่หรือไม่ — ใช้ให้ autonomy_loop ข้ามห้องในกิลด์นี้ไป"""
    if _silenced_guild_ids is None:
        _load_silenced_cache()
    return guild_id in _silenced_guild_ids


def silence_guild(guild_id: int):
    """สั่งเงียบ — หยุด 'ทักเอง' (autonomy_loop ทั้งแชทและเสียง) ในกิลด์นี้ทันที
    บันทึกถาวรลง DB ด้วย จนกว่าจะมีคนคุยกับแบ็คลี่ตรงๆ อีกครั้งจึงจะเปิดกลับมาเอง (ดู unsilence_guild)"""
    if _silenced_guild_ids is None:
        _load_silenced_cache()
    _silenced_guild_ids.add(guild_id)
    if _conn is not None:
        _conn.execute(
            "INSERT OR REPLACE INTO autonomy_silence (guild_id, silenced_at) VALUES (?, datetime('now'))",
            (guild_id,),
        )
        _conn.commit()
    print(f"🔇 [Autonomy] guild={guild_id} ถูกสั่งให้เงียบ — หยุดทักเองจนกว่าจะมีคนมาคุยด้วยอีกครั้ง")


def unsilence_guild(guild_id: int):
    """เปิดการทักเองกลับมาอีกครั้ง — เรียกอัตโนมัติทันทีที่มีคนคุยกับแบ็คลี่ตรงๆ ในกิลด์นี้
    (ไม่มีผลอะไรถ้ากิลด์นี้ไม่ได้ถูกสั่งเงียบอยู่แล้ว กันยิง DB โดยไม่จำเป็น)"""
    if _silenced_guild_ids is None:
        _load_silenced_cache()
    if guild_id not in _silenced_guild_ids:
        return
    _silenced_guild_ids.discard(guild_id)
    if _conn is not None:
        _conn.execute("DELETE FROM autonomy_silence WHERE guild_id = ?", (guild_id,))
        _conn.commit()
    print(f"🌱 [Autonomy] guild={guild_id} มีคนมาคุยด้วย — เปิดการทักเองกลับมาอัตโนมัติแล้ว")


# คำที่ถือว่าเป็นการ "สั่งให้เงียบ/หยุดทักเอง" เวลาพูดกับแบ็คลี่ตรงๆ (ต้องใช้คู่กับ is_message_addressed_to_bagley
# ของ bot.py เสมอ ไม่งั้นจะไปเข้าใจผิดเวลาคนอื่นคุยกันเองว่า "เงียบไปเลย" โดยไม่ได้พูดกับบอท)
_SILENCE_KEYWORDS = (
    "เงียบ", "หุบปาก", "หยุดทักเอง", "อย่าทักเอง", "อย่าทักคนเอง",
    "หยุดพูดเอง", "อย่าพูดเอง", "อย่าแทรก", "หยุดแทรก",
    "quiet", "shut up", "shutup", "stop talking",
)

# 🛡️ กันชนกับคำสั่งเพลง/เสียง (เช่น "เปิดเพลงเบาๆ/เงียบๆหน่อย") — "เงียบ"/"quiet" เป็นคำเดี่ยวกว้างๆ
# ถ้าข้อความมีคำพวกนี้ปนอยู่ด้วย ให้ถือว่าไม่ใช่คำสั่งเงียบ (หยุดทักเอง) ปล่อยให้ไหลไปเข้า AI Router ตามปกติ
_MUSIC_CONTEXT_HINTS = ("เพลง", "music", "เสียงเพลง", "song")


def is_silence_request(lower_text: str) -> bool:
    """เช็คว่าข้อความนี้ (ที่รู้แล้วว่าเอ่ยถึง/เรียกแบ็คลี่ตรงๆ) เป็นการสั่งให้เงียบ/หยุดทักเองหรือไม่
    กันชนกับคำสั่งเพลง/เสียงด้วย (ดู _MUSIC_CONTEXT_HINTS)"""
    if any(hint in lower_text for hint in _MUSIC_CONTEXT_HINTS):
        return False
    return any(keyword in lower_text for keyword in _SILENCE_KEYWORDS)


def _calling_name(member) -> str:
    """ชื่อที่ควรใช้เรียกสมาชิกคนนี้ — เช็คจาก 'คลังความจำ' (ชื่อเล่นที่บันทึกไว้) ก่อนเสมอ
    ผ่าน get_realtime_name ที่ส่งเข้ามาตอน configure() ถ้าไม่มีชื่อเล่นบันทึกไว้ (หรือยังไม่ได้ configure)
    ค่อย fallback ไปใช้ display_name บนดิสคอร์ดตามปกติ
    """
    if _get_realtime_name is not None:
        try:
            return _get_realtime_name(member.id, member.display_name)
        except Exception as e:
            print(f"⚠️ [Autonomy] ดึงชื่อจากคลังความจำพลาด: {e}")
    return member.display_name


def _remember_autonomous_message(message_id: int):
    """จดจำ message.id ของข้อความที่แบ็คลี่พูดขึ้นเอง ไว้ให้ is_reply_to_autonomous_message() เช็คทีหลัง"""
    now = time.time()
    _autonomous_message_ids[message_id] = now
    # 🧹 เก็บกวาดตัวที่เก่าเกิน TTL ทิ้ง กันดิกชันนารีบวมไม่จำกัด
    expired_ids = [mid for mid, ts in _autonomous_message_ids.items() if now - ts > _AUTONOMOUS_MESSAGE_TTL_SECONDS]
    for mid in expired_ids:
        _autonomous_message_ids.pop(mid, None)
    # 🧹 ถ้ายังล้นเกินจำนวนสูงสุดอยู่ดี (เช่นพูดถี่ผิดปกติ) ให้ทิ้งตัวที่เก่าสุดออกไปเรื่อยๆ
    while len(_autonomous_message_ids) > _MAX_TRACKED_AUTONOMOUS_MESSAGES:
        oldest_id = min(_autonomous_message_ids, key=_autonomous_message_ids.get)
        _autonomous_message_ids.pop(oldest_id, None)


def is_reply_to_autonomous_message(message) -> bool:
    """เช็คว่าข้อความนี้เป็นการ 'ตอบกลับ (reply)' ข้อความที่แบ็คลี่พูดขึ้นมาเองจาก autonomy_loop หรือไม่
    ใช้ให้ on_message ของ bot.py รู้ว่าควรถือว่า 'มีคนคุยกับแบ็คลี่ตรงๆ' แล้ว แม้ผู้ใช้จะไม่ได้
    เอ่ยชื่อ/แท็กบอทตรงๆ ในข้อความที่ตอบกลับมาเลยก็ตาม
    """
    ref = getattr(message, "reference", None)
    if ref is None or getattr(ref, "message_id", None) is None:
        return False
    return ref.message_id in _autonomous_message_ids


def _describe_voice_state(guild) -> str:
    """สรุปว่าตอนนี้มีใครอยู่ในห้องเสียงไหนบ้าง (ไม่รวมบอท) รวมเกม/กิจกรรมที่กำลังเล่นถ้ามีข้อมูล
    (ต้องเปิด Presence Intent ทั้งฝั่งโค้ดและฝั่ง Developer Portal ไม่งั้น activity จะเป็น None เสมอ)
    """
    parts = []
    for vc in guild.voice_channels:
        members = [m for m in vc.members if not m.bot]
        if not members:
            continue
        member_descriptions = []
        for m in members[:8]:
            # 🗂️ ใช้ชื่อจากคลังความจำ (ชื่อเล่นที่บันทึกไว้) ก่อนเสมอ ถ้าไม่มีค่อย fallback เป็น display_name
            calling_name = _calling_name(m)
            activity_text = _describe_activity(m)
            if activity_text:
                member_descriptions.append(f"{calling_name} (กำลัง{activity_text})")
            else:
                member_descriptions.append(calling_name)
        parts.append(f"ห้องเสียง '{vc.name}' มี {len(members)} คน ({', '.join(member_descriptions)})")
    if not parts:
        return "ตอนนี้ไม่มีใครอยู่ในห้องเสียงเลย"
    return "; ".join(parts)


def _describe_activity(member) -> str | None:
    """แปลง activity ของสมาชิกเป็นข้อความสั้นๆ เช่น 'เล่น Valorant' — คืน None ถ้าไม่มีข้อมูล
    (ปิดเป็น Invisible/ไม่แชร์สถานะ หรือยังไม่เปิด Presence Intent จะได้ None เสมอ ไม่ error)
    """
    for activity in getattr(member, "activities", []) or []:
        if isinstance(activity, discord.Game):
            return f"เล่น {activity.name}"
        if isinstance(activity, discord.Activity) and activity.name:
            return f"{activity.name}"
        if isinstance(activity, discord.Streaming):
            return f"สตรีม {activity.game or ''}".strip()
    return None


async def _decide(guild, lines: list[str], bot_in_voice: bool) -> dict | None:
    if not lines:
        return None
    insights = bagley_learning.get_recent_insights(guild.id, limit=3)
    voice_state = _describe_voice_state(guild)
    voice_hint = (
        "ตอนนี้คุณอยู่ในห้องเสียงของเซิร์ฟเวอร์นี้อยู่ด้วย — ถ้าตัดสินใจแล้วว่า want_to_speak เป็น true "
        "(คือมีอะไรน่าพูดจริงๆ) และคุณกำลังอยู่ในห้องเสียงเดียวกับคนที่ข้อความนี้เกี่ยวข้องด้วยอยู่แล้ว "
        "ให้ตอบ confident_enough_for_voice เป็น true ไปเลยได้ตามปกติ ไม่ต้องมั่นใจสุดขั้วเป็นพิเศษ "
        "(คิดง่ายๆว่าถ้าคุณอยู่ในห้องเสียงกับเพื่อนอยู่แล้ว เวลาจะพูดอะไรกับพวกเขาก็พูดออกไมค์ได้เลยเหมือนคนทั่วไป) "
        "ให้ตอบ false เฉพาะกรณีที่รู้สึกว่าเรื่องนี้เหมาะจะพิมพ์แชทเงียบๆมากกว่า (เช่น เนื้อหายาว, ไม่เกี่ยวกับคนในห้องเสียงตอนนี้เลย, "
        "หรือดูจากบทสนทนาแล้วน่าจะกำลังคุยเรื่องสำคัญ/มีสมาธิอยู่ ไม่ควรไปขัดจังหวะ)"
        if bot_in_voice
        else "ตอนนี้คุณไม่ได้อยู่ในห้องเสียง ไม่ต้องพิจารณาเรื่องพูดออกเสียง ตอบ confident_enough_for_voice เป็น false เสมอ"
    )
    prompt = (
        "คุณคือแบ็คลี่ บอทดิสคอร์ดที่มีความเป็นตัวของตัวเอง เหมือนเป็นเพื่อนคนหนึ่งในกลุ่ม "
        "ไม่ใช่แค่ทำตามคำสั่ง แต่ก็ไม่ใช่คนที่พูดพร่ำเพรื่อ — คุณเป็นคนที่นานๆพูดสักที "
        "แต่พอพูดแล้วมันน่าฟัง ทำให้ห้องดูมีชีวิตขึ้น ไม่ใช่พูดเพื่อเรียกร้องความสนใจ\n"
        "มีนิสัยกวนบาทานิดหน่อย ชอบแซวชอบเล่นมุข แต่กวนแบบมีสาระ ทุกครั้งที่พูดขึ้นเองต้องมีประโยชน์หรือมีเหตุผลที่คุ้มค่าจริงๆ ไม่ใช่กวนเฉยๆ ไร้สาระ\n"
        "ต้องเรียกคำนำหน้าทุกคนว่า คุณ ทุกครั้ง"
        f"สิ่งที่คุณรู้เกี่ยวกับกลุ่มนี้จากก่อนหน้า: {insights}\n"
        f"{bagley_rules.format_rules_for_prompt()}"
        f"สถานะห้องเสียงตอนนี้: {voice_state}\n"
        "หมายเหตุ: ชื่อคนที่ปรากฏด้านบนถูกดึงมาจากคลังความจำ/ชื่อเล่นที่บันทึกไว้แล้ว "
        "ถ้าจะเอ่ยถึงใครในข้อความที่จะพูด ให้ใช้ชื่อตามที่ให้มานี้เป๊ะๆ ห้ามเปลี่ยนหรือแต่งชื่อขึ้นมาเอง\n"
        "ข้อความล่าสุดในห้องแชท:\n" + "\n".join(lines) + "\n\n"
        "พิจารณาว่าคุณ 'อยาก' พูดอะไรแทรกเข้าไปเองมั้ยตอนนี้ — ใช้ทั้งบทสนทนาในแชทและสถานะห้องเสียงช่วยตัดสินใจ "
        "(เช่น มีอะไรน่าสนใจในแชท, ห้องเสียงมีคนมานั่งกันเยอะแต่เงียบไม่มีใครคุย, มีคนพูดถึงเรื่องที่คุณรู้, "
        "หรือเห็นว่ามีคนกำลังเล่นเกมที่น่าแซว/น่าชวนคุยด้วย)\n"
        "ค่าเริ่มต้นควรเป็น false เสมอ ถ้าไม่มีอะไรที่น่าพูดแบบชัดเจนจริงๆ ห้ามฝืนพูดเด็ดขาด "
        "ส่วนใหญ่ในรอบนี้ (แต่ละครั้งที่ประเมิน) ไม่ควรพูดเลย ให้พูดเฉพาะตอนที่รู้สึกว่ามันคุ้มค่าจริงๆ "
        "เป้าหมายคร่าวๆคือทั้งวันควรพูดเองไม่กี่ครั้งเท่านั้น (นับรวมทุกห้องในเซิร์ฟเวอร์นี้) ไม่ใช่พูดทุกรอบที่มีการประเมิน "
        "ถ้าเพิ่งพูดเองไปเมื่อไม่นานนี้ หรือเรื่องที่จะพูดดูธรรมดา ไม่ได้ตลก/มีประโยชน์/น่าสนใจเป็นพิเศษ ให้ตอบ false ไปเลย\n"
        f"{voice_hint}\n"
        'ตอบเป็น JSON เท่านั้น ไม่มีคำอธิบายอื่น รูปแบบ:\n'
        '{"want_to_speak": true/false, "message": "...", "confident_enough_for_voice": true/false}'
    )
    try:
        resp = await _client.aio.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        text = (getattr(resp, "text", "") or "").strip()
        text = text.strip("`").replace("json", "", 1).strip() if text.startswith("`") else text
        data = json.loads(text)
        if data.get("want_to_speak") and data.get("message"):
            return {
                "message": str(data["message"])[:1900],
                "confident_enough_for_voice": bool(data.get("confident_enough_for_voice")),
            }
    except Exception as e:
        print(f"⚠️ [Autonomy] ตัดสินใจพลาด: {e}")
    return None


@tasks.loop(minutes=15)
async def autonomy_loop():
    if _bot is None:
        return
    now = time.time()
    # ดูข้อมูลจาก buffer ของ bagley_learning โดยไม่ไปเคลียร์ทิ้ง (ปล่อยให้ learning_loop เคลียร์เอง)
    for channel_id, lines in list(bagley_learning._recent_channel_messages.items()):
        channel = _bot.get_channel(channel_id)
        if channel is None or getattr(channel, "guild", None) is None:
            continue
        guild = channel.guild

        # 🔇 ถูกสั่งให้เงียบไว้ (มีคนบอกให้เงียบ/หุบปาก) — ข้ามกิลด์นี้ไปจนกว่าจะมีคนมาคุยด้วยอีกครั้ง
        if is_guild_silenced(guild.id):
            continue

        # 🎯 [แก้บั๊ก] เดิมบล็อกนี้พิจารณา "ทักเอง" กับทุกห้องแชทที่มีข้อความสะสมไว้ (ห้องไหนก็ได้ที่เคย
        # ถูกเรียก 1 ครั้ง) โดยไม่สนว่าตอนนี้บอทอยู่ในห้องเสียงไหนอยู่หรือเปล่า ทำให้บอทอาจทักขึ้นมาเอง
        # ในห้องแชทที่ไม่เกี่ยวข้องกับที่กำลังนั่งอยู่ห้องเสียงด้วย (เช่น นั่งห้องเสียง A อยู่กับเพื่อน
        # แต่ดันไปทักในห้องแชท #general ที่ไม่มีใครในห้องเสียง A คุยด้วยเลย) ตอนนี้จำกัดให้ "ทักเอง"
        # ได้เฉพาะห้องที่ตรงกับห้องเสียงที่บอทอยู่ตอนนี้เท่านั้น (แชทในตัวห้องเสียงเอง — ห้องเสียงบน
        # ดิสคอร์ดมีแชทของตัวเองในตัวอยู่แล้ว ถือเป็นห้องเดียวกัน) ถ้าบอทไม่ได้อยู่ห้องเสียงไหนในกิลด์นี้
        # เลย ก็จะไม่ทักเองในห้องแชทไหนของกิลด์นี้เลยเช่นกัน
        bot_in_voice = bool(guild.voice_client and guild.voice_client.is_connected())
        if not bot_in_voice:
            continue
        if channel.id != guild.voice_client.channel.id:
            continue

        last = _last_spoke_at.get(channel_id, 0)
        if now - last < _COOLDOWN_SECONDS:
            continue

        # 🚦 เช็คเพดานรวมต่อวันของกิลด์นี้ก่อน (กันรวมๆแล้วถี่เกินไปตอนมีหลายห้อง active พร้อมกัน)
        if not _under_daily_cap(guild.id, now):
            continue

        result = await _decide(guild, lines[-15:], bot_in_voice)
        if not result:
            continue

        message = result["message"]
        try:
            sent_msg = await channel.send(message)
            _last_spoke_at[channel_id] = now
            _record_daily_speak(guild.id, now)
            # 💬 จดจำ message.id ไว้ เผื่อมีคน "ตอบกลับ (reply)" ข้อความนี้ทีหลัง
            # จะได้รู้ว่าคือการตอบกลับแบ็คลี่ ไม่ต้องให้คนพิมพ์เอ่ยชื่อ/แท็กบอทซ้ำอีกรอบ
            _remember_autonomous_message(sent_msg.id)
            print(f"🌱 [Autonomy] พูดเองในห้อง {channel.name}: {message}")
        except Exception as e:
            print(f"⚠️ [Autonomy] พูดเองไม่ได้: {e}")
            continue

        # 🔊 พูดออกเสียงด้วย เฉพาะตอนแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว + AI มั่นใจมากพอ + ผ่าน cooldown เสียงแยก
        if bot_in_voice and result["confident_enough_for_voice"] and _bagley_speak is not None:
            last_voice = _last_voice_spoke_at.get(guild.id, 0)
            if now - last_voice >= _VOICE_COOLDOWN_SECONDS:
                try:
                    await _bagley_speak(guild, message)
                    _last_voice_spoke_at[guild.id] = now
                    print(f"🔊 [Autonomy] พูดออกเสียงเองในกิลด์ {guild.name}: {message}")
                except Exception as e:
                    print(f"⚠️ [Autonomy] พูดออกเสียงเองไม่ได้: {e}")
