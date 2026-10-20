"""bagley/core/config.py — ค่าตั้งต้น/คีย์ลับ/ไอดีสิทธิ์ทั้งหมดอยู่ที่นี่ที่เดียว"""
import os
import zoneinfo

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
YT_API_KEY = os.getenv("YT_API_KEY")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")

SPAM_THRESHOLD = 3  # พิมพ์ซ้ำครั้งที่ 3 เป็นต้นไปจะถูกลบ
PENDING_REMINDER_TIMEOUT_SECONDS = 300
_IMAGE_CAPTION_CACHE_MAX = 200

# ---- ไอดีสิทธิ์ ----
# ผู้พัฒนาเหลือคนเดียวคือ ชะอม — ทุกรายชื่อด้านล่างอ้างจากค่าเดียวนี้
# (อยากเพิ่ม/เปลี่ยนผู้พัฒนาในอนาคต แก้ที่บรรทัด OWNER_DISCORD_ID บรรทัดเดียวพอ)
OWNER_DISCORD_ID = 1133740216822267954  # ชะอม

# รายชื่อผู้มีสิทธิ์สั่ง Shut Down คอมพิวเตอร์ได้
ALLOWED_SHUTDOWN_USERS = [OWNER_DISCORD_ID]

# รายชื่อผู้มีสิทธิ์สั่ง Teach แบ็คลี่ได้ (= ผู้พัฒนา)
ALLOWED_TEACH_USERS = [OWNER_DISCORD_ID]

# รายชื่อที่ระบบ "เดินตามอัตโนมัติ" (follow_creator_task) ตาม -> ตามแต่ชะอมเท่านั้น
# (คำสั่ง /follow ที่ผู้พัฒนาสั่งให้ตามคนอื่นยังใช้ได้ตามปกติ แยกจากรายชื่อนี้)
ALLOWED_USERS = [OWNER_DISCORD_ID]

# ============================================================
# 🎙️ [Voice Relay] ระบบรับคำสั่งเสียงตรงจาก mic_to_discord.py
# โดยไม่ต้องผ่าน Discord Webhook เลย -> ไม่ต้องสร้าง Webhook URL
# แยกทุกเซิร์ฟเวอร์ ยืดหยุ่นใช้ได้ทุกที่ที่บอทอยู่ร่วมห้องเสียง
# กับคุณชะอม เซิร์ฟเวอร์ไหนก็ได้ ไม่ต้องตั้งค่าเพิ่ม
# ============================================================
VOICE_RELAY_HOST = "0.0.0.0"   # ฟังจากทุก IP ของเครื่องนี้ (รองรับ Radmin VPN/เครื่องอื่นในเครือข่ายเดียวกัน)

VOICE_RELAY_PORT = 5959

# 🎤 รายชื่อคนที่มีสิทธิ์พูดสั่งงานผ่าน Voice Relay ได้ (แต่ละคนรัน mic_to_discord.py
# ของตัวเอง แล้วระบุ SPEAKER_DISCORD_ID เป็นไอดีของตัวเองในไฟล์นั้น)
VOICE_RELAY_ALLOWED_OWNER_IDS = [
    OWNER_DISCORD_ID,  # ชะอม
]
