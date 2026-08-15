# -*- coding: utf-8 -*-
"""
youtube_live_chat.py
=====================
ระบบให้ Bagley "อ่านแชทสด" จากไลฟ์สตรีม YouTube แล้วพูดออกเสียงผ่านห้องเสียง Discord

วิธีทำงาน (ทำไมถึงทำได้):
  YouTube มี Live Streaming API (ส่วนหนึ่งของ YouTube Data API v3 ที่ bot.py ใช้
  YT_API_KEY อยู่แล้ว) ให้ดึง "liveChatId" ของสตรีมที่กำลังไลฟ์อยู่ได้ จากนั้นเรียก
  liveChatMessages.list วนซ้ำ (polling) ตามช่วงเวลาที่ YouTube แนะนำ (pollingIntervalMillis)
  เพื่อดึงข้อความแชทสดใหม่ ๆ ออกมาได้เรื่อย ๆ โดยไม่ต้องเปิดเบราว์เซอร์หรือสแกนหน้าเว็บเลย

พฤติกรรมคีย์ลัด (กดปุ่มเดียวสลับ):
  - ยังไม่เคยเริ่ม  -> กด 1 ครั้ง: เริ่มเซสชันใหม่ + เริ่มพูด
  - กำลังพูดอยู่    -> กด 1 ครั้ง: "หยุดชั่วคราว" (เงียบ) แต่ตัว poll ยังวิ่งอยู่เบื้องหลัง และยังเก็บ
                        ข้อความที่ตรงเงื่อนไขไว้ในคิวรอ (ไม่ทิ้ง) เพื่อพูดทีหลัง
  - หยุดชั่วคราวอยู่ -> กด 1 ครั้ง: พูดข้อความที่ค้างคิวไว้ตอนหยุดชั่วคราวต่อจนหมดคิว (เรียงตามเวลาที่
                        เข้ามาจริง เว้นระยะห่างกันตาม LIVE_CHAT_COOLDOWN กันพูดรัวเกินไป) แล้วพูดข้อความ
                        สดใหม่ที่เข้ามาต่อจากนั้นตามปกติ — ข้อความไหนพูดไปแล้วจะไม่พูดซ้ำอีก
  เซสชันจะหยุดจริง ๆ (เลิก poll เลย) ก็ต่อเมื่อสั่ง stop_watch() ตรง ๆ เท่านั้น (เช่น /stop_live_chat
  หรือสตรีมจบ/เกิด error)

การใช้งานจาก bot.py:
    import youtube_live_chat as ylc
    await ylc.toggle_watch(guild, video_id_or_url, daren_speak, announce_func)  # ใช้กับคีย์ลัด
    await ylc.stop_watch(guild)          # หยุดเซสชันจริง ๆ (เลิก poll)
    ylc.is_watching(guild.id)            # กำลังมีเซสชันวิ่งอยู่ไหม (ไม่ว่าจะพูดอยู่หรือหยุดชั่วคราว)
    ylc.is_speaking(guild.id)            # กำลังพูดอยู่ตอนนี้ไหม (ไม่ได้หยุดชั่วคราว)

ค่าที่อ่านจาก .env (ไม่ใส่ก็ได้ มีค่า default):
    LIVE_CHAT_KEYWORDS   คำที่จะกรอง คั่นด้วยจุลภาค เช่น "สู้ๆ,สู้ๆนะ" (เว้นว่างไว้ = อ่านทุกข้อความ)
    LIVE_CHAT_REPLY      รูปแบบประโยคที่จะพูด ใช้ {name} แทนชื่อคนคอมเมนต์ และ {message} แทนข้อความ
    LIVE_CHAT_COOLDOWN   เว้นระยะห่างระหว่างประโยคที่พูด (วินาที) กันพูดรัวตอนแชทไหลแรง
"""
import os
import re
import asyncio
import collections
import aiohttp

# 🛠️ [แก้บั๊ก] เดิมโค้ดอ่าน YT_API_KEY แค่ครั้งเดียวตอน import module นี้ (ตัวแปร module-level)
# แต่ bot.py สั่ง `import youtube_live_chat` ไว้ตอนต้นไฟล์ ซึ่งเกิดขึ้น "ก่อน" ที่ bot.py จะเรียก
# load_dotenv() เสียอีก (load_dotenv อยู่ถัดลงไปหลายร้อยบรรทัด) ผลคือตอน module นี้ถูก import ค่า
# YT_API_KEY ใน os.environ ยังไม่ถูกโหลดจาก .env เลย เลยได้ None ติดค้างไปตลอดการรันโปรแกรม
# (ต่อให้ .env มีคีย์ถูกต้องแล้วก็ตาม) แก้โดยเปลี่ยนเป็นอ่านค่าจาก os.getenv() "ทุกครั้งที่ใช้งานจริง"
# แทน จะได้ไม่ขึ้นกับลำดับ import/load_dotenv() อีกต่อไป
def _get_yt_api_key() -> str:
    return os.getenv("YT_API_KEY", "")

