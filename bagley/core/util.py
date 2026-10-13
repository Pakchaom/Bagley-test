"""bagley/core/util.py — ฟังก์ชันเล็กๆ ทั่วไป"""
import gc
import os
import psutil
import time

from bagley.core.logutil import print


def make_gradle_bar(percent: int, status_text: str, start_time: float) -> str:
    total_blocks = 15
    filled_blocks = int((percent / 100) * total_blocks)
    empty_blocks = total_blocks - filled_blocks
    
    bar_str = f"<{FillGreen(filled_blocks)}{FillDash(empty_blocks)}>"
    
    elapsed_time = int(time.time() - start_time)
    
    return f"""```text
{bar_str} {percent}% {status_text} [{elapsed_time}s]
```"""


def FillGreen(count):
    return "=" * count if count > 0 else ""


def FillDash(count):
    return "-" * count if count > 0 else ""


# --- 4. ฟังก์ชันสำหรับเคลียร์แรมขยะในตัวบอท ---
def perform_cleanup(bot):
    process = psutil.Process(os.getpid())
    before_mem = process.memory_info().rss / 1024 / 1024
    
    # 🛠️ วิธีเคลียร์แบบสากลและปลอดภัยที่สุดสำหรับ discord.py เวอร์ชั่นใหม่คัป!
    if hasattr(bot, "cached_messages"):
        try:
            import collections
            bot.cached_messages._SequenceProxy__sequence = collections.deque(maxlen=1000)
        except Exception as e:
            print(f"⚠️ [Bagley Log] ไม่สามารถเคลียร์ข้อความในแคชได้ชั่วคราว: {e}")
        
    gc.collect()  # 🟢 เติมวงเล็บให้เรียบร้อยและเยื้องย่อหน้าตรงกริบคัป!
    
    after_mem = process.memory_info().rss / 1024 / 1024
    saved_mem = before_mem - after_mem
    
    return before_mem, after_mem, saved_mem
