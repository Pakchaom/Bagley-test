"""bagley/ai/humanize.py — ทำให้แบ็คลี่ "ดูเป็นคน" มากขึ้น โดยไม่เปลี่ยนบุคลิกหลักใน persona.py

ใส่ 3 อย่างเข้า prompt แชท (ผ่านพารามิเตอร์ extra ของ persona.chat_prompt):
  1) mood_block()         อารมณ์/พลังงานตอนนี้ของแบ็คลี่ในเซิร์ฟเวอร์นี้ (ง่วงตอนดึก, ดีใจหลังโดนชม, หงุดหงิดหลังโดนสแปม/ด่า)
                          ค่อยๆ จางกลับสู่ปกติเอง ไม่ค้าง
  2) familiarity_block()  ความสนิทกับคนที่คุยด้วย (ดึงจากสถิติ trust เดิม) — คนใหม่สุภาพกว่า คนสนิทแซวแรงขึ้นได้
  3) pace()               หน่วงจังหวะตอบให้ไม่ "ทันที" เกินเหมือนเครื่อง (ถ้าโมเดลตอบเร็วมาก ให้พิมพ์ค้างอีกนิด)

ทั้งหมดไม่ใช้ AI เพิ่ม (ไม่กินโควต้า) และเก็บในแรมเท่านั้น
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Optional

try:
    import zoneinfo
    _BKK = zoneinfo.ZoneInfo("Asia/Bangkok")
except Exception:  # pragma: no cover
    _BKK = None

_PRAISE = ("เก่งมาก", "เก่งจัง", "ขอบคุณ", "ขอบใจ", "น่ารัก", "เทพ", "สุดยอด", "ชอบแบ็คลี่", "รักแบ็คลี่", "thank", "good bot", "love you", "ดีมาก", "เจ๋ง")
_RUDE = ("โง่", "ห่วย", "ขยะ", "เกลียด", "ไร้ประโยชน์", "stupid", "useless", "trash", "หุบปาก")

# สถานะอารมณ์ต่อกิลด์: warmth -1..+1 (ค่อยๆ จางกลับ 0), recent = เวลาข้อความล่าสุดที่คุยด้วย
_state: dict = {}
_HALF_LIFE = 25 * 60  # วินาที


def _now() -> datetime:
    return datetime.now(_BKK) if _BKK else datetime.now()


def _get(guild_key) -> dict:
    return _state.setdefault(guild_key, {"warmth": 0.0, "t": time.time(), "recent": []})


def _decay(st: dict):
    now = time.time()
    dt = now - st["t"]
    if dt > 0:
        st["warmth"] *= 0.5 ** (dt / _HALF_LIFE)
        st["t"] = now


def note_user_message(guild_id: Optional[int], text: str):
    """เรียกทุกครั้งที่มีคนคุยกับแบ็คลี่ — ปรับอารมณ์จากสิ่งที่ได้ยิน (heuristic ล้วน ไม่ใช้ AI)"""
    st = _get(guild_id)
    _decay(st)
    low = (text or "").lower()
    if any(k in low for k in _PRAISE):
        st["warmth"] = min(1.0, st["warmth"] + 0.35)
    if any(k in low for k in _RUDE):
        st["warmth"] = max(-1.0, st["warmth"] - 0.4)
    now = time.time()
    st["recent"] = [t for t in st["recent"] if now - t < 60] + [now]
    if len(st["recent"]) >= 8:           # ถูกรัวใน 1 นาที = หงุดหงิดนิดๆ
        st["warmth"] = max(-1.0, st["warmth"] - 0.15)


def mood_block(guild_id: Optional[int]) -> str:
    st = _get(guild_id)
    _decay(st)
    h = _now().hour
    parts = []
    if 0 <= h < 5:
        parts.append("very late at night: a little sleepy and a bit more rambling/honest than usual")
    elif 5 <= h < 8:
        parts.append("early morning: slightly groggy, needs 'coffee' (electricity)")
    elif 12 <= h < 14:
        parts.append("lunch hour: mentions being hungry is allowed (you can't eat)")
    elif 22 <= h <= 23:
        parts.append("late evening: winding down")
    w = st["warmth"]
    if w > 0.45:
        parts.append("you're in a notably good mood (someone was nice to you recently): warmer, a bit more playful")
    elif w > 0.15:
        parts.append("mildly pleased")
    elif w < -0.45:
        parts.append("a bit irritated lately: drier and shorter, but still helpful and never cruel")
    elif w < -0.15:
        parts.append("slightly on edge")
    if not parts:
        return ""
    return "Your current mood (let it color tone subtly, never announce it): " + "; ".join(parts) + ".\n"


def familiarity_block(user_id: int, guild_id: Optional[int]) -> str:
    try:
        from bagley.features import trust
        if guild_id is None:
            return ""
        count, days = trust.get_stats(user_id, guild_id)
    except Exception:
        return ""
    if days is None or count < 5:
        return "Familiarity: you barely know this person — friendly, a touch more polite, light teasing only.\n"
    if count < 50:
        return f"Familiarity: you've chatted a fair bit ({count} times) — relaxed, easy banter.\n"
    return (f"Familiarity: close regular (about {count} chats over {days} days) — you can tease more freely, "
            "use inside jokes and shared history from memory, and talk like an old friend.\n")


def reaction_delay_target(text: str) -> float:
    """เวลาขั้นต่ำที่ 'คนจริง' น่าจะใช้พิมพ์ข้อความนี้ (วินาที) — สั้นก็ไม่เร็วเกินไป ยาวก็ไม่ช้าเกินไป"""
    n = len(text or "")
    return max(0.8, min(3.2, 0.7 + n * 0.018)) * random.uniform(0.85, 1.2)


async def pace(started_at: float, text: str):
    """เรียกหลังได้คำตอบจาก AI แล้ว (ภายใน typing indicator) — หน่วงเฉพาะส่วนที่ขาด ไม่เพิ่มเวลาถ้าช้าอยู่แล้ว"""
    remaining = reaction_delay_target(text) - (time.time() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)
