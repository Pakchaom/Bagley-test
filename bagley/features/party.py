"""bagley/features/party.py — ระบบชวนตี้ / เตือนคนเล่นเกมเดียวกัน / วาร์ปเชิญ / DM เรียก"""
import asyncio
import discord
import json
import os
import random
import re
from datetime import datetime, timezone

from bagley.core import state
from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.data.storage import _atomic_write_json, get_realtime_name
from bagley.ui.views import PartyInviteView
from bagley.voice.alerts import check_shared_voice_quota
from bagley.voice.client import connect_voice
from bagley.voice.tts import bagley_speak, bagley_speak_wait


# ============================================================
# 🎮⏰ สวิตช์เปิด/ปิด "เตือนเล่นเกมนาน" (3 / 6 / 9 ชั่วโมง) แยกตามเซิร์ฟเวอร์
# ค่าเริ่มต้น = เปิด  | ปิดด้วย /gaming_warning off หรือพิมพ์/พูด "แบ็คลี่ ปิดเตือนเล่นเกมนาน"
# เก็บลงไฟล์ (gaming_warning_settings.json) -> รีสตาร์ทบอทแล้วยังคงสถานะที่ตั้งไว้
# ============================================================
GAMING_WARNING_FILE = "gaming_warning_settings.json"
_gaming_warning_off: set[int] | None = None


