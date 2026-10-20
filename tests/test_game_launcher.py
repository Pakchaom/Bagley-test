"""ทดสอบตัวจับคำชวนเล่นเกม (UNO/XO) จากข้อความ/เสียง   รัน: PYTHONPATH=. python3 tests/test_game_launcher.py"""
import asyncio
import sys

from bagley.features.games import uno
from bagley.features.games.launcher import detect_game, detect_language, detect_level, try_launch_from_message

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


YES_UNO = ["แบ็คลี่ เล่นอูโน่กัน", "แบ็คลี่ ชวนเล่น uno หน่อย", "แบ็คลี่ มาเล่นยูโน่", "แบ็คลี่ เปิดห้อง UNO", "bagley play uno",
           "แบ็คลี่ เล่น อู โน่ กัน"]
YES_XO = ["แบ็คลี่ เล่น XO กับผมหน่อย", "แบ็คลี่ เล่นทิกแทกโทกัน", "แบ็คลี่ มาเล่น xo", "แบ็คลี่ เล่น tic tac toe", "แบ็คลี่ เล่นเอ็กซ์โอ"]
NO = ["แบ็คลี่ เปิดเพลง", "แบ็คลี่ เล่นเพลงนี้หน่อย", "แบ็คลี่ เล่นเกมเดียวกันบ้าง", "แบ็คลี่ ไม่เล่นอูโน่แล้ว", "แบ็คลี่ เลิกเล่น uno",
      "แบ็คลี่ อูโน่คืออะไร", "แบ็คลี่ ปิดเตือนเล่นเกมนาน", "แบ็คลี่ box ของผมอยู่ไหน", "แบ็คลี่ หยุดเล่น xo", "แบ็คลี่ สวัสดี", "เล่นยังไงอะ"]
YES_HANGMAN = ["แบ็คลี่ เล่น hangman กัน", "แบ็คลี่ เล่นแฮงแมนหน่อย", "bagley play hangman", "แบ็คลี่ เปิดเกมแฮงค์แมน", "แบ็คลี่ เล่น hang man"]
YES_WORDLE = ["แบ็คลี่ เล่น wordle กัน", "แบ็คลี่ เล่นเกมทายคำกัน", "แบ็คลี่ มาเล่นทายคำหน่อย", "แบ็คลี่ เล่นเวิร์ดเดิล", "bagley play wordle"]
YES_RPS = ["แบ็คลี่ เล่นเป่ายิ้งฉุบกัน", "แบ็คลี่ ท้าเป่ายิงฉุบหน่อย", "bagley play rock paper scissors", "แบ็คลี่ เล่น rps"]
NO += ["แบ็คลี่ ช่วยทายคำนี้หน่อย", "แบ็คลี่ ไม่เล่นแฮงแมนแล้ว", "แบ็คลี่ เลิกเล่น wordle", "แบ็คลี่ wordle คืออะไร", "แบ็คลี่ หยุดเล่นเป่ายิ้งฉุบ",
       "แบ็คลี่ hangman คืออะไร", "แบ็คลี่ ทายคำนี้ถูกไหม"]
for t in YES_UNO:
    check(f"UNO: {t}", detect_game(t) == "uno")
for t in YES_XO:
    check(f"XO: {t}", detect_game(t) == "xo")
for t in NO:
    check(f"ไม่เปิดเกม: {t}", detect_game(t) is None)

for t in YES_HANGMAN:
    check(f"Hangman: {t}", detect_game(t) == "hangman")
for t in YES_WORDLE:
    check(f"Wordle: {t}", detect_game(t) == "wordle")
for t in YES_RPS:
    check(f"RPS: {t}", detect_game(t) == "rps")
check("Hangman ภาษาไทยเมื่อพูดถึงไทย", detect_language("แบ็คลี่ เล่นแฮงแมนภาษาไทย") == "th" and detect_language("แบ็คลี่ เล่นแฮงแมน") == "en")
check("ระดับยาก", detect_level("แบ็คลี่ เล่น xo ระดับยาก") == "ยาก")
check("ระดับง่าย", detect_level("แบ็คลี่ เล่น xo แบบง่ายๆ") == "ง่าย")
check("ไม่ระบุ = กลาง", detect_level("แบ็คลี่ เล่น xo") == "กลาง")


class User:
    def __init__(self, uid, name, bot=False):
        self.id, self.display_name, self.bot = uid, name, bot


class Chan:
    id = 55

    def __init__(self):
        self.sent = []

    async def send(self, *a, **kw):
        self.sent.append((a, kw))
        return type("M", (), {"edit": lambda *x, **y: None})()


class Msg:
    def __init__(self, content, mentions=(), guild=True):
        self.content, self.mentions, self.guild = content, list(mentions), object() if guild else None
        self.channel, self.author = Chan(), User(1, "ชะอม")


async def main():
    botu = User(999, "Bagley", True)
    m = Msg("แบ็คลี่ เล่นอูโน่กัน")
    check("ข้อความชวนเล่น UNO เปิดห้องรอในช่อง", await try_launch_from_message(m, botu) and uno.get_session(55) is not None
          and "embed" in m.channel.sent[0][1])
    uno.get_session(55).close()
    m = Msg("แบ็คลี่ เล่น xo กับผม", [botu, User(2, "เพื่อน")])
    check("ข้อความชวนเล่น XO ท้าคนที่แท็ก", await try_launch_from_message(m, botu) and "เพื่อน" in m.channel.sent[0][1]["content"])
    from bagley.features.games import hangman, wordle
    m = Msg("แบ็คลี่ เล่นแฮงแมนภาษาไทย")
    check("ข้อความชวนเล่น Hangman เปิดเกมในช่อง (ภาษาไทย)", await try_launch_from_message(m, botu) and hangman.get_active(55) is not None
          and hangman.get_active(55).game.lang == "th" and "Hangman" in m.channel.sent[0][1]["content"])
    hangman._active.clear()
    m = Msg("แบ็คลี่ เล่นเกมทายคำกัน")
    check("ข้อความชวนเล่นทายคำ เปิดเกมในช่อง", await try_launch_from_message(m, botu) and wordle.get_active(55) is not None)
    wordle._active.clear()
    m = Msg("แบ็คลี่ เล่นเป่ายิ้งฉุบกัน")
    check("ข้อความชวนเล่นเป่ายิ้งฉุบ เปิดเกมให้ผู้เรียก", await try_launch_from_message(m, botu) and "เป่ายิ้งฉุบ" in m.channel.sent[0][1]["content"])
    m = Msg("แบ็คลี่ เปิดเพลง")
    check("ข้อความทั่วไปไม่ถูกดักไว้", not await try_launch_from_message(m, botu) and not m.channel.sent)
    m = Msg("แบ็คลี่ เล่นอูโน่กัน", guild=False)
    check("ใน DM ไม่เปิดเกม (คืน False ให้ด่านอื่นทำต่อ)", not await try_launch_from_message(m, botu))


asyncio.run(main())
print("\nALL PASS" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
