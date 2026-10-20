"""bagley/features/games/launcher.py — ชวนเล่นเกมด้วยข้อความ/คำพูด เช่น "แบ็คลี่ เล่นอูโน่กัน" "แบ็คลี่ เล่น XO กับผมหน่อย"

detect_game(text) -> "uno" | "xo" | "hangman" | "wordle" | "rps" | None   (ต้องมีชื่อเกม + คำชวนเล่น และไม่มีคำปฏิเสธ)
try_launch_from_message(message, bot_user) -> True ถ้าเปิดเกมให้แล้ว (ผู้เรียกควร return)
"""
from __future__ import annotations

import re
from typing import Optional

_UNO_TH = ("อูโน่", "อูโน", "อูโน้", "ยูโน่", "ยูโน", "ยูโน้", "อูโนะ")
_XO_TH = ("ทิกแทกโท", "ติ๊กแท็กโท", "ติกแทกโท", "เอ็กซ์โอ", "เอ็กโอ", "โอเอ็กซ์", "โอเอกซ์")
_HANGMAN_TH = ("แฮงแมน", "แฮงค์แมน", "แฮงก์แมน", "แฮงมัน", "เกมแขวนคอ")
_WORDLE_TH = ("เวิร์ดเดิล", "เวิร์ดเดิ้ล", "เวิร์ดเดล", "ทายคำ")
_RPS_TH = ("เป่ายิ้งฉุบ", "เป่ายิงฉุบ", "เป่ายิ้งฉุป", "เป่ายิงฉุป", "เป่ายิ้งชุบ", "เป่ายิ้งฉุ")
_PLAY_TH = ("เล่น", "ชวน", "เปิดห้อง", "สร้างห้อง", "ตั้งห้อง", "เปิดเกม", "จัดเกม", "เริ่ม", "ท้า", "สู้")
_NEG_TH = ("ไม่เล่น", "เลิกเล่น", "หยุดเล่น", "ไม่อยากเล่น", "ไม่ต้องเล่น", "ห้ามเล่น", "อย่าเล่น")
_LEVELS = {"ยาก": "ยาก", "กลาง": "กลาง", "ง่าย": "ง่าย", "hard": "ยาก", "easy": "ง่าย"}


def detect_game(text: str) -> Optional[str]:
    t = (text or "").lower()
    ns = re.sub(r"\s+", "", t)            # ข้อความจากเสียงอาจมีช่องว่างแทรก
    if any(n in ns for n in _NEG_TH):
        return None
    wants = any(p in ns for p in _PLAY_TH) or re.search(r"(?<![a-z])play(?![a-z])", t)
    if not wants:
        return None
    if re.search(r"(?<![a-z])uno(?![a-z])", t) or any(w in ns for w in _UNO_TH):
        return "uno"
    if re.search(r"(?<![a-z])(xo|tic ?tac ?toe)(?![a-z])", t) or any(w in ns for w in _XO_TH):
        return "xo"
    if re.search(r"(?<![a-z])hang ?man(?![a-z])", t) or any(w in ns for w in _HANGMAN_TH):
        return "hangman"
    if re.search(r"(?<![a-z])wordle(?![a-z])", t) or any(w in ns for w in _WORDLE_TH):
        return "wordle"
    if re.search(r"(?<![a-z])(rps|rock ?paper ?scissors)(?![a-z])", t) or any(w in ns for w in _RPS_TH):
        return "rps"
    return None


def detect_level(text: str) -> str:
    ns = re.sub(r"\s+", "", (text or "").lower())
    for k, v in _LEVELS.items():
        if k in ns:
            return v
    return "กลาง"


def detect_language(text: str) -> str:
    """ภาษาของ Hangman: พูดถึง "ไทย" -> th ไม่งั้น en"""
    ns = re.sub(r"\s+", "", (text or "").lower())
    return "th" if ("ไทย" in ns or re.search(r"(?<![a-z])thai(?![a-z])", (text or "").lower())) else "en"


async def try_launch_from_message(message, bot_user) -> bool:
    game = detect_game(message.content)
    if game is None or message.guild is None:
        return False
    if game == "uno":
        from bagley.features.games.uno import open_uno_lobby
        await open_uno_lobby(message.channel, message.author, bot_user.id)
        return True
    if game == "hangman":
        from bagley.features.games.hangman import start_hangman
        await start_hangman(message.channel.send, message.channel.id, message.author, detect_language(message.content))
        return True
    if game == "wordle":
        from bagley.features.games.wordle import start_wordle
        await start_wordle(message.channel.send, message.channel.id, message.author)
        return True
    if game == "rps":
        from bagley.features.games.rps import start_rps
        await start_rps(message.channel.send, message.author, 3, "ยาก")
        return True
    from bagley.features.games.xo import start_xo
    opponent = next((m for m in message.mentions if m.id != bot_user.id and not m.bot), None)
    await start_xo(message.channel.send, message.author, opponent, detect_level(message.content))
    return True
