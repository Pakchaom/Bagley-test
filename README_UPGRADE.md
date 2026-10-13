# Bagley v2 — สรุปการอัพเกรด

## ติดตั้ง (5 ขั้นตอน)
1. **สำรองของเดิมไว้ก่อน** (ถ้าใช้ git อยู่แล้ว commit ไว้ก็พอ)
2. แตก zip นี้ทับโฟลเดอร์บอทเดิม — จะได้ `bot.py` ตัวใหม่ (บางๆ) + โฟลเดอร์ `bagley/` + `requirements.txt` + `.env.example`
   *zip นี้ไม่มี `.env`, ฐานข้อมูล, ไฟล์ json, mp3, tray — ข้อมูลเดิมของคุณไม่โดนแตะ*
3. **ลบไฟล์เก่าที่ root** (ย้ายเข้า `bagley/` หมดแล้ว): `ai_command_router.py`, `bagley_autonomy.py`, `bagley_learning.py`, `bagley_rooms.py`, `bagley_rules.py`, `bagley_trust.py`, `ephemeral_tools.py`, `youtube_live_chat.py`
4. เปิด `.env` เดิม แล้ว **ใส่ key AI อย่างน้อย 1 เจ้า** (ดู `.env.example`) — `GEMINI_API_KEY` ลบทิ้งได้เลย
   `pip install -r requirements.txt` (ไม่ต้องลง `google-genai` และ `requests` อีกแล้ว)
5. รันเหมือนเดิม (`start_hidden.bat` / ถาด / `python bot.py`) — ถาดกับ `/update_bot` ใช้ได้เหมือนเดิมเพราะจุดเริ่มยังเป็น `bot.py`
   ถ้าใช้ `/update_bot` ให้ **commit + push โฟลเดอร์ `bagley/` ขึ้น GitHub** ก่อน

เริ่มบอทแล้วดู log บรรทัด `🧠 AI พร้อมใช้: chat=[...]` ถ้าเป็น `[]` แปลว่ายังไม่ได้ใส่ key

## ใช้ Gemini เดิม (gemini-3.1-flash-lite) — ไม่ต้องแก้โค้ด
ให้คง `GEMINI_API_KEY` เดิมไว้ใน `.env` แล้วรันเลย บอทจะใช้ **gemini-3.1-flash-lite ทั้งแชท งานจัดหมวด และอ่านรูป** (เหมือนเดิมทุกจุด)
ได้ความไว/โครงสร้างใหม่ครบ (ด่านกรอง ลดรอบ AI เสียงพูดแคช ฯลฯ) ส่วนเจ้าอื่นที่ใส่ไว้จะเป็นตัวสำรองตอนโควต้า Gemini เต็มเท่านั้น
อยากใช้ Gemini ล้วน: ใส่ `AI_ORDER_CHAT=gemini`, `AI_ORDER_FAST=gemini`, `AI_ORDER_VISION=gemini` ใน `.env`
(ใช้ผ่าน endpoint แบบ OpenAI-compatible ของ Google ไม่ต้องลง `google-genai`)

## เรื่อง "ChatGPT ฟรี" (ต้องรู้)
API ทางการของ OpenAI **ไม่มีโควต้าฟรีที่ใช้งานจริงได้** จึงใช้ตัวที่ใกล้เคียงที่สุด:
| เจ้า | โมเดล | จุดเด่น |
|---|---|---|
| Cerebras | gpt-oss-120b (โมเดลเปิดของ OpenAI) | เร็วมาก โควต้าต่อวันเยอะสุด |
| Groq | gpt-oss-20b / 120b | เร็วสุด แต่จำกัด ~8,000 โทเคน/นาที |
| GitHub Models | GPT-4.1 mini ของจริง | **อ่านรูปได้** แต่ ~150 ครั้ง/วัน |
| OpenRouter | gpt-oss `:free` | ตัวสำรอง |
| OpenAI | gpt-4.1-mini | ใส่ key เสียเงินของคุณเองได้ถ้าต้องการ |

บอทสลับเจ้าให้เอง: ถ้าเจ้าแรก 429 / ล่ม / โควต้าเต็ม จะไปเจ้าถัดไปทันทีโดยผู้ใช้ไม่รู้สึก
**แนะนำใส่ Cerebras + Groq + GitHub** (3 เจ้า) — ตัวเลขโควต้าของแต่ละเจ้าเปลี่ยนได้ตามนโยบาย ตรวจในหน้า console ของเขา
หมายเหตุ: ดูรูปภาพต้องมี `GITHUB_TOKEN` (หรือ OpenAI key) เพราะโมเดล gpt-oss อ่านรูปไม่ได้
`/tell_story` โหมดเรื่องจาก AI ยังค้นเว็บด้วย Google Search จริง (ต้องมี `GEMINI_API_KEY`) ถ้าไม่มี key หรือโควต้า Gemini เต็ม จะตกไปเล่าจากความรู้ของโมเดลแทน

