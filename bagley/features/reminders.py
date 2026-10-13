"""bagley/features/reminders.py — ตั้งเตือนตัวเอง/เพื่อนจากการพิมพ์คุย (รอคำตอบเวลา)"""
import re as regex_lib
from datetime import datetime

from bagley.ai.classifiers import _ai_parse_time_of_day
from bagley.core import state
from bagley.data.storage import load_user_data, save_user_data


# 🛡️ [กันบั๊กชนกัน] คำ/รูปแบบที่บ่งบอกว่าข้อความนี้คือ "คำสั่งใหม่แยกต่างหาก" ไม่ใช่แค่คำตอบเวลาเฉยๆ
# ต่อคำถาม "กี่โมงดีครับ" ที่เพิ่งถามไป (กันไม่ให้ pending_remember_reminders ไปแย่งข้อความที่ควรให้
# ระบบอื่นจัดการแทน เช่น [ส่วนที่ 2] ระบบเตือนตัวเอง/เพื่อนแบบพิมพ์ตรงๆ, [ส่วนที่ 3] ฝากข้อความ,
# หรือ bagley_rules ที่จะจดจำเป็นกฎ/ข้อมูลใหม่อีกที)
_PENDING_REMINDER_SKIP_KEYWORDS = ("ฝากบอก", "บอกเพื่อนว่า", "จำไว้ว่า", "จำไว้", "จดไว้")


def _looks_like_new_command_not_time_answer(text: str) -> bool:
    lowered = text.lower()
    if "เตือน" in lowered and ("ตอน" in lowered or "เวลา" in lowered):
        return True  # เข้าเงื่อนไขเดียวกับ [ส่วนที่ 2]/ai_command_router.looks_like_personal_reminder
    return any(kw in lowered for kw in _PENDING_REMINDER_SKIP_KEYWORDS)


def _extract_explicit_time(text: str) -> str | None:
    """หาเวลารูปแบบตัวเลขชัดๆ เช่น '21:00' หรือ '21.00' จากข้อความ คืน None ถ้าไม่เจอ"""
    match = regex_lib.search(r'(\d{1,2}[:.]\d{2})', text)
    if not match:
        return None
    return match.group(1).replace('.', ':').zfill(5)


def _save_self_reminder(user_id, time_str: str, content: str, channel_id):
    user_data = load_user_data()
    if "reminders" not in user_data:
        user_data["reminders"] = []
    user_data["reminders"].append({
        "user_id": str(user_id),
        "time": time_str,
        "content": content,
        "channel_id": str(channel_id),
        "is_notified": False
    })
    save_user_data(user_data)


async def handle_remembered_reminder(message, event_text: str, get_realtime_name=None):
    """เรียกตอน bagley_rules จัดหมวดข้อความ 'จำไว้ว่า...' ว่าเป็น REMINDER (เช่น 'จำไว้ว่าพรุ่งนี้มีสอบ')
    ถ้าในข้อความมีเวลาระบุชัดอยู่แล้ว ให้บันทึกเตือนทันที ถ้าไม่มี ให้ถามกลับว่ากี่โมงแล้วรอคำตอบถัดไป"""
    caller_name = get_realtime_name(message.author.id, message.author.display_name) if get_realtime_name else message.author.display_name

    explicit_time = _extract_explicit_time(message.content)
    if explicit_time:
        _save_self_reminder(message.author.id, explicit_time, event_text, message.channel.id)
        await message.reply(
            f"รับทราบครับคุณ {caller_name}! จำไว้แล้วว่า **\"{event_text}\"** เดี๋ยวผมจะเตือนตอน {explicit_time} ให้เองนะครับ ⏰"
        )
        return

    state.pending_remember_reminders[(message.channel.id, message.author.id)] = {
        "content": event_text,
        "asked_at": datetime.now(),
    }
    await message.reply(
        f"จำไว้แล้วครับว่า **\"{event_text}\"** แล้วอยากให้แบ็คลี่เตือนตอนกี่โมงดีครับ? "
        "พิมพ์เวลาบอกมาได้เลยครับ (เช่น '21:00')"
    )


async def try_finish_pending_reminder(message, pending: dict, get_realtime_name=None) -> str | None:
    """ตรวจว่าข้อความล่าสุด (คำตอบต่อคำถาม 'กี่โมงดีครับ') มีเวลาบอกมาให้หรือยัง ถ้ามีให้บันทึกเตือนจริง
    แล้วคืนข้อความ ack ให้ reply ถ้ายังจับเวลาจากข้อความนี้ไม่ได้ คืน None (ปล่อยข้อความไหลไปทำงานปกติต่อ
    เผื่อเป็นข้อความอื่นที่ไม่เกี่ยวข้องกับคำถามที่ถามไป)"""
    # 🛡️ [กันบั๊กชนกัน] ถ้าข้อความนี้ดูเหมือนเป็น "คำสั่งใหม่ที่ตั้งใจแยกต่างหาก" อยู่แล้ว (เช่น พิมพ์
    # "เตือนฉันตอน 15:00 ว่ามีประชุม" หรือ "ฝากบอกว่าไปกินข้าว 15:00" ใหม่ทั้งดุ้น) อย่าไปหยิบเวลาในนั้น
    # มาปิดคำถามค้างเก่าให้เองแบบเงียบๆ เพราะจะไปแย่งข้อความที่ควรให้ระบบอื่น ([ส่วนที่ 2]/[ส่วนที่ 3]/
    # bagley_rules) จัดการแทน ปล่อยให้ไหลไปทำงานปกติต่อดีกว่า (คำถามเก่าจะยังค้างรอจนกว่าจะหมดเวลา
    # หรือมีคำตอบที่เป็นแค่เวลาสั้นๆ จริงๆ มาให้)
    if _looks_like_new_command_not_time_answer(message.content):
        return None

    time_str = _extract_explicit_time(message.content) or await _ai_parse_time_of_day(message.content)
    if not time_str:
        return None

    caller_name = get_realtime_name(message.author.id, message.author.display_name) if get_realtime_name else message.author.display_name
    _save_self_reminder(message.author.id, time_str, pending["content"], message.channel.id)
    return (
        f"รับทราบครับคุณ {caller_name}! ตั้งเตือนเรื่อง **\"{pending['content']}\"** ไว้ตอน {time_str} ให้เรียบร้อยแล้วครับ ⏰"
    )
