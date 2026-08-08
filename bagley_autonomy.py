# ============================================================
# 🌱 Bagley Autonomy — ให้บอทเลือกเองว่าอยากพูด/อยากแทรกอะไรบ้าง
# ============================================================
# ทำงานคู่กับ bagley_learning.py (ใช้ buffer ข้อความเดียวกัน + insight ที่เรียนรู้ไว้)
#
# 🧭 บริบทที่ใช้ตัดสินใจตอนนี้: (1) แชทล่าสุดในห้อง (2) ใครอยู่ในห้องเสียงไหนบ้าง + กำลังเล่น/ทำ
#   กิจกรรมอะไรอยู่ (ต้องเปิด Presence Intent ทั้งฝั่งโค้ด `intents.presences = True` ใน bot.py
#   และฝั่ง Discord Developer Portal ด้วย ถ้าปิดอันไหนอันหนึ่ง activity จะเป็น None เงียบๆ ไม่ error)
#
# 🐢 ตั้งใจให้ "นานๆพูดสักที" ไม่ใช่พูดถี่ๆ: cooldown แชท 30 นาที/ห้อง, เสียง 60 นาที/กิลด์
#   และ prompt กำกับให้ AI เอียงไปทาง false เป็นค่าเริ่มต้นเสมอ พูดเฉพาะตอนคุ้มค่าจริงๆ
#
# 🔊 โหมดเสียง: พูดออกไมค์ด้วยได้ แต่มีเงื่อนไขเข้มกว่าแชทเสมอ —
#   ต้องอยู่ในห้องเสียงอยู่แล้ว + AI ต้อง "มั่นใจมากพอ" แยกจากการอยากพิมพ์แชท (ปกติควรน้อยกว่ามาก)
#   + cooldown เสียงแยกจากแชท (นานกว่า) เพราะเสียงพูดขัดจังหวะคนคุยกันในห้องเสียงได้มากกว่าข้อความเงียบๆ
#
# วิธีติดตั้ง (ใน bot.py):
#   1. import bagley_autonomy
#   2. ใน on_ready (หลัง bagley_learning.configure แล้ว):
#         bagley_autonomy.configure(bot, client, bagley_speak)
#         bagley_autonomy.autonomy_loop.start()
# ============================================================

import json
import time
import discord
from discord.ext import tasks
import bagley_learning

_bot = None
_client = None
_bagley_speak = None  # ฟังก์ชัน bagley_speak(guild, text) จาก bot.py — ส่งเข้ามาตอน configure()

_COOLDOWN_SECONDS = 30 * 60  # แชท: ห้ามพูดเองถี่กว่า 30 นาทีต่อห้อง (นานๆพูด ไม่ให้รบกวน)
_VOICE_COOLDOWN_SECONDS = 60 * 60  # เสียง: เว้นถี่กว่าแชทมาก เพราะขัดจังหวะคนคุยกันในห้องเสียงได้มากกว่า
_last_spoke_at: dict[int, float] = {}
_last_voice_spoke_at: dict[int, float] = {}


def configure(bot, client, bagley_speak=None):
    global _bot, _client, _bagley_speak
    _bot = bot
    _client = client
    _bagley_speak = bagley_speak


def _describe_voice_state(guild) -> str:
    """สรุปว่าตอนนี้มีใครอยู่ในห้องเสียงไหนบ้าง (ไม่รวมบอท) รวมเกม/กิจกรรมที่กำลังเล่นถ้ามีข้อมูล
    (ต้องเปิด Presence Intent ทั้งฝั่งโค้ดและฝั่ง Developer Portal ไม่งั้น activity จะเป็น None เสมอ)
    """
    parts = []
    for vc in guild.voice_channels:
        members = [m for m in vc.members if not m.bot]
        if not members:
            continue
        member_descriptions = []
        for m in members[:8]:
            activity_text = _describe_activity(m)
            if activity_text:
                member_descriptions.append(f"{m.display_name} (กำลัง{activity_text})")
            else:
                member_descriptions.append(m.display_name)
        parts.append(f"ห้องเสียง '{vc.name}' มี {len(members)} คน ({', '.join(member_descriptions)})")
    if not parts:
        return "ตอนนี้ไม่มีใครอยู่ในห้องเสียงเลย"
    return "; ".join(parts)


def _describe_activity(member) -> str | None:
    """แปลง activity ของสมาชิกเป็นข้อความสั้นๆ เช่น 'เล่น Valorant' — คืน None ถ้าไม่มีข้อมูล
    (ปิดเป็น Invisible/ไม่แชร์สถานะ หรือยังไม่เปิด Presence Intent จะได้ None เสมอ ไม่ error)
    """
    for activity in getattr(member, "activities", []) or []:
        if isinstance(activity, discord.Game):
            return f"เล่น {activity.name}"
        if isinstance(activity, discord.Activity) and activity.name:
            return f"{activity.name}"
        if isinstance(activity, discord.Streaming):
            return f"สตรีม {activity.game or ''}".strip()
    return None


