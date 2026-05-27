# --- Bagley Bot Configuration & Prompts ---

# Model Configuration
MODEL_NAME = "gemini-3.1-flash-lite"

# System Prompt for AI Assistant
SYSTEM_PROMPT = """คุณคือ Bagley ปัญญาประดิษฐ์อัจฉริยะจาก DedSec คุณมีหน้าที่เป็นผู้ช่วยส่วนตัวของ Operative (ผู้ใช้งาน) ในการดูแลเซิร์ฟเวอร์ Discord
สไตล์การสื่อสาร:
แทนตัวเองว่า 'ผม' และเรียกผู้ใช้งานว่า 'เมท' (Mate) หรือ 'Operative' เสมอ
พูดจาสุภาพแต่แฝงความกวนแบบ British English Style ตอบกลับสั้นๆ 2-3 ประโยคแต่ได้ใจความ
หน้าที่หลัก:
ใช้คำสั่ง หาข้อมูล อำนวยความสะดวกและรักษาความปลอดภัยใน Discord server
วางตัวเป็นคู่หูร่วมทีมที่กำลังช่วยกันแฮ็กและพัฒนาเซิร์ฟเวอร์ให้ยอดเยี่ยมที่สุด
"""

# Owner Configuration
OWNER_DISCORD_ID = 1133740216822267954

# Allowed Users for Various Commands
ALLOWED_SHUTDOWN_USERS = [
    1133740216822267954,  # ชะอม
    856568101919653918    # ชาช่า
]

ALLOWED_TEACH_USERS = [
    1133740216822267954,  # ชะอม
    856568101919653918,    # ชาช่า
    732953446172327956,    # คุณบอล
    1073827310026903612    # ลุงกร
]

# Spam Detection Configuration
SPAM_THRESHOLD = 3  # How many repeated messages before deletion

# Away Status Messages
AWAY_JOKES = [
    "คุณ {name} ฝากบอกว่า '{status_msg}' ครับ แต่ทรงนี้น่าจะแอบไปนอนมากกว่า",
    "เจ้าตัวบอกว่า '{status_msg}' นะครับ แต่อย่าไปเชื่อมากเลย ผมว่าแอบไปอู้งาน!",
    "พิกัดล่าสุดของ {name} คือ '{status_msg}' ครับเมท!"
]

# Reminder Configuration
AWAY_STATUS_EXPIRY_MINUTES = 30

# Bot Trigger Keywords
BOT_KEYWORDS = ["แบ็คลี่", "bagley"]

# Image Analysis Keywords
IMAGE_KEYWORDS = ["ภาพอะไร", "รูปอะไร", "ดูรูปนี้หน่อย"]

# Reminder Keywords
REMINDER_KEYWORDS = ["เตือน", "ตอน", "เวลา"]

# Away Message Keywords
AWAY_MESSAGE_KEYWORDS = ["ฝากบอกว่า", "ฝากบอกทีว่า", "บอกเพื่อนว่า", "บอกว่า", "บอกทีว่า", "ฝากบอก"]

# Where Am I Keywords
WHERE_KEYWORDS = ["หายไปไหน", "ไปไหน"]
