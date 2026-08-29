# ============================================================
# 🧠 Bagley Learning — เรียนรู้จากบทสนทนารอบข้างอัตโนมัติ
# ============================================================
# วิธีติดตั้ง (ใน bot.py):
#   1. import bagley_learning
#   2. ใน on_ready: bagley_learning.configure(bot, client, conn)
#                    bagley_learning.init_learning_db(conn)
#                    bagley_learning.learning_loop.start()
#   3. ใน on_message (ทุกข้อความที่ไม่ใช่บอทพูด):
#         bagley_learning.track_message(message.channel.id, message.author.display_name, message.content)
#   4. ตอนสร้าง prompt คุยกับ AI ปกติ ดึง insight มาแปะเพิ่มได้:
#         insights = bagley_learning.get_recent_insights(guild_id)
# ============================================================

import sqlite3
from discord.ext import tasks

_bot = None
_client = None
_conn = None
_MAX_MESSAGES_PER_SCAN = 30

# เก็บข้อความล่าสุดแบบ rolling ต่อห้อง — อยู่บน RAM เท่านั้น ไม่ persist ตั้งใจ
_recent_channel_messages: dict[int, list[str]] = {}

# 🏠 "ห้องที่บอทเคยเกี่ยวข้องด้วยจริงๆ" (เคยถูกเรียก/เคยคุยด้วยตรงๆ อย่างน้อย 1 ครั้ง) —
# ใช้กรองว่าห้องไหนบ้างที่ควรสะสมข้อความไว้ให้ระบบเรียนรู้/ทักเอง (bagley_autonomy) พิจารณา
# กันไม่ให้ไปอ่าน/พูดในห้องอื่นที่บอทไม่เคยเกี่ยวข้องด้วยเลย (เช่นห้องที่แค่มีคนคุยกันเอง บอทไม่เคยถูกเรียก)
# persist ลง DB ด้วย เพื่อไม่ให้รีเซ็ตทุกครั้งที่บอทรีสตาร์ท
_active_channel_ids: set[int] | None = None


def configure(bot, client, conn):
    global _bot, _client, _conn
    _bot = bot
    _client = client
    _conn = conn


