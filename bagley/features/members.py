"""bagley/features/members.py — ค้นหาสมาชิกจากชื่อ / ดูสถานะเกมของคนในห้อง"""
import difflib
import discord

from bagley.core.app import bot
from bagley.data.storage import get_realtime_name, load_user_data


def _describe_member_activities(guild, max_members: int = 30) -> str:
    """🎮 [แก้ไข] สรุปสั้นๆ ว่าตอนนี้ใครในเซิร์ฟกำลังเล่นเกม/ทำกิจกรรมอะไรอยู่บ้าง — จำกัดเฉพาะคนที่อยู่
    "ในห้องเสียงเดียวกับบอทตอนนี้เท่านั้น" (เดิมส่องทั้งเซิร์ฟ ไม่สนว่าบอทอยู่ห้องไหน ทำให้ข้อมูลไม่แม่นเวลา
    บอทไม่ได้อยู่ด้วยจริงๆ) ถ้าบอทไม่ได้อยู่ในห้องเสียงไหนเลย ให้คืนข้อความบอกตรงๆ ว่าไม่รู้เพราะไม่ได้อยู่ด้วย
    กัน AI เดามั่วเอาสถานะของคนที่ไม่ได้อยู่ห้องเดียวกันมาตอบราวกับเห็นด้วยตาตัวเอง
    """
    if guild is None:
        return "ไม่ทราบสถานะ (ไม่อยู่ในเซิร์ฟเวอร์)"
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return "ตอนนี้บอทไม่ได้อยู่ในห้องเสียงไหนเลย เลยไม่รู้ว่าใครกำลังเล่น/ทำอะไรอยู่ — ถ้ามีคนถาม ให้ตอบตรงๆว่าไม่ทราบเพราะไม่ได้อยู่ในห้องเสียงด้วยตอนนี้"
    channel = vc.channel
    members = [m for m in channel.members if not m.bot]
    if not members:
        return "ตอนนี้บอทอยู่ในห้องเสียงคนเดียว ไม่มีใครอยู่ด้วยเลย"
    lines = []
    for m in members:
        activity_bits = []
        for activity in getattr(m, "activities", []) or []:
            if isinstance(activity, discord.Game):
                activity_bits.append(f"เล่น {activity.name}")
            elif isinstance(activity, discord.Streaming):
                activity_bits.append(f"สตรีม {activity.game or ''}".strip())
            elif isinstance(activity, discord.Activity) and activity.type == discord.ActivityType.playing and activity.name:
                activity_bits.append(f"เล่น {activity.name}")
        calling_name = get_realtime_name(m.id, m.display_name)
        if activity_bits:
            lines.append(f"{calling_name}: {', '.join(activity_bits)}")
        else:
            lines.append(f"{calling_name}: ไม่ได้เปิดเกม/ไม่มีข้อมูลกิจกรรมให้เห็น")
        if len(lines) >= max_members:
            break
    return f"(อยู่ในห้องเสียง '{channel.name}' เดียวกับบอทตอนนี้) " + "; ".join(lines)