# คำที่ต้องการดักฟัง (แก้ผ่าน .env: LIVE_CHAT_KEYWORDS=สู้ๆ,สู้สู้)
# เว้นว่างไว้ (ค่า default) = ไม่กรอง อ่านทุกข้อความที่เข้ามา
_raw_keywords = os.getenv("LIVE_CHAT_KEYWORDS", "")
LIVE_CHAT_KEYWORDS = [kw.strip() for kw in _raw_keywords.split(",") if kw.strip()]

# แม่แบบประโยคที่ Bagley จะพูด (แก้ผ่าน .env: LIVE_CHAT_REPLY="พี่ {name} บอกว่า {message}")
LIVE_CHAT_REPLY_TEMPLATE = os.getenv("LIVE_CHAT_REPLY", "พี่ {name} บอกว่า {message}")

# กันไม่ให้พูดถี่เกินไปตอนแชทไหลแรง (วินาที) - แก้ผ่าน .env: LIVE_CHAT_COOLDOWN
LIVE_CHAT_COOLDOWN = float(os.getenv("LIVE_CHAT_COOLDOWN", "1.5"))

# guild_id -> {"task": asyncio.Task, "paused": asyncio.Event}
# paused.is_set() == True หมายถึง "กำลังหยุดชั่วคราว" (poll ต่อ แต่ไม่พูด)
_sessions = {}


def _extract_video_id(text: str) -> str:
    """รับได้ทั้ง video id ตรง ๆ, ลิงก์ watch?v=, ลิงก์ youtu.be/, หรือ /live"""
    text = (text or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return text  # เผื่อเป็น handle/URL แปลก ๆ ปล่อยให้ resolve_live_chat_id จัดการต่อ


async def _resolve_video_id_from_channel(session: aiohttp.ClientSession, channel_id: str) -> str:
    """ถ้าพี่ให้ channel id/handle มาแทน video id ให้หา video ที่ไลฟ์อยู่ตอนนี้ของช่องนั้น"""
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?key={_get_yt_api_key()}&channelId={channel_id}&eventType=live&type=video&part=id"
    )
    async with session.get(url) as resp:
        data = await resp.json()
    items = data.get("items", [])
    if not items:
        raise ValueError("ไม่พบไลฟ์สดที่กำลังถ่ายทอดอยู่ของช่องนี้ครับ")
    return items[0]["id"]["videoId"]


async def resolve_live_chat_id(session: aiohttp.ClientSession, video_id_or_url: str):
    """คืนค่า (video_id, live_chat_id) จาก video id/ลิงก์ หรือ channel id ที่กำลังไลฟ์อยู่"""
    api_key = _get_yt_api_key()
    if not api_key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า YT_API_KEY ใน .env ครับ ต้องใส่ก่อนถึงจะอ่านแชทสดได้")

    candidate = _extract_video_id(video_id_or_url)

    url = f"https://www.googleapis.com/youtube/v3/videos?key={api_key}&id={candidate}&part=liveStreamingDetails,snippet"
    async with session.get(url) as resp:
        data = await resp.json()

    items = data.get("items", [])
    if not items:
        # อาจเป็น channel id/handle ไม่ใช่ video id -> ลองหาไลฟ์ปัจจุบันของช่องนั้นแทน
        candidate = await _resolve_video_id_from_channel(session, candidate)
        url = f"https://www.googleapis.com/youtube/v3/videos?key={api_key}&id={candidate}&part=liveStreamingDetails,snippet"
        async with session.get(url) as resp:
            data = await resp.json()
        items = data.get("items", [])

    if not items:
        raise ValueError("หาวิดีโอ/ไลฟ์สดนี้ไม่เจอครับ ตรวจสอบลิงก์หรือรหัสอีกทีนะครับ")

    details = items[0].get("liveStreamingDetails", {})
    live_chat_id = details.get("activeLiveChatId")
    if not live_chat_id:
        raise ValueError("วิดีโอนี้ไม่ได้กำลังไลฟ์สดอยู่ (ไม่มีแชทสดให้อ่านครับ)")

    return candidate, live_chat_id


def _text_matches_keywords(text: str) -> bool:
    if not LIVE_CHAT_KEYWORDS:
        return True  # ไม่ได้ตั้งคำกรองไว้ -> อ่านทุกข้อความ
    lowered = (text or "").lower()
    return any(kw.lower() in lowered for kw in LIVE_CHAT_KEYWORDS)