def init_learning_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learned_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            insight TEXT NOT NULL,
            learned_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_active_channels (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            marked_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _load_active_channels_cache():
    global _active_channel_ids
    if _conn is None:
        _active_channel_ids = set()
        return
    rows = _conn.execute("SELECT channel_id FROM learning_active_channels").fetchall()
    _active_channel_ids = {r[0] for r in rows}


def mark_channel_active(channel_id: int, guild_id: int):
    """เรียกตอนบอทถูกเรียก/คุยด้วยตรงๆ ในห้องนี้ (ดู bot.py on_message) — ทำเครื่องหมายว่าห้องนี้
    เป็นห้องที่บอท 'อยู่' จริงๆ จากนี้ไปห้องนี้จะถูกสะสมข้อความให้ระบบเรียนรู้/ทักเองพิจารณาได้
    (ไม่มีผลอะไรถ้าห้องนี้ถูกทำเครื่องหมายไว้แล้ว กันยิง DB โดยไม่จำเป็น)"""
    global _active_channel_ids
    if _active_channel_ids is None:
        _load_active_channels_cache()
    if channel_id in _active_channel_ids:
        return
    _active_channel_ids.add(channel_id)
    if _conn is not None:
        _conn.execute(
            "INSERT OR REPLACE INTO learning_active_channels (channel_id, guild_id, marked_at) VALUES (?, ?, datetime('now'))",
            (channel_id, guild_id),
        )
        _conn.commit()
        print(f"🏠 [Learning] channel={channel_id} ถูกทำเครื่องหมายว่าบอทเกี่ยวข้องด้วยแล้ว — เริ่มสะสมข้อความห้องนี้")


def is_channel_active(channel_id: int) -> bool:
    if _active_channel_ids is None:
        _load_active_channels_cache()
    return channel_id in _active_channel_ids


def track_message(channel_id: int, author_name: str, content: str, image_caption: str | None = None):
    """เรียกจาก on_message ทุกครั้ง เพื่อสะสมบทสนทนาไว้ให้ AI สรุปเป็นระยะ —
    สะสมเฉพาะห้องที่บอทเคยถูกเรียก/เกี่ยวข้องด้วยจริงๆ เท่านั้น (ดู mark_channel_active) กันไม่ให้
    ระบบเรียนรู้/ทักเองไปยุ่งกับห้องที่บอทไม่เคยเกี่ยวข้องด้วยเลย

    🖼️ image_caption (ใหม่): ถ้ามีคนแนบรูปภาพมาด้วย (ไม่ว่าจะพิมพ์ข้อความมาด้วยหรือไม่) ฝั่ง bot.py
    จะสรุปคำบรรยายรูปสั้นๆ ด้วย Gemini vision แล้วส่งเข้ามาทาง argument นี้ — เก็บแนบเข้าไปในบรรทัด
    บทสนทนาเดียวกัน เพื่อให้ทั้ง bagley_learning (สรุป insight) และ bagley_autonomy (ตัดสินใจ "ชวนคุย"
    เอง) มองเห็นว่ามีรูปภาพอะไรถูกโพสต์ไปด้วย ไม่ใช่แค่ข้อความล้วนๆ เหมือนเดิม"""
    line = None
    if content and content.strip():
        line = f"{author_name}: {content}"
        if image_caption:
            line += f" [แนบรูปภาพมาด้วย — ในรูปคือ: {image_caption}]"
    elif image_caption:
        line = f"{author_name}: [ส่งรูปภาพมาเฉยๆ ไม่มีข้อความ — ในรูปคือ: {image_caption}]"

    if not line:
        return
    if not is_channel_active(channel_id):
        return
    buf = _recent_channel_messages.setdefault(channel_id, [])
    buf.append(line)
    if len(buf) > _MAX_MESSAGES_PER_SCAN:
        del buf[: len(buf) - _MAX_MESSAGES_PER_SCAN]


def get_recent_insights(guild_id: int, limit: int = 5) -> list[str]:
    """ดึง insight ล่าสุดของกิลด์นี้ เอาไปแปะใน system prompt ตอนคุยกับ user ได้"""
    if _conn is None:
        return []
    rows = _conn.execute(
        "SELECT insight FROM learned_context WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
        (guild_id, limit),
    ).fetchall()
    return [r[0] for r in rows]


async def _summarize_channel(guild_id: int, channel_id: int, lines: list[str]):
    if not lines:
        return
    prompt = (
        "นี่คือข้อความล่าสุดในห้องแชทดิสคอร์ดกลุ่มหนึ่ง:\n"
        + "\n".join(lines)
        + "\n\nสรุปเป็น 1 ประโยคสั้นๆ ว่ามีอะไรที่บอทควร 'จดจำ' เกี่ยวกับคนกลุ่มนี้ "
          "(นิสัย, ความสนใจ, มีมที่ใช้บ่อย, เรื่องที่คุยกันบ่อย) "
          "ถ้าไม่มีอะไรน่าจดจำเลย ให้ตอบว่า NONE เท่านั้น อย่าตอบอย่างอื่นเลย"
    )
    try:
        resp = await _client.aio.models.generate_content(
            model="gemini-3.1-flash-lite", contents=prompt
        )
        text = (getattr(resp, "text", "") or "").strip()
        if text and text.upper() != "NONE":
            _conn.execute(
                "INSERT INTO learned_context (guild_id, insight) VALUES (?, ?)",
                (guild_id, text),
            )
            _conn.commit()
            print(f"🧠 [Learning] guild={guild_id} จดจำ: {text}")
    except Exception as e:
        print(f"⚠️ [Learning] สรุปบทสนทนาพลาด: {e}")


@tasks.loop(minutes=30)
async def learning_loop():
    """สแกนห้องที่มีข้อความสะสมไว้ ทุก 30 นาที แล้วให้ AI สรุปเป็น insight เก็บลง DB"""
    if _bot is None:
        return
    snapshot = dict(_recent_channel_messages)
    _recent_channel_messages.clear()
    for channel_id, lines in snapshot.items():
        channel = _bot.get_channel(channel_id)
        if channel is None or getattr(channel, "guild", None) is None:
            continue
        await _summarize_channel(channel.guild.id, channel_id, lines)
