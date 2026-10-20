"""ทดสอบ: สวิตช์เตือนเล่นเกมนาน, ผู้พัฒนาเหลือแต่ชะอม, สถานะ /listen off ไม่ติดข้ามรีสตาร์ท"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp())          # ไฟล์ตั้งค่าที่เขียนตอนเทสต์ไปอยู่ในโฟลเดอร์ชั่วคราว

bad = 0


def check(name, cond):
    global bad
    print(("PASS " if cond else "FAIL ") + name)
    bad += 0 if cond else 1


from bagley.core import config  # noqa: E402
from bagley.features import party  # noqa: E402

CHAOM = 1133740216822267954
CHACHA = 856568101919653918
for n in ("ALLOWED_USERS", "ALLOWED_TEACH_USERS", "ALLOWED_SHUTDOWN_USERS", "VOICE_RELAY_ALLOWED_OWNER_IDS"):
    v = getattr(config, n)
    check(f"{n} = [ชะอม] เท่านั้น", list(v) == [CHAOM] and CHACHA not in v)

# --- keyword เปิด/ปิด ---
for t in ("แบ็คลี่ ปิดเตือนเล่นเกมนาน", "ปิด เตือน เล่นเกม นาน", "แบ็คลี่ หยุดเตือนเล่นเกม", "เลิกเตือนเกมนาน",
          "ไม่ต้องเตือนเล่นเกมนานแล้ว", "ปิดแจ้งเตือนเล่นเกมนาน", "bagley ปิดเตือนเล่นเกมนาน"):
    check(f"ปิด <- {t}", party.parse_gaming_warning_toggle(t) is False)
for t in ("แบ็คลี่ เปิดเตือนเล่นเกมนาน", "เปิดเตือนเล่นเกม", "แบ็คลี่ เตือนเล่นเกมต่อ", "กลับมาเตือนเล่นเกมนาน"):
    check(f"เปิด <- {t}", party.parse_gaming_warning_toggle(t) is True)
for t in ("แบ็คลี่ เล่นเกมอะไรอยู่", "ปิดเพลง", "แบ็คลี่ หยุดหาคน", "เตือนฉันตอนบ่ายสอง"):
    check(f"ไม่เกี่ยว <- {t}", party.parse_gaming_warning_toggle(t) is None)

# --- สวิตช์ต่อเซิร์ฟ + จำข้ามรีสตาร์ท ---
check("ค่าเริ่มต้นเปิด", party.gaming_warning_enabled(1) and party.gaming_warning_enabled(2))
party.set_gaming_warning(1, False)
check("ปิดเซิร์ฟ 1 แล้วเซิร์ฟ 2 ไม่กระทบ", not party.gaming_warning_enabled(1) and party.gaming_warning_enabled(2))
party._gaming_warning_off = None      # จำลองรีสตาร์ท (โหลดจากไฟล์ใหม่)
check("รีสตาร์ทแล้วสถานะปิดยังอยู่", not party.gaming_warning_enabled(1))
party.set_gaming_warning(1, True)
party._gaming_warning_off = None
check("เปิดคืนแล้วจำได้", party.gaming_warning_enabled(1))

# --- /listen off ไม่ติดข้ามรีสตาร์ท ---
import json  # noqa: E402
with open("listen_settings.json", "w", encoding="utf-8") as f:   # ไฟล์รุ่นเก่าที่เคยบันทึกว่าปิดไว้
    json.dump({"111": {"enabled": False, "text_channel": 5}}, f)
from bagley.commands import listen  # noqa: E402
check("ไฟล์รุ่นเก่าที่เคยปิดไว้ -> รีสตาร์ทแล้วกลับมาเปิดฟัง", listen.listen_enabled(111))
listen._set_listen(111, enabled=False, text_channel_id=5)
check("สั่ง off แล้วปิดในรอบนี้", not listen.listen_enabled(111))
saved = json.load(open("listen_settings.json", encoding="utf-8"))
check("ไม่มีสถานะ enabled ถูกเขียนลงไฟล์", "enabled" not in saved.get("111", {}) and saved["111"]["text_channel"] == 5)
listen._listen_off.clear(); listen._listen_cfg = None           # จำลองรีสตาร์ท
check("รีสตาร์ทแล้วกลับมาเปิดฟังเหมือนเดิม", listen.listen_enabled(111))

print("FAILED:", bad)
sys.exit(1 if bad else 0)