async def _watch_loop(guild, video_id_or_url, speak_func, paused_event, announce_func=None, moderate_func=None):
    """
    ลูปหลัก: poll liveChatMessages.list ตาม pollingIntervalMillis ที่ YouTube บอกมา
    ทำงานต่อเนื่องไปเรื่อย ๆ ไม่ว่าจะหยุดชั่วคราว (paused) อยู่หรือไม่ก็ตาม เพื่อให้ pageToken
    เดินหน้าต่อเนื่อง — ตอนกดพูดต่อ จะไม่มีข้อความเก่าตกหล่นและไม่มีข้อความไหนถูกพูดซ้ำ

    moderate_func (ถ้ามี): async def moderate_func(message_text) -> str | None
        ใช้ตรวจแชทด้วย AI ก่อนอ่านออกเสียงแต่ละข้อความ
          - คืนค่า None            -> ข้อความสุภาพปกติ อ่านแชทนั้นตามฟอร์แมตปกติ
          - คืนค่าเป็นสตริงข้อความ  -> ข้อความนี้หยาบคาย/ไม่สุภาพ แบ็คลี่จะพูดสตริงที่ AI
                                       ตอบกลับมา (คำตักเตือนแบบน่ารัก) แทน แล้วข้ามแชทเดิมไปเลย
        ถ้า moderate_func พลาด (exception) จะถือว่าไม่หยาบคาย (fail-open) กันไม่ให้แชทค้าง
    """
    async with aiohttp.ClientSession() as session:
        try:
            video_id, live_chat_id = await resolve_live_chat_id(session, video_id_or_url)
        except Exception as e:
            if announce_func:
                await announce_func(f"❌ เริ่มอ่านแชทสดไม่ได้ครับ: {e}")
            return

        if announce_func:
            await announce_func(f"👀 เริ่มอ่านแชทสดจาก https://www.youtube.com/watch?v={video_id} แล้วครับ")

        page_token = None
        last_spoken_at = 0.0
        # 📥 ข้อความที่ตรงเงื่อนไขแต่ยังไม่ได้พูด (เช่น เข้ามาตอนหยุดชั่วคราวอยู่) รอคิวพูดตอนพูดต่อ
        # จำกัดไว้ไม่เกิน MAX_PENDING ข้อความล่าสุด กันแชทไหลแรงมากตอนหยุดนานๆ แล้วมาพูดรัวเกินไป
        MAX_PENDING = 40
        pending = collections.deque(maxlen=MAX_PENDING)

        try:
            while True:
                params = f"?key={_get_yt_api_key()}&liveChatId={live_chat_id}&part=snippet,authorDetails"
                if page_token:
                    params += f"&pageToken={page_token}"
                url = f"https://www.googleapis.com/youtube/v3/liveChat/messages{params}"

                async with session.get(url) as resp:
                    data = await resp.json()

                if "error" in data:
                    reason = data["error"].get("message", "unknown error")
                    if announce_func:
                        await announce_func(f"⚠️ อ่านแชทสดผิดพลาด ({reason}) หยุดเฝ้าแชทให้แล้วครับ")
                    break

                # ✅ เลื่อน pageToken เสมอแม้ตอนนี้จะหยุดชั่วคราวอยู่ก็ตาม เพื่อไม่ให้ YouTube
                # ส่งข้อความชุดเดิมซ้ำมาให้อีกตอนเรียกครั้งถัดไป (กันพูดซ้ำ)
                page_token = data.get("nextPageToken", page_token)
                polling_ms = data.get("pollingIntervalMillis", 5000)

                # 🧺 เก็บข้อความที่ตรงเงื่อนไขทุกข้อความเข้าคิวไว้ก่อนเสมอ ไม่ว่าจะหยุดชั่วคราวอยู่
                # หรือไม่ก็ตาม — ตอน "พูดต่อ" (resume) ค่อยไปดึงจากคิวนี้มาพูดทีหลัง จะได้ไม่ตกหล่น
                for item in data.get("items", []):
                    snippet = item.get("snippet", {})
                    author = item.get("authorDetails", {})
                    message_text = snippet.get("displayMessage", "")
                    author_name = author.get("displayName", "ผู้ชม")

                    if not message_text or not _text_matches_keywords(message_text):
                        continue

                    pending.append((author_name, message_text))

                # 🔊 พูดข้อความในคิวทีละอันจนกว่าจะหมดคิวหรือโดนหยุดชั่วคราวกลางคัน
                # (ครอบคลุมทั้งข้อความสดใหม่ และข้อความค้างคิวจากตอนหยุดชั่วคราวไว้ก่อนหน้า)
                while pending and not paused_event.is_set():
                    now = asyncio.get_event_loop().time()
                    if now - last_spoken_at < LIVE_CHAT_COOLDOWN:
                        break  # รอรอบถัดไปค่อยพูดต่อ กันพูดรัวเกินไป
                    author_name, message_text = pending.popleft()
                    last_spoken_at = now

                    # 🤖 ให้ AI ช่วยเช็กก่อนว่าแชทนี้หยาบคาย/ไม่สุภาพหรือไม่ ก่อนอ่านออกเสียง
                    warning_text = None
                    if moderate_func:
                        try:
                            warning_text = await moderate_func(message_text)
                        except Exception as e:
                            print(f"⚠️ [ระบบตรวจคำหยาบแชทสด] moderate_func พลาด: {e} (จะอ่านแชทนี้ตามปกติ)")
                            warning_text = None

                    if warning_text:
                        # ข้อความไม่น่ารัก -> แบ็คลี่พูดคำตักเตือนแทน แล้วข้ามแชทนี้ไปอ่านแชทอื่นต่อปกติ
                        await speak_func(guild, warning_text)
                    else:
                        reply = LIVE_CHAT_REPLY_TEMPLATE.format(name=author_name, message=message_text)
                        await speak_func(guild, reply)

                # ⏱️ ถ้ายังมีคิวค้างพูดไม่ทัน (โดนคูลดาวน์กั้นไว้) ให้ตื่นมาเช็คถี่ขึ้นแทนที่จะรอ
                # เต็ม polling interval เพื่อพูดคิวที่เหลือให้ต่อเนื่อง ไม่หน่วงนาน
                sleep_seconds = LIVE_CHAT_COOLDOWN if (pending and not paused_event.is_set()) else max(polling_ms, 2000) / 1000
                await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if announce_func:
                await announce_func(f"⚠️ อ่านแชทสดหยุดกะทันหันเพราะ: {e}")
        finally:
            _sessions.pop(guild.id, None)


