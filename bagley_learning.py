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
    conn.commit()


def track_message(channel_id: int, author_name: str, content: str):
    """เรียกจาก on_message ทุกครั้ง เพื่อสะสมบทสนทนาไว้ให้ AI สรุปเป็นระยะ"""
    if not content or not content.strip():
        return
    buf = _recent_channel_messages.setdefault(channel_id, [])
    buf.append(f"{author_name}: {content}")
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