def find_member_by_name(guild, name_text, exclude_ids=None, prefer_channel=None, fuzzy_cutoff=0.72):
    """
    🔍 ค้นหาสมาชิกจากชื่อที่พิมพ์เฉยๆ (ไม่ต้อง @แท็ก)
    ลอจิก: เทียบกับชื่อเล่นที่เก็บไว้ใน "คลังความจำ" (user_data) ก่อน
    ถ้าไม่เจอในคลัง ค่อยเทียบกับชื่อบนดิสคอร์ด (display_name / name) เหมือนเดิม

    prefer_channel: ห้องเสียงที่ควรให้น้ำหนักก่อน (เช่น ห้องของคนสั่ง/บอท) ใช้ตอนมีคนชื่อซ้ำกัน
    จะได้เตะ/จัดการคนที่ "อยู่ในห้องเดียวกัน" แทนที่จะสุ่มเอาคนแรกที่เจอในเซิร์ฟ

    รอบที่ 3 เป็นการจับคู่แบบ Fuzzy (คล้ายกัน) เพื่อรองรับกรณีคำสั่งเสียงฟังชื่อผิดเพี้ยน
    เช่น พูดว่า "สุนทร" แต่ระบบจำเสียงได้ว่า "สุนทอน" ก็ยังแมตช์ชื่อในคลังได้
    """
    if not guild or not name_text:
        return None

    exclude_ids = exclude_ids or set()
    clean = name_text.lower().strip()
    if not clean:
        return None

    data_memory = load_user_data()

    def get_calling_name(member):
        special_info = data_memory.get(str(member.id))
        if special_info and isinstance(special_info, dict):
            calling_name = special_info.get("nickname", member.display_name)
        elif special_info:
            calling_name = special_info
        else:
            calling_name = member.display_name
        if not calling_name or calling_name == "ยังไม่ระบุ":
            calling_name = member.display_name
        return (calling_name or "").lower().strip()

    def pick_best(candidates):
        """เมื่อมีคนชื่อซ้ำ/คล้ายกันหลายคน ให้เลือกคนที่น่าจะเป็นเป้าหมายจริงที่สุด:
        1) คนที่อยู่ในห้องเสียงเดียวกับ prefer_channel (ห้องของคนสั่ง/บอท) ก่อน
        2) ถ้าไม่มี ให้เลือกคนที่กำลังอยู่ในห้องเสียงใดๆ ก็ได้ (ปกติคำสั่งพวกนี้ใช้กับคนในห้องเสียง)
        3) ถ้ายังเสมอกันอีก ค่อยเอาคนแรกที่เจอ
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if prefer_channel:
            same_room = [m for m in candidates if m.voice and m.voice.channel and m.voice.channel.id == prefer_channel.id]
            if same_room:
                return same_room[0]
        in_any_voice = [m for m in candidates if m.voice and m.voice.channel]
        if in_any_voice:
            return in_any_voice[0]
        return candidates[0]

    # รอบที่ 1: หาแบบตรงตัวเป๊ะๆ ก่อน (กันแมตช์มั่วจากชื่อสั้นๆ) — เช็คคลังก่อนเสมอ
    exact_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        if clean == c_name or clean == m_disp or clean == m_name:
            exact_matches.append(m)
    picked = pick_best(exact_matches)
    if picked:
        return picked

    # รอบที่ 2: หาแบบเข้าใกล้เคียง/มีคำอยู่ในข้อความ (บางส่วนของชื่อ)
    partial_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        if (c_name and (c_name in clean or clean in c_name)) or \
           (m_disp and (m_disp in clean or clean in m_disp)) or \
           (m_name and clean in m_name):
            partial_matches.append(m)
    picked = pick_best(partial_matches)
    if picked:
        return picked

    # รอบที่ 3: Fuzzy Matching — กันกรณีฟังเสียงผิด/พิมพ์ชื่อเพี้ยนนิดหน่อย
    # (เช่น "สุนทร" ↔ "สุนทอน") โดยเทียบความคล้ายของตัวอักษรทั้งหมด
    best_score = 0.0
    fuzzy_matches = []
    for m in guild.members:
        if m.id in exclude_ids:
            continue
        c_name = get_calling_name(m)
        m_disp = (m.display_name or "").lower()
        m_name = (m.name or "").lower()
        candidate_names = {n for n in (c_name, m_disp, m_name) if n}
        member_best_score = 0.0
        for candidate_name in candidate_names:
            score = difflib.SequenceMatcher(None, clean, candidate_name).ratio()
            if score > member_best_score:
                member_best_score = score
        if member_best_score > best_score:
            best_score = member_best_score
            fuzzy_matches = [m]
        elif member_best_score == best_score and member_best_score >= fuzzy_cutoff:
            if m not in fuzzy_matches:
                fuzzy_matches.append(m)

    if best_score >= fuzzy_cutoff:
        return pick_best(fuzzy_matches)

    return None


def resolve_target_member(message, remove_keywords=None, exclude_bot=True):
    """
    🎯 หาสมาชิกเป้าหมายจากข้อความคำสั่ง:
    1. ถ้ามีการ @แท็ก ให้ใช้คนที่ถูกแท็กก่อนเหมือนเดิม
    2. ถ้าไม่ได้แท็ก ให้แกะข้อความ (ตัดคีย์เวิร์ดคำสั่งออก) แล้วค้นจากคลังความจำ/ชื่อดิสคอร์ดแทน
    คืนค่าเป็น (target_member หรือ None, ข้อความที่เหลือหลังตัดชื่อ/แท็กออกแล้ว)
    """
    exclude_ids = {bot.user.id} if exclude_bot else set()

    if message.mentions:
        target = next((m for m in message.mentions if m.id not in exclude_ids), None)
        if target:
            leftover = message.content
            for mention in message.mentions:
                leftover = leftover.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            return target, leftover.strip()

    if not message.guild:
        return None, message.content

    clean_text = message.content.lower()
    for kw in (remove_keywords or []):
        clean_text = clean_text.replace(kw.lower(), "")
    clean_text = clean_text.strip()

    # ให้น้ำหนักคนที่อยู่ห้องเสียงเดียวกับผู้สั่ง (หรือห้องที่บอทอยู่) ก่อน กันแมตช์ผิดคนตอนชื่อซ้ำ
    prefer_channel = None
    if getattr(message.author, "voice", None) and message.author.voice.channel:
        prefer_channel = message.author.voice.channel
    elif message.guild.voice_client:
        prefer_channel = message.guild.voice_client.channel

    target = find_member_by_name(message.guild, clean_text, exclude_ids=exclude_ids, prefer_channel=prefer_channel)
    return target, clean_text


def find_voice_member_across_guilds(name_query: str, exclude_ids: set = None):
    """🆕 ค้นหาสมาชิกที่ชื่อ/ชื่อเล่นตรงกับ name_query ที่กำลังอยู่ในห้องเสียงอยู่ ข้ามทุกเซิร์ฟที่บอทอยู่ด้วย
    ใช้เฉพาะระบบ "ชวน" (execute_warp_invite) เท่านั้น — ไม่ใช้กับคำสั่งจัดการสมาชิกอื่นๆ (เตะ/ปิดไมค์ ฯลฯ)
    เพราะการชวนไปห้องเสียงไม่กระทบสิทธิ์/ความปลอดภัยเท่าคำสั่งจัดการสมาชิกที่ควรจำกัดอยู่แค่เซิร์ฟเดียวเหมือนเดิม
    คืนค่า discord.Member ตัวแรกที่ตรง (เซิร์ฟที่ผู้สั่งอยู่ก่อน ตามด้วยเซิร์ฟอื่นตามลำดับที่บอทอยู่) หรือ None"""
    exclude_ids = exclude_ids or set()
    query = name_query.strip().lower()
    if not query:
        return None
    for g in bot.guilds:
        for member in g.members:
            if member.id in exclude_ids or member.bot:
                continue
            if not (member.voice and member.voice.channel):
                continue
            if query in member.display_name.lower() or query in member.name.lower():
                return member
    return None


# --- คำสั่ง Join แบบ Hybrid (พิมพ์ได้ทั้ง /join และ !join) ---
def _format_greeting_names(names: list[str]) -> str:
    """รวมรายชื่อคนในห้องให้เป็นประโยคทักทายภาษาไทยแบบธรรมชาติ
    ถ้ามีมากกว่า 4 คน (หรือไม่มีชื่อเลย) จะใช้คำว่า 'ทุกคน' แทนการไล่ชื่อทีละคน"""
    if not names or len(names) > 4:
        return "ทุกคน"
    labeled = [f"คุณ {n}" for n in names]
    if len(labeled) == 1:
        return labeled[0]
    return ", ".join(labeled[:-1]) + " และ" + labeled[-1]
