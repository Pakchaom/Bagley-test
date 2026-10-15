"""bagley/ai/understanding.py — ทำให้แบ็คลี่ "ฟังรู้เรื่อง" เวลาคนสั่งด้วยภาษาพูด

ปัญหาเดิม: gate.looks_like_command() ดูแค่ "มีคำสำคัญในลิสต์ไหม" ถ้าคนพูดด้วยคำที่ไม่อยู่ในลิสต์
(เช่น "ช่วยจัดเพลงให้หน่อย", "ปรับห้องให้เงียบๆ ที") ข้อความจะถูกมองเป็นแค่คุยเล่นแล้วไม่ถูกส่งต่อ
และ AI ก็ไม่เห็นบริบทแชท จึงตีความ "เขา/เพลงนั้น/อีกที" ไม่ได้

ที่เพิ่ม:
  looks_requestish()     ด่านเร็วไม่ใช้ AI: ประโยคนี้ "มีกลิ่นการขอให้ทำ" ไหม (ลงท้าย หน่อย/ที/ให้/ด้วย, ช่วย..., ขอ..., ...ได้ไหม)
  classify_request()     AI ตัวเล็กแยก chat | command | task (แคชผล ไม่เสียซ้ำเมื่อ router/ephemeral เรียกประโยคเดิม)
  pick_candidates()      ให้ AI เลือกคำสั่งที่เป็นไปได้จากรายการย่อ (ไม่ต้องส่ง schema ทั้ง ~70 ตัว ประหยัดโควต้า)
  fetch_recent_context() ดึงแชทล่าสุดของห้อง (เฉพาะวันนี้) ให้ AI เข้าใจคำอ้างอิง
  Clarification          ถ้าตั้งใจสั่งแน่แต่ข้อมูลขาด -> ถามกลับ 1 ข้อ แล้วรับคำตอบเติมต่อ (ไม่ต้องเรียกชื่อซ้ำ)
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional

# ----------------------------------------------------------------------------
# ด่านเร็ว: ประโยคนี้เหมือนการ "ขอให้ทำ" ไหม
# ----------------------------------------------------------------------------
_REQ_ENDINGS = ("หน่อย", "ที", "ด้วย", "ให้", "เลย", "สิ", "ซิ", "ได้ไหม", "ได้มั้ย", "ได้ป่าว", "ได้ปะ", "ไหวไหม", "ไหวมั้ย",
                "นะ", "หน่อยนะ", "ทีนะ", "ด้วยนะ", "ครับ", "คับ", "หน่อยครับ", "ที่")
_REQ_STARTS = ("ช่วย", "ขอ", "อยาก", "เอา", "ทำ", "จัด", "สร้าง", "สั่ง", "ลอง", "ส่ง", "โพล", "สรุป", "นับ", "สุ่ม", "หา", "บอก", "ดู", "เช็ค", "เช็ก",
               "ตั้ง", "เปลี่ยน", "ย้าย", "เปิด", "ปิด", "แปล", "คิด", "เลือก", "แบ่ง", "รวม", "เรียก")
_REQ_ANYWHERE = ("ช่วย", "ขอให้", "ขอหน่อย", "อยากให้", "รบกวน", "ฝาก", "ได้ไหม", "ได้มั้ย", "ได้ป่าว", "ได้ปะ", "ทำให้", "จัดให้", "ลองทำ", "โหวต", "โพล", "นับ", "สรุป")
_NOISE = re.compile(r"^(555+|ฮ่า+|หึ+|อ๋อ|โอเค|ok|เออ|ครับ|ค่ะ|จ้า|จ้ะ|ขอบคุณ|ขอบใจ|สวัสดี|หวัดดี)+[\s!.~]*$", re.I)


def looks_requestish(text: str) -> bool:
    t = re.sub(r"<@!?\d+>|แบ็คลี่|bagley", "", (text or ""), flags=re.I).strip()
    if len(t) < 4 or _NOISE.match(t):
        return False
    low = t.lower()
    if any(low.startswith(s) for s in _REQ_STARTS):
        return True
    if any(k in low for k in _REQ_ANYWHERE):
        return True
    tail = low.rstrip(" ?!.~ๆ")
    return any(tail.endswith(e) for e in ("หน่อย", "ที", "ด้วย", "ให้", "สิ", "ซิ", "หน่อยนะ", "ทีนะ", "ด้วยนะ", "หน่อยครับ", "ทีครับ", "ให้หน่อย"))


# ----------------------------------------------------------------------------
# AI ตัวเล็ก: chat | command | task
# ----------------------------------------------------------------------------
_CLASSIFY_PROMPT = """Classify a Thai Discord message that was addressed to the bot Bagley. Reply JSON only: {{"kind":"chat"|"command"|"task"}}
- chat: greeting, joking, opinion, question about facts/people/the bot, telling something about themselves, venting, or asking Bagley to just talk/explain/answer.
- command: asks the bot to perform a built-in action: music/play/skip/queue, join/leave voice, move/kick/mute members, rooms, party/teams, reminders/alarms/schedule, YouTube/live chat, memory, stream mode, follow, etc.
- task: asks for some OTHER concrete action inside the Discord server that needs custom steps (make a poll, summarize recent messages, pick/shuffle/random something among people, list who is in voice, count things, build a message from server data).
If unsure between chat and the others, choose chat.
Recent chat (may be empty):
{context}
Message: "{text}" """


async def classify_request(client, text: str, context: str = "") -> str:
    """คืน 'chat' | 'command' | 'task' (ผิดพลาด/ไม่แน่ใจ = chat)"""
    if client is None or not text:
        return "chat"
    prompt = _CLASSIFY_PROMPT.format(text=text.replace('"', "'")[:400], context=(context or "(none)")[-500:])
    data = await client.classify_json(prompt, cache_ttl=300, max_tokens=40)
    kind = (data or {}).get("kind") if isinstance(data, dict) else None
    return kind if kind in ("chat", "command", "task") else "chat"


# ----------------------------------------------------------------------------
# เลือกคำสั่งที่เป็นไปได้จากรายการย่อ (ใช้เมื่อ gate คำสำคัญพลาดแต่เป็น command)
# ----------------------------------------------------------------------------
async def pick_candidates(client, text: str, context: str, catalog: dict, limit: int = 8) -> list:
    """catalog: {ชื่อคำสั่ง: คำอธิบายสั้น} -> คืนชื่อคำสั่งที่น่าจะเกี่ยว (สูงสุด limit)"""
    if not catalog:
        return []
    listing = "\n".join(f"{n}: {d[:50]}" for n, d in catalog.items())
    prompt = (
        "From this list of bot commands pick up to 6 that the Thai message could mean (best first). "
        'Reply JSON only: {"names":["..."]}. If none fits, {"names":[]}.\n'
        f"Commands:\n{listing}\n\nRecent chat:\n{(context or '(none)')[-400:]}\nMessage: \"{text[:300]}\""
    )
    data = await client.classify_json(prompt, cache_ttl=120, max_tokens=120)
    names = (data or {}).get("names") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return []
    return [n for n in names if n in catalog][:limit]


# ----------------------------------------------------------------------------
# บริบทแชท
# ----------------------------------------------------------------------------
async def fetch_recent_context(message, n: int = 6, name_fn=None, bot_user_id: Optional[int] = None) -> str:
    """แชทล่าสุดของห้องนี้ (เฉพาะวันเดียวกับข้อความ) เก่า->ใหม่ ในรูป '[ชื่อ]: ข้อความ' ไม่รวมข้อความปัจจุบัน"""
    lines = []
    try:
        day = message.created_at.date()
        async for m in message.channel.history(limit=n + 2, before=message):
            if m.created_at.date() != day:
                break
            txt = (m.clean_content or "").strip()
            if not txt:
                continue
            who = "แบ็คลี่" if (bot_user_id and m.author.id == bot_user_id) else (
                name_fn(m.author.id, m.author.display_name) if name_fn else m.author.display_name)
            lines.append(f"[{who}]: {txt[:200]}")
            if len(lines) >= n:
                break
    except Exception:
        return ""
    return "\n".join(reversed(lines))


# ----------------------------------------------------------------------------
# ถามกลับ (clarification) แบบทั่วไป
# ----------------------------------------------------------------------------
_PENDING: dict = {}   # (channel_id, user_id) -> {"original":..., "question":..., "expires":..., "tries":int}
CLARIFY_TTL = 120
_last_clarify: dict = {}


def can_clarify(key) -> bool:
    """กันถามกวน: คนเดียวถามกลับได้ไม่เกิน 1 ครั้งต่อ 20 วินาที"""
    now = time.time()
    if now - _last_clarify.get(key, 0) < 20:
        return False
    _last_clarify[key] = now
    return True


def set_pending(key, original: str, question: str):
    _PENDING[key] = {"original": original, "question": question, "expires": time.time() + CLARIFY_TTL, "tries": 0}


def get_pending(key) -> Optional[dict]:
    p = _PENDING.get(key)
    if not p:
        return None
    if p["expires"] < time.time():
        _PENDING.pop(key, None)
        return None
    return p


def clear_pending(key):
    _PENDING.pop(key, None)


def combine_with_pending(pending: dict, answer: str) -> str:
    """รวมคำสั่งเดิม + คำตอบ เป็นข้อความเดียวให้ router ตีความใหม่ทั้งก้อน"""
    return f'{pending["original"]} ({pending["question"]} -> {answer})'


# ----------------------------------------------------------------------------
# คำอ้างอิงตัวผู้พูดเอง
# ----------------------------------------------------------------------------
SELF_WORDS = {"ฉัน", "ผม", "เรา", "กู", "หนู", "ตัวเอง", "ตัวฉัน", "ตัวผม", "ข้า", "me", "myself", "i"}


def is_self_reference(value: str) -> bool:
    return (value or "").strip().lower() in SELF_WORDS


def value_grounded(value: str, message_text: str, context_text: str = "") -> bool:
    """ค่าพารามิเตอร์ที่ AI แกะมา 'มีที่มาจริง' ไหม — อยู่ในข้อความ หรือในแชทล่าสุด หรือเป็นคำอ้างตัวเอง
    (ขยายจากเดิมที่ยอมเฉพาะในข้อความ เพื่อให้ 'ย้ายเขาไปห้องนั้น' ที่อ้างบริบทใช้ได้ แต่ยังกันการกุค่า)"""
    v = re.sub(r"\s+", "", str(value).lower())
    if not v or is_self_reference(str(value)):
        return True
    for src in (message_text, context_text):
        if v in re.sub(r"\s+", "", (src or "").lower()):
            return True
    return False