## ที่เปลี่ยนด้านความเร็ว
- **ข้อความคุยเล่นไม่ผ่าน AI Router อีกแล้ว**: เดิมทุกข้อความที่เรียกแบ็คลี่เสีย AI 2–3 รอบก่อนจะได้ตอบ (เลือกคำสั่ง + ตรวจทาน + เช็คขาด slot) ตอนนี้ด่าน `ai/gate.py` กรองก่อน ถ้าไม่มีคำสั่งงาน = ตอบแชททันที (1 รอบ)
- ส่ง AI เฉพาะคำสั่งที่เกี่ยวข้อง (~5–15 ตัว แทนทั้ง ~70 ตัว) และตรวจทานรอบ 2 เฉพาะคำสั่งที่กระทบคนอื่น (เตะ ย้าย ปิดไมค์ ฯลฯ)
- งานจัดหมวดสั้นๆ ใช้โมเดลเล็ก/เร็ว (`fast`), คุยจริงใช้โมเดลใหญ่ (`chat`), session เดียว keep-alive, แคชงานจัดหมวด
- **เสียงพูด**: ตัดหน่วง 1 วินาที/ประโยคทิ้ง, สร้างเสียงล่วงหน้าระหว่างประโยคก่อนหน้ายังเล่นอยู่, แคชไฟล์เสียง (`tts_cache/`), อุ่นแคชประโยคตายตัวตอนเริ่มบอท
- **เลิกบล็อกบอท**: `requests.get` (ดูรูป/YouTube API) → aiohttp, `yt-dlp` ค้นเพลงย้ายไป thread (เดิมค้นเพลงทีไรบอททั้งตัวค้าง 2–5 วินาที)
- SQLite เปิด WAL + index, ลดแคชข้อความ Discord จาก 1000 → 200

## บุคลิก
`bagley/ai/persona.py` = ที่เดียวที่เก็บบุคลิก (เดิมกระจายซ้ำ ~18 จุด): แบ็คลี่ DedSec สาขาไทย ประชดเนียนๆ มั่นใจในตัวเอง แซวแล้วช่วยจริง มุกกรุงเทพแทนมุกลอนดอน
กันซ้ำ 3 ชั้น: สุ่ม "มุกตลก" ต่อ 1 คำตอบ + ส่งคำตอบ 3 อันล่าสุดให้โมเดลเลี่ยง + อุณหภูมิ 0.85–0.9
คำตอบสั้นๆ ที่ไม่ใช้ AI อยู่ใน `bagley/phrases.py` (~60 สถานการณ์ x 4–8 แบบ, ไม่ซ้ำติดกัน) — **เพิ่มคำใหม่แค่เติมบรรทัดใน `POOLS`**

## โครงสร้าง
```
bot.py                 จุดเริ่ม (บางๆ)
bagley/core/           config, state (สถานะรัน), app (บอท), security, logutil, http
bagley/ai/             provider, persona, gate, router, classifiers
bagley/voice/          tts, alerts          bagley/music/   player, spotify
bagley/services/       youtube, youtube_live_chat, images, voice_relay
bagley/features/       party teams stories reminders memory members rooms rules trust learning autonomy
bagley/ui/ tasks/ events/ commands/        data/storage.py   db.py   phrases.py
```
ตัวแปรสถานะที่ถูกกำหนดค่าใหม่ เช่น `state.is_playing_music` ต้องเข้าผ่าน `state.` เสมอ

## ยังไม่ได้ทดสอบกับของจริง (ซื่อๆ)
ผมรันบอทกับ Discord/อินเทอร์เน็ตจริงไม่ได้ในเครื่องผม สิ่งที่ตรวจแล้ว: ทุกไฟล์คอมไพล์ผ่าน, โหลดทั้ง 59 โมดูลด้วยตัวจำลอง discord ผ่าน, ไม่มีชื่อตัวแปรที่อ้างถึงแต่ไม่นิยาม, ไม่มี import วนกัน, ทดสอบหน่วย AI provider (สลับสำรอง/429/โควต้า/tool call/รูป) และ router (คุยเล่น = 0 รอบ AI) ด้วยตัวจำลอง
สิ่งที่ต้องลองเอง: คำตอบและน้ำเสียงจริงของโมเดล, ความเร็วจริงบนเครื่องคุณ, คำสั่งเสียง/เพลง/ปุ่มต่างๆ — ถ้าตรงไหนพัง ส่ง traceback มาได้เลย
(พบบั๊กเดิมที่ไม่ได้แก้: `/yt_add` เขียนคอลัมน์ `yt_id` แต่ตาราง `youtube_channels` ประกาศเป็น `channel_id`)
