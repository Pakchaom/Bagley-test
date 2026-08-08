# ============================================================
# 🤝 Bagley Trust — วัด "ความคุ้นเคย" ของแต่ละคนจากการคุยกับแบ็คลี่จริงๆ
# ============================================================
# ใช้ต่อยอด ephemeral_tools.py — ให้คนที่คุ้นเคยพอ (ไม่ต้องอยู่ใน list ที่ admin เพิ่มมือ)
# สามารถสั่งสร้างความสามารถชั่วคราวได้ด้วย
#
# 🔒 ทำไมต้องเช็ค 2 เงื่อนไขพร้อมกัน (จำนวนครั้ง + จำนวนวันที่รู้จัก):
#   ถ้าเช็คแค่ "จำนวนครั้งที่คุย" อย่างเดียว คนร้ายพิมพ์สแปมคุยรัวๆวันเดียวก็ปั๊มยอดผ่านเกณฑ์ได้
#   การบวกเงื่อนไข "ต้องรู้จักกันมาแล้วอย่างน้อย N วัน" ทำให้ปั๊มยอดข้ามคืนไม่ได้ ต้องใช้เวลาจริง
#   (ยังไม่ใช่ระบบที่กันโกง 100% แต่ลดความเสี่ยงจากคนแปลกหน้าที่โผล่มาแล้วรีบขอสิทธิ์ทันที)
#
# วิธีติดตั้ง (ใน bot.py):
#   1. import bagley_trust
#   2. ใน on_ready: bagley_trust.configure(conn)
#                    bagley_trust.init_trust_db(conn)
#   3. ใน on_message ทุกครั้งที่ "ข้อความนี้เอ่ยถึง/คุยกับแบ็คลี่ตรงๆ"
#      (ใช้เงื่อนไขเดียวกับ is_message_addressed_to_bagley ที่มีอยู่แล้ว):
#         if message.guild:
#             bagley_trust.track_interaction(message.author.id, message.guild.id)
# ============================================================

import time
from datetime import datetime

_conn = None

# เกณฑ์ขั้นต่ำ — ต้องผ่าน "ทั้งคู่" ถึงจะถือว่าคุ้นเคยพอ ปรับตัวเลขได้ตามความสบายใจ
MIN_INTERACTIONS = 50
MIN_DAYS_KNOWN = 3

# กันสแปมพิมพ์รัวๆเพื่อปั๊มยอด — นับเพิ่มได้อย่างมาก 1 ครั้งต่อคนต่อ 30 วินาที
_INTERACTION_COOLDOWN_SECONDS = 30
_last_counted_at: dict[tuple, float] = {}


def configure(conn):
    global _conn
    _conn = conn


def init_trust_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_trust (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            interaction_count INTEGER DEFAULT 0,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, guild_id)
        )
    """)
    conn.commit()


def track_interaction(user_id: int, guild_id: int):
    """เรียกเฉพาะตอน user คุยกับแบ็คลี่ตรงๆ (เอ่ยชื่อ/mention) — ไม่ใช่ทุกข้อความในห้อง"""
    if _conn is None:
        return
    key = (user_id, guild_id)
    now = time.time()
    if now - _last_counted_at.get(key, 0) < _INTERACTION_COOLDOWN_SECONDS:
        return
    _last_counted_at[key] = now

    _conn.execute("""
        INSERT INTO user_trust (user_id, guild_id, interaction_count, last_seen)
        VALUES (?, ?, 1, datetime('now'))
        ON CONFLICT(user_id, guild_id) DO UPDATE SET
            interaction_count = interaction_count + 1,
            last_seen = datetime('now')
    """, (user_id, guild_id))
    _conn.commit()


def get_stats(user_id: int, guild_id: int):
    """คืน (จำนวนครั้งที่คุย, จำนวนวันที่รู้จักกันมา) — ถ้าไม่เคยคุยเลยคืน (0, None)"""
    if _conn is None:
        return 0, None
    row = _conn.execute(
        "SELECT interaction_count, first_seen FROM user_trust WHERE user_id=? AND guild_id=?",
        (user_id, guild_id),
    ).fetchone()
    if not row:
        return 0, None
    count, first_seen = row
    days_known = (datetime.utcnow() - datetime.fromisoformat(first_seen)).days
    return count, days_known


def is_trusted_for_dynamic_tools(user_id: int, guild_id: int) -> bool:
    """เช็คว่าคนนี้ 'คุ้นเคยพอ' ให้สั่งสร้างความสามารถชั่วคราวได้เองมั้ย โดยไม่ต้องอยู่ใน allowlist"""
    count, days_known = get_stats(user_id, guild_id)
    if days_known is None:
        return False
    return count >= MIN_INTERACTIONS and days_known >= MIN_DAYS_KNOWN


def trust_summary_text(user_id: int, guild_id: int) -> str:
    """ข้อความสรุปสถานะ ใช้ตอบเวลามีคนถามว่าตัวเองผ่านเกณฑ์รึยัง"""
    count, days_known = get_stats(user_id, guild_id)
    if days_known is None:
        return "ยังไม่มีประวัติคุยกับแบ็คลี่เลยครับ"
    passed = is_trusted_for_dynamic_tools(user_id, guild_id)
    status = "✅ ผ่านเกณฑ์แล้ว" if passed else "❌ ยังไม่ผ่านเกณฑ์"
    return (
        f"{status} — คุยกันมาแล้ว {count}/{MIN_INTERACTIONS} ครั้ง, "
        f"รู้จักกันมา {days_known}/{MIN_DAYS_KNOWN} วัน"
    )