def _load_gaming_warning_off() -> set[int]:
    global _gaming_warning_off
    if _gaming_warning_off is None:
        _gaming_warning_off = set()
        try:
            with open(GAMING_WARNING_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _gaming_warning_off = {int(x) for x in (raw.get("disabled_guilds") or [])}
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ [Gaming Warning] อ่าน {GAMING_WARNING_FILE} ไม่ได้ ({type(e).__name__}: {e}) -> ใช้ค่าเริ่มต้น (เปิดเตือน)")
    return _gaming_warning_off


def gaming_warning_enabled(guild_id: int) -> bool:
    """เซิร์ฟนี้เปิดเตือนเล่นเกมนานอยู่ไหม (ค่าเริ่มต้น = เปิด)"""
    return guild_id not in _load_gaming_warning_off()


def set_gaming_warning(guild_id: int, enabled: bool) -> None:
    off = _load_gaming_warning_off()
    if enabled:
        off.discard(guild_id)
    else:
        off.add(guild_id)
    try:
        _atomic_write_json(GAMING_WARNING_FILE, {"disabled_guilds": sorted(off)}, indent=2)
    except Exception as e:
        print(f"⚠️ [Gaming Warning] บันทึก {GAMING_WARNING_FILE} ไม่สำเร็จ: {type(e).__name__}: {e}")


_GW_TARGETS = ("เตือนเล่นเกมนาน", "เตือนเล่นเกม", "เตือนเกมนาน", "เตือนเล่นนาน", "เตือนสติเล่นเกม",
               "แจ้งเตือนเล่นเกมนาน", "แจ้งเตือนเล่นเกม", "แจ้งเตือนเกมนาน", "gamingwarning")
_GW_OFF_PHRASES = tuple(v + t for v in ("ปิด", "หยุด", "เลิก", "ไม่ต้อง", "งด", "off") for t in _GW_TARGETS)
_GW_ON_PHRASES = tuple(v + t for v in ("เปิด", "กลับมา", "on") for t in _GW_TARGETS)
_GW_ON_CONTINUE = tuple(t + "ต่อ" for t in _GW_TARGETS[:8])      # "เตือนเล่นเกมต่อ"


def parse_gaming_warning_toggle(text: str):
    """ตรวจจับข้อความสั่งเปิด/ปิดเตือนเล่นเกมนาน -> False = ปิด, True = เปิด, None = ไม่เกี่ยว
    (ตัดช่องว่างก่อนเทียบ เพื่อรองรับข้อความที่ได้จากเสียง เช่น "ปิด เตือน เล่นเกม นาน")"""
    t = re.sub(r"\s+", "", (text or "").lower())
    # ⚠️ ต้องเช็ค "เปิด..." ก่อน "ปิด..." เสมอ เพราะคำว่า "เปิด" มี "ปิด" เป็นส่วนหนึ่งของคำ
    # (เช่น "เปิดเตือนเล่นเกม" จะไปตรงกับ "ปิดเตือนเล่นเกม" ถ้าเช็คฝั่งปิดก่อน)
    if any(p in t for p in _GW_ON_PHRASES):
        return True
    if any(p in t for p in _GW_OFF_PHRASES):
        return False
    if any(p in t for p in _GW_ON_CONTINUE):
        return True
    return None


async def check_and_warn_gamers(guild):
    if not guild or not guild.voice_client:
        return

    # 🔇 เซิร์ฟนี้ถูกสั่งปิด "เตือนเล่นเกมนาน" ไว้ -> ข้ามไปเลย
    if not gaming_warning_enabled(guild.id):
        return

    vc = guild.voice_client
    target_channel = vc.channel
    today = datetime.today().date()
    
    # ดึงรายชื่อมนุษย์ทุกคนในห้องเสียงปัจจุบันที่บอทสถิตอยู่
    all_humans_in_room = [m for m in target_channel.members if not m.bot]
    
    for m in all_humans_in_room:
        for activity in m.activities:
            if activity.type == discord.ActivityType.playing and activity.start:
                # คำนวณเวลาที่เล่นไปแล้ว
                elapsed = datetime.now(timezone.utc) - activity.start.replace(tzinfo=timezone.utc)
                hours_played = elapsed.total_seconds() / 3600
                
                # เช็กหาหลักชั่วโมงตึงๆ (3, 6, 9 ชั่วโมง)
                milestone = None
                if hours_played >= 9.0:
                    milestone = 9
                elif hours_played >= 6.0:
                    milestone = 6
                elif hours_played >= 3.0:
                    milestone = 3
                
                if milestone:
                    # สร้างกุญแจสำหรับตรวจสอบว่าเคยเตือนคนนี้ในหลักชั่วโมงนี้ไปหรือยังคัปพ้ม
                    warning_key = (m.id, activity.name, milestone)
                    
                    if state.last_gaming_warnings.get(warning_key) != today:
                        # ✨ เรียกใช้ตรงๆ ได้เลยคัปพ้ม ตา Pylance เลิกงอแงแน่นอน!
                        m_real_name = get_realtime_name(m.id, m.display_name)
                        game_name = activity.name
                        
                        # สร้างประโยคเตือนสติแบ่งตามระดับความตึงของชั่วโมงคัป!
                        if milestone == 3:
                            quotes = [
                                f"คุณ {m_real_name} เล่นเกม {game_name} มา {milestone} ชั่วโมงเต็มแล้วนะ พักสายตาไปดื่มน้ำบ้าง เป็นห่วงนะครับ!",
                                f"แอบส่องมา แอบเห็นคุณ {m_real_name} นั่งจมกับเกม {game_name} มาตั้ง {milestone} ชั่วโมงแน่ะ ลุกไปยืดเส้นยืดสายสักนิดก็ดีนะครับ"
                            ]
                        elif milestone == 6:
                            quotes = [
                                f"อูหู คุณ {m_real_name} นี่กดลากยาว {game_name} มา {milestone} ชั่วโมงแล้วหรอเนี่ย! ร่างกายไม่ใช่เครื่องจักรนะ พักเติมพลังหาอะไรทานด่วนเลยครับ!",
                                f"แจ้งเตือนระดับสองครับ คุณ {m_real_name} เล่นเกม {game_name} ทะลุ {milestone} ชั่วโมงแล้ว ปล่อยจอยสักสิบนาทีไปพักผ่อนก่อนเร็วๆ นะ"
                            ]
                        else:  # 9 ชั่วโมง ตึงขั้นสุด!
                            quotes = [
                                f"คุณพระช่วย! คุณ {m_real_name} เล่นเกม {game_name} มารวดเดียว {milestone} ชั่วโมงแล้วนะครับ! แบ็คลี่ขอร้องเลย ลุกไปนอนพักผ่อนหรือพักสายตายาวๆ ก่อนเถอะครับ เป็นห่วงสุขภาพมากๆ เลยนะ"
                            ]
                        
                        warn_msg = random.choice(quotes)
                        
                        # บันทึกสถานะทันทีกันบอทพ่นซ้ำซ้อน
                        state.last_gaming_warnings[warning_key] = today
                        
                        # สั่งให้ลุงนิวัฒน์เอ่ยปากเตือนสติในห้องเสียงทันทีคัปพ้ม!
                        try:
                            print(f"🎮 [Gaming Warning]: สั่งเตือนสติคุณ {m_real_name} เล่นเกม {game_name} ครบ {milestone} ชม.")
                            await bagley_speak_wait(guild, warn_msg)
                            return  # เตือนทีละ 1 คนต่อนาทีเพื่อความสมูท ไม่พูดแทรกกันเองคัป
                        except Exception as e:
                            print(f"❌ เกิดข้อผิดพลาดตอนส่งเสียงเตือนคนเล่นเกม: {e}")


async def check_and_invite_party(guild):
    if not guild or not guild.voice_client:
        return

    # 🔇🎮 ถ้าเซิร์ฟเวอร์นี้ถูกสั่ง "หยุดหาคน" ไว้ ให้ข้ามการสแกน/ทักคนนอกห้องไปเลย
    if guild.id in state.party_matcher_disabled_guilds:
        return

    vc = guild.voice_client
    target_channel = vc.channel
    today = datetime.today().date()
    
    # 👥 แยกชาวแก๊ง: คนที่อยู่ในห้องเสียงกับบอท VS คนที่อยู่นอกห้องเสียง
    in_room_humans = [m for m in target_channel.members if not m.bot]
    all_guild_humans = [m for m in guild.members if not m.bot]
    outside_humans = [m for m in all_guild_humans if m not in in_room_humans]
    
    if not in_room_humans or not outside_humans:
        return

    # 🎮 1. ส่องดูว่าคน "ในห้องเสียง" กำลังเล่นเกมอะไรกันอยู่บ้าง (เก็บชื่อเกมไว้)
    active_games_in_room = set()
    game_to_players_in_room = {} # { "เกม": [รายชื่อคนในห้อง] }
    
    for m in in_room_humans:
        for activity in m.activities:
            if activity.type == discord.ActivityType.playing:
                game_name = activity.name
                active_games_in_room.add(game_name)
                if game_name not in game_to_players_in_room:
                    game_to_players_in_room[game_name] = []
                game_to_players_in_room[game_name].append(m)

    if not active_games_in_room:
        return # ถ้าคนในห้องไม่มีใครเล่นเกมอยู่เลย ก็ข้ามคัปพ้ม

    # 🎮 2. ส่องดูคน "นอกห้องเสียง" ว่ามีใครเพิ่งเปิดเกมตรงกับคนในห้องไหม
    for m_outside in outside_humans:
        for activity in m_outside.activities:
            if activity.type == discord.ActivityType.playing:
                outside_game = activity.name
                
                # 🔥 ว้าว! คนนอกห้องเล่นเกมเดียวกับคนในห้องเสียงคัป!
                if outside_game in active_games_in_room:
                    invite_key = (m_outside.id, outside_game)
                    
                    # เช็กว่านาทีนี้เพิ่งเข้า หรือยังไม่เคยทักชวนในวันนี้
                    if state.last_party_invites.get(invite_key) != today:
                        
                        # ดึงชื่อเล่นเรียลไทม์ของคนนอกห้อง
                        outside_name = get_realtime_name(m_outside.id, m_outside.display_name)
                        
                        # ดูว่าในห้องมีคนเล่นเกมนี้อยู่กี่คน เพื่อเลือกคำพูด (คุณ / พวกคุณ)
                        players_in_room = game_to_players_in_room[outside_game]
                        
                        if len(players_in_room) == 1:
                            # มีคนเล่นในห้องคนเดียว เจาะจงชื่อเลยคัป
                            host_name = get_realtime_name(players_in_room[0].id, players_in_room[0].display_name)
                            target_speech = f"คุณ {host_name}"
                        else:
                            # มีคนเล่นในห้องหลายคน ใช้คำว่า พวกคุณ คัป
                            target_speech = "พวกคุณ"
                        
                        # 🗣️ มัดรวมประโยคชวนตี้แบบนุ่มนวลตามที่คุณชะอมดีไซน์ไว้เลยคัป!
                        msg = (
                            f"ดูเหมือนว่า คุณ {outside_name} จะเพิ่งเข้าเกม {outside_game} นะครับ "
                            f"{target_speech} ต้องการให้ผมชวนคุณ {outside_name} มั้ยครับ "
                            f"พิมพ์ แบ็คลี่ เรียก พร้อมแท็กได้เลยนะครับ"
                        )
                        
                        # บันทึกสถานะล็อกไว้ทันทีกันบอทพูดสแปมซ้ำซ้อน
                        state.last_party_invites[invite_key] = today
                        
                        try:
                            print(f"📡 [Party Matcher]: พบคุณ {outside_name} เปิดเกม {outside_game} ตรงกับคนในห้อง!")
                            await bagley_speak_wait(guild, msg)
                            return # พูดจบ 1 อิมแพ็คต่อนาที เพื่อไม่ให้เสียงตีกันคัปพ้ม
                        except Exception as e:
                            print(f"❌ เกิดข้อผิดพลาดในระบบแม่สื่อชวนตี้: {e}")


async def handle_same_game_query(message: discord.Message):
    """ตอบคำถาม 'มีใครเล่นเกมเดียวกับเราบ้าง' — เช็คว่าคนถามกำลังเล่นเกมอะไรอยู่
    แล้วไล่หาคนอื่นทั้งเซิร์ฟเวอร์ (ไม่จำกัดแค่ในห้องเสียง) ที่กำลังเล่นเกมเดียวกัน
    ใช้ชื่อจาก "คลังความจำ" (get_realtime_name) ก่อนเสมอ ถ้าไม่มีชื่อเล่นบันทึกไว้ค่อย fallback
    ไปใช้ display_name บนดิสคอร์ดตามปกติ (ดีไซน์ให้คู่กับ check_and_invite_party ด้านบนที่คอยทักเอง
    อัตโนมัติอยู่แล้ว — ฟังก์ชันนี้คือเวอร์ชัน "ถามเอง" เมื่อคนพิมพ์มาถามตรงๆ)"""
    asker = message.author

    asker_game = None
    for activity in asker.activities:
        if activity.type == discord.ActivityType.playing:
            asker_game = activity.name
            break

    if not asker_game:
        try:
            await message.reply(
                "เอ๊ะ ตอนนี้ผมไม่เห็นสถานะว่าคุณเปิดเกมอะไรอยู่เลยนะครับ "
                "ต้องเปิดให้ดิสคอร์ดโชว์สถานะ 'กำลังเล่น' ด้วยนะครับ ผมถึงจะสแกนหาคนที่เล่นเกมเดียวกันให้ได้ 🎮"
            )
        except Exception:
            pass
        return

    matched_members = []
    for m in message.guild.members:
        if m.bot or m.id == asker.id:
            continue
        for activity in m.activities:
            if activity.type == discord.ActivityType.playing and activity.name == asker_game:
                matched_members.append(m)
                break

    if not matched_members:
        try:
            await message.reply(
                f"สแกนดูทั้งเซิร์ฟแล้ว ตอนนี้ยังไม่มีใครเล่นเกม {asker_game} เหมือนคุณอยู่เลยนะครับ 🕵️"
            )
        except Exception:
            pass
        return

    matched_names = [f"คุณ {get_realtime_name(m.id, m.display_name)}" for m in matched_members]
    names_text = ", ".join(matched_names)
    reply_text = f"ตอนนี้ที่กำลังเล่นเกม {asker_game} เหมือนคุณอยู่ด้วยมี {names_text} ครับ 🎮"

    try:
        await message.reply(reply_text)
    except Exception:
        pass

    # 🔊 พูดออกเสียงด้วย ถ้าบอทอยู่ในห้องเสียงเดียวกับคนถามอยู่แล้ว
    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
    if (
        message.guild.voice_client
        and asker.voice
        and message.guild.voice_client.channel == asker.voice.channel
    ):
        try:
            await bagley_speak(message.guild, reply_text)
        except Exception as e:
            print(f"❌ [Same Game Query] พูดออกเสียงไม่สำเร็จ: {e}")


async def execute_warp_invite(ctx_or_interaction, host_member: discord.Member, target_member: discord.Member, target_guild: discord.Guild = None):
    """ลอจิก "ชวน" — บอทวาร์ปตัวเองเข้าไปในห้องเสียงเป้าหมาย เปิดไมค์ตื๊อชวนตัวต่อตัว
    3 รอบ แล้ววาร์ปกลับห้องเดิม (คนละความสามารถกับ execute_dm_call ที่แค่ส่ง DM
    พร้อมปุ่มตอบรับ ไม่วาร์ปตามไปหา)

    🆕 [ข้ามเซิร์ฟ] ถ้า target_member อยู่คนละเซิร์ฟกับ host_member ให้ส่ง target_guild มาด้วย
    (เซิร์ฟที่ target_member อยู่จริง) ฟังก์ชันจะ "เชื่อมต่อแยกต่างหาก" เข้าไปในเซิร์ฟนั้นโดยไม่ยุ่ง
    กับการเชื่อมต่อห้องเสียงเดิมของบอทในเซิร์ฟของ host_member เลย (แต่ละเซิร์ฟมีสถานะห้องเสียงเป็นอิสระ
    จากกันอยู่แล้วในตัว) เสร็จภารกิจแล้วจะออกจากห้องเสียงเซิร์ฟปลายทางไปเฉยๆ (ไม่ต้อง "ย้าย" กลับ เพราะ
    การเชื่อมต่อฝั่งเซิร์ฟของ host_member ไม่เคยถูกแตะต้องเลยตั้งแต่แรก — จึง "กลับมา" ที่เดิมได้เองอัตโนมัติ)"""
    guild = ctx_or_interaction.guild
    if target_guild is None:
        target_guild = guild
    is_cross_server = target_guild.id != guild.id

    # 🕵️‍♂️ ดึงชื่อเล่นเรียลไทม์จากคลัง
    host_name = get_realtime_name(host_member.id, host_member.display_name)
    target_name = get_realtime_name(target_member.id, target_member.display_name)

    # 🔒 กันชวนซ้ำ/ทับกัน: นี่คือจุดเดียวที่ทำการวาร์ปเข้าห้องเสียงไปตื๊อชวนจริง
    # ไม่ว่าจะถูกเรียกจาก /invite_voice ตรงๆ, AI Command Router ตีความจากแชทแล้วสั่ง
    # /invite_voice ให้เอง, หรือจากบล็อกดีเทคคำสำรองใน on_message ก็ตาม ถ้ามีการวาร์ป
    # ไปชวนคนคนเดียวกันในกิลด์นี้ค้างอยู่แล้ว จะกันไม่ให้วาร์ป/พูดตื๊อซ้ำสองรอบ
    invite_key = (target_guild.id, target_member.id)
    if invite_key in state.active_warp_invites:
        msg = f"กำลังวาร์ปไปชวนคุณ {target_name} อยู่แล้วครับ ขอลุยรอบนี้ให้จบก่อนนะครับ ยังไม่ต้องสั่งซ้ำ 🙏"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return
    state.active_warp_invites.add(invite_key)

    try:
        # 1. ตรวจสอบสถานะห้องเสียงของผู้ใช้คำสั่ง
        if not host_member.voice or not host_member.voice.channel:
            msg = " คุณต้องอยู่ในห้องเสียงก่อนนะครับ ถึงจะสั่งให้ผมไปชวนเพื่อนได้คัปพ้ม!"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        host_channel = host_member.voice.channel

        # 2. ตรวจสอบสถานะห้องเสียงของเพื่อนที่จะไปชวน
        if not target_member.voice or not target_member.voice.channel:
            msg = f"ดูเหมือนคุณ {target_name} จะไม่ได้อยู่ในห้องเสียงห้องไหนเลยนะครับ ชวนไม่ได้คัปพ้ม"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        target_channel = target_member.voice.channel

        if host_channel.id == target_channel.id:
            msg = f"อ้าว คุณ {target_name} ก็อยู่นั่งหายใจรดต้นคอในห้องเสียงเดียวกันอยู่แล้วนี่ครับเนี่ย! 555"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        # 3. ตรวจจับเกมที่คนสั่งกำลังเล่นอยู่คัปพ้ม
        game_name = None
        for activity in host_member.activities:
            if activity.type == discord.ActivityType.playing:
                game_name = activity.name
                break

        game_speech = f"เกม {game_name}" if game_name else "เล่นเกมด้วยกัน"

        # แจ้งสถานะก่อนบอทบินวาร์ป (ข้อความนี้ยังคงแจ้งที่ห้องเดิมที่คนสั่ง เพื่อบอกว่ากำลังไปทำภารกิจ)
        start_msg = f"🛸 รับทราบคัปพ้ม! แบ็คลี่กำลังวาร์ปไปชวนคุณ {target_name} ที่ห้อง **{target_channel.name}** ให้คัป!"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(start_msg)
        else:
            await ctx_or_interaction.send(start_msg)

        # 🛠️ [แก้บั๊ก] ข้อความปุ่มตอบรับ/ปฏิเสธ ต้องไปโผล่ที่ห้องแชทของห้องเสียงเป้าหมายที่บอทวาร์ปไปชวน
        # (ห้องเสียงบนดิสคอร์ดมีแชทข้อความในตัวเองอยู่แล้ว) ไม่ใช่ห้องแชทเดิมที่คนสั่งคำสั่งอยู่ก่อนหน้า
        target_text_channel = target_channel

        # 4. ลอจิกวาร์ปข้ามมิติ
        # 🆕 [ข้ามเซิร์ฟ] ถ้าเป็นการชวนข้ามเซิร์ฟ ใช้ voice_client ของ target_guild (อิสระจากเซิร์ฟของ
        # host_member โดยสิ้นเชิง) และจำ "สถานะเดิม" ของบอทในเซิร์ฟปลายทางไว้ก่อน เผื่อบอทเคยอยู่ห้องเสียง
        # เซิร์ฟนั้นด้วยเหตุผลอื่นอยู่ก่อนแล้ว จะได้คืนกลับที่เดิมให้ถูกต้องหลังภารกิจจบ
        previous_target_guild_channel = None
        try:
            if is_cross_server:
                previous_target_guild_channel = target_guild.voice_client.channel if target_guild.voice_client else None
                vc = target_guild.voice_client
                if vc:
                    await vc.move_to(target_channel)
                else:
                    vc = await connect_voice(target_channel)
            else:
                vc = guild.voice_client
                if vc:
                    await vc.move_to(target_channel)
                else:
                    vc = await connect_voice(target_channel)

            # สร้างประโยคตื๊อ 3 รอบ
            invite_quote = f"คุณ {target_name} ครับ คุณ {host_name} ฝากผมมาตามไปตี้ {game_speech} ด้วยกันที่ห้องนู้นหน่อยครับ!"

            view = PartyInviteView(target_member, host_channel, timeout=60)
            invite_msg = None  # จะส่งข้อความปุ่มกดหลังพูดตื๊อรอบแรกจบ ไม่ใช่ก่อนพูด

            # วนลูปพูดตื๊อ 3 รอบ (เว้นระยะรอบละประมาณ 18 วินาที รวมเป็น 1 นาที)
            # 🛠️ [แก้บั๊ก] บอทจะยังคงพูดตื๊อซ้ำไปเรื่อยๆ ทุกรอบจนกว่าจะครบเวลา หรือคนที่โดนชวนกดปุ่ม
            # ตอบรับ/ปฏิเสธ เท่านั้น บอทจะยังไม่วาร์ปกลับห้องเดิมก่อนหน้านั้นเด็ดขาด
            for i in range(3):
                if view.accepted or view.is_finished():
                    break  # ถ้าเขากดปุ่มแล้วให้หยุดตื๊อทันทีคัปพ้ม

                print(f"🗣️ [Warp Invite]: กำลังพูดรอบที่ {i+1} ชวนคุณ {target_name}" + (" (ข้ามเซิร์ฟ)" if is_cross_server else ""))
                await bagley_speak_wait(target_guild, invite_quote)

                # 🛠️ [แก้บั๊ก] พูดตื๊อรอบแรกจบแล้ว ค่อยส่งข้อความปุ่มกดทิ้งไว้ที่ห้องแชทของห้องเสียง
                # เป้าหมายที่บอทไปชวนตอนนี้ (ไม่ใช่ห้องเดิมที่คนสั่งคำสั่งอยู่ก่อนหน้า)
                if invite_msg is None:
                    invite_msg = await target_text_channel.send(
                        f"📢 **คำเชิญชวนเข้าตี้ด่วน!** คุณ {host_name} ชวนคุณ {target_name} ไปจอย {game_speech} คัปพ้ม!",
                        view=view,
                    )

                if view.accepted or view.is_finished():
                    break

                # นอนรอสักแป๊บเผื่อเขากดปุ่ม
                await asyncio.sleep(18)

            # 5. เมื่อเสร็จสิ้นภารกิจ (หมดเวลา 1 นาที หรือกดปุ่มใดปุ่มหนึ่ง) วาร์ปกลับห้องเดิม
            if invite_msg is not None:
                await invite_msg.edit(content="⌛ หมดเวลาหรือคำเชิญนี้สิ้นสุดลงแล้วคัป", view=None)

            # ถ้าวาร์ปกลับไปหาคนสั่งได้ก็กลับคัป
            if is_cross_server:
                # 🆕 [ข้ามเซิร์ฟ] ไม่ต้องแตะเซิร์ฟของ host_member เลย (ไม่เคยถูกยุ่งด้วยตั้งแต่ต้น
                # จึง "อยู่ที่เดิม" อัตโนมัติ) แค่คืนสถานะห้องเสียงของ target_guild ให้เหมือนก่อนหน้านี้:
                # ถ้าบอทเคยอยู่ห้องอื่นในเซิร์ฟนั้นมาก่อน ให้ย้ายกลับไปห้องนั้น ไม่งั้นก็ออกจากห้องเสียงไปเฉยๆ
                if target_guild.voice_client:
                    if previous_target_guild_channel:
                        await target_guild.voice_client.move_to(previous_target_guild_channel)
                    else:
                        await target_guild.voice_client.disconnect(force=False)
                try:
                    await ctx_or_interaction.channel.send(
                        f"🛸 แบ็คลี่ทำภารกิจข้ามเซิร์ฟไปชวนคุณ {target_name} ที่เซิร์ฟ **{target_guild.name}** เสร็จแล้ว "
                        f"วาร์ปกลับมาห้อง **{host_channel.name}** ที่นี่เรียบร้อยครับ! (ไม่เคยขยับออกจากห้องนี้เลยด้วยซ้ำ 😄)"
                    )
                except Exception:
                    pass
            elif guild.voice_client:
                await guild.voice_client.move_to(host_channel)
                await bagley_speak_wait(guild, " แบ็คลี่ทำภารกิจชวนตี้เสร็จสิ้นและวาร์ปกลับมาประจำการเรียบร้อยแล้วครับ!")

        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในระบบวาร์ปตื๊อชวนตี้: {e}")

    finally:
        # 🔓 ปลดล็อกเสมอ ไม่ว่าจะจบแบบสำเร็จ, error, หรือ return กลางทางจากเงื่อนไขด้านบน
        state.active_warp_invites.discard(invite_key)


async def execute_dm_call(ctx_or_interaction, host_member: discord.Member, target_member: discord.Member):
    """ลอจิก "เรียก" — คนละความสามารถกับ execute_warp_invite (ชวน) โดยเจตนา:
    บอทจะ "ส่งข้อความส่วนตัว (DM)" ไปหาคนที่ถูกเรียก พร้อมปุ่ม ✅ ตอบรับ / ❌ ปฏิเสธ
    และลิงก์เชิญเข้าห้องเสียง ให้เขากดไปเองตอนพร้อม บอทไม่ได้วาร์ปตัวเองเข้าไปหาเลย
    (ต่างจาก "ชวน" ที่บอทวาร์ปเข้าไปเปิดไมค์ตื๊อถึงห้องเป้าหมายแล้ววาร์ปกลับ)"""
    guild = ctx_or_interaction.guild

    async def _reply(text, ephemeral=False):
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(text, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(text)

    if target_member.id == bot.user.id:
        await _reply("🤖 เอ๋... จะให้ผมส่ง DM หาตัวเองทำไมกันครับ! ผมสแตนด์บายรออยู่ในนี้แล้วนะ")
        return

    if target_member.id == host_member.id:
        await _reply("🤖 หว่า... จะเรียกตัวเองทำไมกันครับ! คุณก็อยู่ในเซิร์ฟเวอร์นี้อยู่แล้วน้า 🤣")
        return

    if not host_member.voice or not host_member.voice.channel:
        await _reply("❌ คุณต้องเข้าห้องเสียงก่อนถึงจะเรียกเพื่อนให้ส่งลิงก์ได้นะครับ!")
        return

    # 🔒 กันเรียกซ้ำ/ทับกัน: กันไม่ให้มีการส่ง DM เชิญคนคนเดียวกันในกิลด์นี้ซ้อนกันสองรอบ
    call_key = (guild.id, target_member.id)
    if call_key in state.active_dm_calls:
        await _reply(f"เพิ่งส่งสัญญาณไปเรียกคุณ {get_realtime_name(target_member.id, target_member.display_name)} ทาง DM ไปแล้วครับ รอเขาตอบรับก่อนนะครับ ยังไม่ต้องเรียกซ้ำ 🙏")
        return

    can_act, rem = await check_shared_voice_quota(host_member.id, guild)
    if not can_act:
        await _reply(f"⚠️ **Cooldown!** รอก่อนอีก {rem} วินาทีนะครับ")
        return

    state.active_dm_calls.add(call_key)
    try:
        current_channel = ctx_or_interaction.channel
        voice_channel = host_member.voice.channel
        guild_name = guild.name if guild else "เซิร์ฟเวอร์"

        class GatherView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120.0)

            @discord.ui.button(label="🟢 ไปหาเดี๋ยวนี้ (Join)", style=discord.ButtonStyle.success)
            async def accept_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                await current_channel.send(f"🤖 **[BAGLEY]**: {target_member.mention} กดปุ่มตอบรับคำเชิญจากใน DM แล้ว และกำลังมาครับ! 🚀")

                try:
                    invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                    await interaction.response.send_message(f"รับทราบครับ! นี่คือลิงก์เข้าห้องเสียงครับ วาร์ปตามไปได้เลย: {invite.url}", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"รับทราบครับ! (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})", ephemeral=True)

                if guild and guild.voice_client and guild.voice_client.is_connected():
                    print(f"🔊 [BAGLEY VOICE LOG]: รายงานเสียงในห้อง -> {target_member.name} กำลังมาแล้ว")

                self.stop()

            @discord.ui.button(label="🔴 ไม่ว่าง/ติดธุระ (Decline)", style=discord.ButtonStyle.danger)
            async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                await current_channel.send(f"🤖 **[BAGLEY]**: แจ้งสถานะครับ... พอดี {target_member.mention} กดปฏิเสธจากใน DM ว่าติดธุระด่วนอยู่ครับ 💤")
                await interaction.response.send_message("ปฏิเสธคำเชิญเรียบร้อยครับ", ephemeral=True)
                self.stop()

        try:
            view = GatherView()
            await target_member.send(
                f"🔔 **สวัสดีครับคุณ {get_realtime_name(target_member.id, target_member.display_name)}**\n"
                f"ผมแบ็คลี่นะครับ มีสัญญาณเรียกตัวด่วนจากคุณ **{get_realtime_name(host_member.id, host_member.display_name)}** ในดิส `{guild_name}`\n"
                f"รบกวนตามไปพบกันที่ห้อง {current_channel.mention} หน่อยน้าครับ! 👇",
                view=view
            )
            await _reply(f"🤖 **[BAGLEY]**: ส่งรหัสสัญญาณลับเข้าไปที่ DM ของ {target_member.mention} เรียบร้อยแล้วครับ! รอการตอบรับได้เลยครับ")
        except discord.Forbidden:
            await _reply(f"หว่า... ผมไม่สามารถส่ง DM หา {target_member.mention} ได้ครับ เหมือนเขาจะปิดรับ DM ส่วนตัวไว้ชั่วคราวครับ 🔒")
    finally:
        state.active_dm_calls.discard(call_key)