def is_watching(guild_id: int) -> bool:
    """มีเซสชันกำลังวิ่งอยู่ไหม (ไม่ว่าจะพูดอยู่หรือหยุดชั่วคราว)"""
    session = _sessions.get(guild_id)
    return bool(session and not session["task"].done())


def is_speaking(guild_id: int) -> bool:
    """กำลังพูดอยู่จริง (ไม่ได้หยุดชั่วคราว) ไหม"""
    session = _sessions.get(guild_id)
    return bool(session and not session["task"].done() and not session["paused"].is_set())


async def start_watch(guild, video_id_or_url, speak_func, announce_func=None, moderate_func=None):
    """เริ่มเซสชันใหม่ (ถ้ามีเซสชันเก่าค้างอยู่จะหยุดตัวเก่าก่อนแล้วเริ่มใหม่)"""
    await stop_watch(guild)
    paused_event = asyncio.Event()  # เริ่มต้นแบบไม่หยุดชั่วคราว (พูดทันที)
    task = asyncio.create_task(
        _watch_loop(guild, video_id_or_url, speak_func, paused_event, announce_func, moderate_func)
    )
    _sessions[guild.id] = {"task": task, "paused": paused_event}
    return task


async def stop_watch(guild):
    """หยุดเซสชันจริง ๆ (เลิก poll เลย) ถ้ากำลังมีเซสชันอยู่"""
    session = _sessions.pop(guild.id, None)
    if session and not session["task"].done():
        session["task"].cancel()
        try:
            await session["task"]
        except asyncio.CancelledError:
            pass


async def toggle_watch(guild, video_id_or_url, speak_func, announce_func=None, moderate_func=None):
    """
    กดปุ่มเดียวสลับ 3 สถานะ:
      ยังไม่เริ่ม -> เริ่มเซสชันใหม่ + พูด
      กำลังพูด    -> หยุดชั่วคราว (เงียบ แต่ poll ต่อเนื่อง กันตกหล่น)
      หยุดชั่วคราว -> พูดต่อ (เฉพาะข้อความใหม่ที่ยังไม่เคยอ่าน)
    คืนค่า "started" / "paused" / "resumed" บอกสถานะล่าสุดหลังกด
    """
    session = _sessions.get(guild.id)

    if not session or session["task"].done():
        await start_watch(guild, video_id_or_url, speak_func, announce_func, moderate_func)
        return "started"

    if session["paused"].is_set():
        session["paused"].clear()
        if announce_func:
            await announce_func("🔊 พูดต่อแล้วครับ (จะพูดแชทที่ค้างไว้ตอนหยุดก่อน แล้วพูดแชทสดใหม่ต่อครับ)")
        return "resumed"
    else:
        session["paused"].set()
        if announce_func:
            await announce_func("🔇 หยุดพูดชั่วคราวแล้วครับ (ยังฟังและเก็บแชทไว้ให้อยู่ กดอีกครั้งเพื่อพูดต่อ)")
        return "paused"