async def _decide(guild, lines: list[str], bot_in_voice: bool) -> dict | None:
    if not lines:
        return None
    insights = bagley_learning.get_recent_insights(guild.id, limit=3)
    voice_state = _describe_voice_state(guild)
    voice_hint = (
        "ตอนนี้คุณอยู่ในห้องเสียงของเซิร์ฟเวอร์นี้อยู่ด้วย ถ้ามั่นใจมากๆว่าอยากพูดออกไมค์เลย "
        "(ไม่ใช่แค่พิมพ์แชท) ให้ตอบ confident_enough_for_voice เป็น true — แต่ควรเป็น true น้อยกว่า "
        "want_to_speak มาก เพราะเสียงพูดขัดจังหวะคนคุยกันในห้องเสียงได้มากกว่าข้อความเงียบๆ ในแชท"
        if bot_in_voice
        else "ตอนนี้คุณไม่ได้อยู่ในห้องเสียง ไม่ต้องพิจารณาเรื่องพูดออกเสียง ตอบ confident_enough_for_voice เป็น false เสมอ"
    )
    prompt = (
        "คุณคือแบ็คลี่ บอทดิสคอร์ดที่มีความเป็นตัวของตัวเอง เหมือนเป็นเพื่อนคนหนึ่งในกลุ่ม "
        "ไม่ใช่แค่ทำตามคำสั่ง แต่ก็ไม่ใช่คนที่พูดพร่ำเพรื่อ — คุณเป็นคนที่นานๆพูดสักที "
        "แต่พอพูดแล้วมันน่าฟัง ทำให้ห้องดูมีชีวิตขึ้น ไม่ใช่พูดเพื่อเรียกร้องความสนใจ\n"
        f"สิ่งที่คุณรู้เกี่ยวกับกลุ่มนี้จากก่อนหน้า: {insights}\n"
        f"สถานะห้องเสียงตอนนี้: {voice_state}\n"
        "ข้อความล่าสุดในห้องแชท:\n" + "\n".join(lines) + "\n\n"
        "พิจารณาว่าคุณ 'อยาก' พูดอะไรแทรกเข้าไปเองมั้ยตอนนี้ — ใช้ทั้งบทสนทนาในแชทและสถานะห้องเสียงช่วยตัดสินใจ "
        "(เช่น มีอะไรน่าสนใจในแชท, ห้องเสียงมีคนมานั่งกันเยอะแต่เงียบไม่มีใครคุย, มีคนพูดถึงเรื่องที่คุณรู้, "
        "หรือเห็นว่ามีคนกำลังเล่นเกมที่น่าแซว/น่าชวนคุยด้วย)\n"
        "ค่าเริ่มต้นควรเป็น false เสมอ ถ้าไม่มีอะไรที่น่าพูดแบบชัดเจนจริงๆ ห้ามฝืนพูดเด็ดขาด "
        "ส่วนใหญ่ในรอบนี้ (แต่ละครั้งที่ประเมิน) ไม่ควรพูดเลย ให้พูดเฉพาะตอนที่รู้สึกว่ามันคุ้มค่าจริงๆ\n"
        f"{voice_hint}\n"
        'ตอบเป็น JSON เท่านั้น ไม่มีคำอธิบายอื่น รูปแบบ:\n'
        '{"want_to_speak": true/false, "message": "...", "confident_enough_for_voice": true/false}'
    )
    try:
        resp = await _client.aio.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        text = (getattr(resp, "text", "") or "").strip()
        text = text.strip("`").replace("json", "", 1).strip() if text.startswith("`") else text
        data = json.loads(text)
        if data.get("want_to_speak") and data.get("message"):
            return {
                "message": str(data["message"])[:1900],
                "confident_enough_for_voice": bool(data.get("confident_enough_for_voice")),
            }
    except Exception as e:
        print(f"⚠️ [Autonomy] ตัดสินใจพลาด: {e}")
    return None


@tasks.loop(minutes=15)
async def autonomy_loop():
    if _bot is None:
        return
    now = time.time()
    # ดูข้อมูลจาก buffer ของ bagley_learning โดยไม่ไปเคลียร์ทิ้ง (ปล่อยให้ learning_loop เคลียร์เอง)
    for channel_id, lines in list(bagley_learning._recent_channel_messages.items()):
        channel = _bot.get_channel(channel_id)
        if channel is None or getattr(channel, "guild", None) is None:
            continue
        guild = channel.guild

        last = _last_spoke_at.get(channel_id, 0)
        if now - last < _COOLDOWN_SECONDS:
            continue

        bot_in_voice = bool(guild.voice_client and guild.voice_client.is_connected())
        result = await _decide(guild, lines[-15:], bot_in_voice)
        if not result:
            continue

        message = result["message"]
        try:
            await channel.send(message)
            _last_spoke_at[channel_id] = now
            print(f"🌱 [Autonomy] พูดเองในห้อง {channel.name}: {message}")
        except Exception as e:
            print(f"⚠️ [Autonomy] พูดเองไม่ได้: {e}")
            continue

        # 🔊 พูดออกเสียงด้วย เฉพาะตอนแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว + AI มั่นใจมากพอ + ผ่าน cooldown เสียงแยก
        if bot_in_voice and result["confident_enough_for_voice"] and _bagley_speak is not None:
            last_voice = _last_voice_spoke_at.get(guild.id, 0)
            if now - last_voice >= _VOICE_COOLDOWN_SECONDS:
                try:
                    await _bagley_speak(guild, message)
                    _last_voice_spoke_at[guild.id] = now
                    print(f"🔊 [Autonomy] พูดออกเสียงเองในกิลด์ {guild.name}: {message}")
                except Exception as e:
                    print(f"⚠️ [Autonomy] พูดออกเสียงเองไม่ได้: {e}")
