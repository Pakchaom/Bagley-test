"""bagley/core/logutil.py — print แบบเก็บ log ล่าสุดไว้ให้คำสั่ง /view_logs (ของเดิมจาก bot.py)"""
import builtins
import collections

LOG_BUFFER = collections.deque(maxlen=10)
ORIGINAL_PRINT = builtins.print


def print(*args, **kwargs):  # noqa: A001 - ตั้งใจทับ print ในโมดูลที่ import ไป
    message = " ".join(str(arg) for arg in args)
    LOG_BUFFER.append(message)
    try:
        ORIGINAL_PRINT(message, **kwargs)
    except Exception:  # stdout ปิด (pythonw) หรือ encoding พัง -> ไม่ให้บอทล้ม
        pass
