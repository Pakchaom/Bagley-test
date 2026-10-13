"""bagley/data/storage.py — อ่าน/เขียนไฟล์ JSON (ตั้งค่า, ข้อมูลผู้ใช้, สถิติห้องเสียง, แจ้งเตือน) และชื่อที่จำไว้"""
import json
import os
import re as regex_lib
import secrets
from datetime import datetime, timedelta

from bagley.core.config import bangkok_tz
from bagley.core.logutil import print


def save_settings(data):
    with open('server_settings.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def load_settings():
    # This is for testing
    try:
        with open('server_settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_user_data(data):
    with open('user_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_user_data():
    try:
        with open('user_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# ============================================================
# 🗓️ ระบบช่วยจัดการ "ตารางนัดหมาย" (schedules) กลาง
# แก้บั๊ก: เดิม /remind (ทั้งพิมพ์ตรงๆ และผ่าน AI Command Router เวลาพิมพ์
# "เตือนฉันตอน...") ถ้าไม่ได้ระบุวันที่มาชัดเจน จะเก็บคำว่า "วันนี้" ดิบๆ
# ลงไปเป็นค่า date ตรงๆ โดยไม่แปลงเป็นวันที่จริง ทำให้:
#   - /schedule_list โชว์วันที่ผิดเพี้ยน (ขึ้นคำว่า "วันนี้" แทนวันที่จริง)
#   - ระบบเคลียร์ตารางที่หมดเวลาอัตโนมัติ (check_expired_schedules) พาร์สไม่ได้
#     เลยค้างอยู่ในตารางไปตลอด ไม่มีวันถูกลบออกเอง
# ฟังก์ชันตรงนี้เลยทำหน้าที่แปลงค่าวันที่ให้เป็น YYYY-MM-DD เสมอ ไม่ว่าใครจะพิมพ์มา
# แบบไหน (วันนี้ / พรุ่งนี้ / มะรืน / เลขวันสั้นๆ / หรือรูปแบบมาตรฐานอยู่แล้ว)
# ============================================================
_RELATIVE_DATE_KEYWORDS = {
    "มะรืนนี้": 2, "มะรืน": 2, "day after tomorrow": 2,
    "พรุ่งนี้": 1, "tomorrow": 1,
    "วันนี้": 0, "today": 0,
}


def _normalize_schedule_date(raw_date: str, now: datetime) -> str:
    """แปลงค่า 'date' ที่พิมพ์มาแบบไม่เป็นทางการ (เช่น 'วันนี้', 'พรุ่งนี้', หรือแค่ตัวเลขวันที่)
    ให้กลายเป็นรูปแบบ YYYY-MM-DD เสมอ กันไม่ให้ค้างเป็นข้อความดิบจนพัง /schedule_list,
    /delete_schedule และระบบเคลียร์ตารางที่หมดเวลาอัตโนมัติ (check_expired_schedules)"""
    clean_date = (raw_date or "").strip()
    lowered = clean_date.lower()

    # คำที่หมายถึงวันแบบสัมพัทธ์ (วันนี้ / พรุ่งนี้ / มะรืน) เช็คยาวไปสั้นกันคำว่า "มะรืน" ไปแมตช์ก่อน "วันนี้" ผิดจุด
    for keyword, offset in _RELATIVE_DATE_KEYWORDS.items():
        if keyword in lowered:
            return (now + timedelta(days=offset)).strftime("%Y-%m-%d")

    # ตัวเลขวันที่สั้น ๆ เช่น '11' -> เดือน/ปีปัจจุบัน (หรือเดือนถัดไปถ้าผ่านมาแล้ว)
    if len(clean_date) <= 2 and clean_date.isdigit():
        try:
            day_val = int(clean_date)
            if day_val < now.day:
                first_of_next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
                target_date = first_of_next_month.replace(day=day_val)
            else:
                target_date = now.replace(day=day_val)
            return target_date.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"DEBUG: 📅 จัดฟอร์แมตวันที่แบบสั้นพลาด: {e}")
            return now.strftime("%Y-%m-%d")

    # ถ้าเป็น YYYY-MM-DD ที่ถูกต้องอยู่แล้ว ให้ใช้ตามนั้นเลย
    try:
        datetime.strptime(clean_date, "%Y-%m-%d")
        return clean_date
    except Exception:
        pass

    # พาร์สรูปแบบอื่นไม่ได้เลย (เช่น AI Router ส่งคำแปลกๆ มา) กันพังไว้ก่อนด้วยการใช้วันนี้จริงๆ แทน
    print(f"⚠️ [Schedule] แปลงวันที่ '{raw_date}' ไม่ได้ ใช้วันนี้แทนไปก่อนครับ")
    return now.strftime("%Y-%m-%d")


def _schedule_sort_key(s):
    """เรียงตารางนัดตามวันที่ + เวลาก่อน-หลัง (นัดที่ใกล้ถึงก่อนจะขึ้นก่อน) ใช้ร่วมกันทั้ง
    /schedule_list และ /delete_schedule"""
    try:
        return datetime.strptime(f"{s.get('date', '')} {s.get('time', '')}", "%Y-%m-%d %H:%M")
    except Exception:
        return datetime.max  # ถ้าเวลาไม่ได้เป็นรูปแบบมาตรฐาน (เช่น '3 ทุ่ม') ให้ไปต่อท้ายสุด


def _ensure_schedule_ids(schedules: list) -> bool:
    """เผื่อรายการตารางนัดเก่า (ที่บันทึกไว้ก่อนมีระบบ id) ยังไม่มี 'id' ให้สุ่มใส่ให้ครบทุกอัน
    จะได้เอาไปใช้อ้างอิงตอนลบผ่าน /delete_schedule ได้แม่นยำ ไม่มีทางชนกัน
    คืนค่า True ถ้ามีการแก้ไข (ต้อง save_user_data ต่อ)"""
    changed = False
    for s in schedules:
        if not s.get("id"):
            s["id"] = secrets.token_hex(4)
            changed = True
    return changed


#  ฟังก์ชันกลางสำหรับลบข้อมูล (ทำหน้าที่ลบอย่างเดียว)
def เคลียร์ข้อมูลพรรคพวก(user_id: str):
    data_memory = load_user_data()
    if user_id in data_memory:
        del data_memory[user_id]
        save_user_data(data_memory)
        return True
    return False


def load_voice_data():
    file_path = 'voice_stats.json'
    # 🛠️ หากหาไฟล์ไม่เจอในคอมบริษัท ให้สร้างไฟล์ปีกกาเปล่า {} ขึ้นมาทันทีคัปพ้ม
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"❌ ไม่สามารถสร้างไฟล์ voice_stats.json ชั่วคราวได้: {e}")
        return {}
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # 🛡️ ดักจับกรณีโครงสร้างไฟล์ JSON พัง (ป้องกันบั๊ก Extra data) ให้รีเซ็ตกลับเป็นไฟล์เปล่าทันที
        print("⚠️ โครงสร้างไฟล์ voice_stats.json พัง/ซ้อนกัน! กำลังทำการล้างเป็นไฟล์เริ่มต้น...")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        except:
            pass
        return {}
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดอื่นในการอ่านไฟล์: {e}")
        return {}


def save_voice_data(data):
    try:
        # บันทึกไฟล์ข้อมูลอย่างปลอดภัยแบบเคลียร์ของเดิมทิ้งก่อนเขียนใหม่คัป
        with open('voice_stats.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ ไม่สามารถบันทึกข้อมูลลง voice_stats.json ได้: {e}")


def _get_saved_voice_name(member):
    """คืนชื่อที่ควรใช้บันทึก/เรียกในสถิติห้องเสียง (เอาฉายาที่บันทึกไว้ก่อน ถ้าไม่มีก็ใช้ชื่อในเซิร์ฟเวอร์)"""
    data_memory = load_user_data()
    special_info = data_memory.get(str(member.id))
    if special_info and isinstance(special_info, dict):
        saved_name = special_info.get("nickname", member.display_name)
    elif special_info:
        saved_name = special_info
    else:
        saved_name = member.display_name
    if saved_name == "ยังไม่ระบุ":
        saved_name = member.display_name
    return saved_name


def _register_voice_entry(member):
    """บันทึกทันทีว่าสมาชิกคนนี้แวะเข้าห้องเสียงวันนี้แล้ว (แม้ยังไม่ออกจากห้องก็ให้ขึ้นชื่อในรายงาน
    'ใครเข้าห้องเสียงบ้าง' ได้เลย) โดยจะจำเวลาที่เข้าห้องครั้งแรกของวันนั้นไว้ด้วย (first_join)
    ไม่ได้แตะ total_time ตรงนี้ - ส่วนนั้นยังคงบวกตอน 'ออก' จากห้องเหมือนเดิม"""
    try:
        user_id = str(member.id)
        today_str = datetime.now().strftime("%Y-%m-%d")
        data = load_voice_data()
        if data.get("date") != today_str:
            data = {"date": today_str, "stats": {}}

        stats = data.setdefault("stats", {})
        guild_id_str = str(member.guild.id)
        guild_stats = stats.setdefault(guild_id_str, {})

        if user_id not in guild_stats:
            guild_stats[user_id] = {
                "total_time": 0,
                "name": _get_saved_voice_name(member),
                "first_join": datetime.now(bangkok_tz).strftime("%H:%M"),
            }
            save_voice_data(data)
        elif "first_join" not in guild_stats[user_id]:
            # เผื่อข้อมูลเก่าก่อนอัปเดตฟีเจอร์นี้ที่ยังไม่มีเวลาบันทึกไว้
            guild_stats[user_id]["first_join"] = datetime.now(bangkok_tz).strftime("%H:%M")
            save_voice_data(data)
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะบันทึกสถิติเข้าห้องเสียง: {e}")


def get_reminders_for_user(user_id):
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    user_notes = [r.get('content', 'แจ้งเตือนความจำ') for r in reminders if r.get('user_id') == str(user_id) and not r.get('is_notified', False)]
    
    if user_notes:
        return ", ".join(user_notes)
    return None


def add_reminder(user_id, time_str, content):
    data = load_user_data()
    if "reminders" not in data:
        data["reminders"] = []
    
    new_memo = {
        "user_id": str(user_id),
        "time": time_str,
        "content": content,
        "is_notified": False
    }
    data["reminders"].append(new_memo)
    save_user_data(data)


def clean_emoji(text):
    # ลบอิโมจิ Discord และสัญลักษณ์พิเศษ
    text = regex_lib.sub(r'<a?:\w+:\d+>', '', text) 
    text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', text)
    return text.strip()


def load_reminders():
    if os.path.exists('check_friend_reminders.json'):
        with open('check_friend_reminders.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_reminders(reminders):
    with open('check_friend_reminders.json', 'w', encoding='utf-8') as f:
        json.dump(reminders, f, ensure_ascii=False, indent=4)


def get_realtime_name(user_id, default_name):
    try:
        user_memory = load_user_data()
        mem = user_memory.get(str(user_id))
        if mem and isinstance(mem, dict):
            if mem.get("admin_nickname") and mem.get("admin_nickname") != "ยังไม่ระบุ":
                return mem.get("admin_nickname")
            if mem.get("nickname") and mem.get("nickname") != "ยังไม่ระบุ":
                return mem.get("nickname")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดใน get_realtime_name: {e}")
    return default_name


def parse_birthday(bday_string):
    if not bday_string or bday_string == "ยังไม่ระบุ":
        return None

    months_th = [
        "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    months_th_short = [
        "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
        "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
    ]
    clean_str = bday_string.strip()

    try:
        # 1. เช็กกรณีมีเดือนภาษาไทยเต็มหรือย่อ
        for i, month_name in enumerate(months_th, 1):
            if month_name in clean_str:
                day_part = clean_str.replace(month_name, "").strip()
                return int(day_part), i
        for i, month_name in enumerate(months_th_short, 1):
            if month_name in clean_str:
                day_part = clean_str.replace(month_name, "").strip()
                return int(day_part), i

        # 2. เช็กกรณีสัญลักษณ์คั่น เช่น วัน/เดือน, วัน-เดือน
        for splitter in ["/", "-", ".", " "]:
            if splitter in clean_str:
                parts = clean_str.split(splitter)
                if len(parts) >= 2:
                    return int(parts[0].strip()), int(parts[1].strip())
    except Exception as e:
        print(f"❌ [Bagley] แปลงวันเกิด '{bday_string}' ไม่สำเร็จ: {e}")
    return None
