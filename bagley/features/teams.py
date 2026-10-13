"""bagley/features/teams.py — สุ่มทีม / แยกห้องทีม / สุ่มรายการ / ตั้งเวลาเตะตัวเอง"""
import asyncio
import discord
import random
import re as regex_lib
from discord.ext import commands

from bagley.core import state
from bagley.core.app import bot
from bagley.core.logutil import print
from bagley.data.storage import _get_saved_voice_name, get_realtime_name
from bagley.voice.tts import bagley_speak


async def _dm_self_kick_timer(ctx: commands.Context, target_time_str: str, delay_seconds: float):
    """🆕 เวอร์ชันสำหรับสั่ง /kicktimer ผ่าน DM: ไม่มี ctx.guild ให้ใช้ ui.UserSelect เลือกใครไม่ได้
    (คอมโพเนนต์นี้ต้องใช้บริบทเซิร์ฟเวอร์) เลยล็อกเป้าหมายเป็น "ตัวคนสั่งเอง" โดยอัตโนมัติ แล้วตามหา
    ว่าตอนนี้อยู่ห้องเสียงเซิร์ฟไหนอยู่ (จากเซิร์ฟที่บอทกับคนสั่งอยู่ร่วมกัน) เพื่อเตะออกให้ตรงเวลา
    แล้วแจ้งกลับใน DM ว่าเตะออกให้แล้วครับ"""
    author = ctx.author
    target_guild = None
    for g in bot.guilds:
        member = g.get_member(author.id)
        if member and member.voice and member.voice.channel:
            target_guild = g
            break

    if target_guild is None:
        return await ctx.send(
            "ตอนนี้ผมหาไม่เจอเลยครับว่าคุณอยู่ห้องเสียงเซิร์ฟไหนอยู่ 😅 "
            "รบกวนเข้าห้องเสียงในเซิร์ฟที่มีผมอยู่ด้วยก่อน แล้วค่อยตั้งเวลาผ่าน DM อีกทีนะครับ "
            "(ตั้งเวลาผ่าน DM จะล็อกเป้าหมายเป็นตัวคุณเองเท่านั้นครับ ถ้าอยากเลือกดีดคนอื่น ต้องสั่ง `/kicktimer` ในเซิร์ฟเวอร์แทนครับ)"
        )

    guild_id = target_guild.id
    await ctx.send(
        f"รับทราบครับ! ผมเจอคุณอยู่ห้องเสียง **{target_guild.name}** แล้วครับ "
        f"ผมล็อกเป้าหมายเป็นตัวคุณเองไว้แล้ว จะดีดออกให้ตอน **{target_time_str}** ครับผม "
        f"*(ตั้งผ่าน DM เลือกดีดได้แค่ตัวเองเท่านั้นน้า ถ้าอยากยกเลิกทัก DM มาบอกได้เลยครับ)*"
    )

    async def dm_kick_worker():
        try:
            await asyncio.sleep(delay_seconds)
            member = target_guild.get_member(author.id)
            if member and member.voice and member.voice.channel and member.voice.channel.guild.id == guild_id:
                try:
                    origin_channel = member.voice.channel  # ห้องเสียงมีแชทข้อความในตัว ใช้แจ้งในเซิร์ฟด้วย
                    await member.move_to(None, reason=f"แบ็คลี่เคลียร์ตามเวลาที่ตั้งไว้ผ่าน DM {target_time_str} ครับ")
                    notify_text = f"💥 ถึงเวลา {target_time_str} แล้ว! เตะออกให้ตามที่ตั้งไว้ผ่าน DM เรียบร้อยครับ!"
                    try:
                        await origin_channel.send(f"{author.mention} {notify_text}")
                    except Exception:
                        pass
                    try:
                        await author.send(notify_text)
                    except Exception:
                        pass
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            state.active_kick_tasks.pop((guild_id, author.id), None)

    loop = asyncio.get_running_loop()
    old_task = state.active_kick_tasks.get((guild_id, author.id))
    if old_task:
        old_task.cancel()
    task = loop.create_task(dm_kick_worker())
    state.active_kick_tasks[(guild_id, author.id)] = task


# ============================================================
# 🎲 ระบบสุ่มแบ่งทีมจากคนในห้องเสียง (/split_team)
# ไม่ย้ายห้องใครทั้งนั้น แค่สุ่มแล้วบอกผลเป็นข้อความในแชท
# มีเมนูให้ติ๊กเลือก/ถอดคนที่ไม่ได้เล่นออกก่อนสุ่มได้
# เลือกได้ 2 โหมด: สุ่มทีเดียวแยกทีมให้เลย หรือ สุ่มทีละคนทีละฝั่งให้ตื่นเต้น
# ============================================================
class TeamSplitView(discord.ui.View):
    def __init__(self, author, members, num_teams, origin_channel=None):
        super().__init__(timeout=120)
        self.author = author
        self.num_teams = num_teams
        # 🏠 ห้องเสียงต้นทางที่สุ่มออกมา (ใช้ตอนถามว่าจะแยกห้องจริงมั้ย)
        self.origin_channel = origin_channel

        # ค่าเริ่มต้น = เลือกทุกคนในห้องไว้ก่อน (ไม่เกิน 25 คนตามกฎ Discord)
        member_options = [
            discord.SelectOption(label=get_realtime_name(m.id, m.display_name), value=str(m.id), emoji="🎮", default=True)
            for m in members if not m.bot
        ][:25]

        if not member_options:
            member_options.append(discord.SelectOption(label="ไม่มีคนให้สุ่มคัป", value="none"))

        self.member_select = discord.ui.Select(
            placeholder="ติ๊กเลือกคนที่จะร่วมสุ่มทีม (ค่าเริ่มต้นคือทุกคนในห้อง)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        confirm_btn = discord.ui.Button(label="🎲 สุ่มทีเดียว (แยกทีมให้เลย)", style=discord.ButtonStyle.green)
        confirm_btn.callback = self.confirm_all_callback
        self.add_item(confirm_btn)

        stepwise_btn = discord.ui.Button(label="🎯 สุ่มทีละคน (ตื่นเต้นกว่า)", style=discord.ButtonStyle.blurple)
        stepwise_btn.callback = self.confirm_stepwise_callback
        self.add_item(stepwise_btn)

        # ค่าเริ่มต้นตอนยังไม่ได้แตะเมนูเลย = ทุกคนในห้อง
        self.selected_ids = [str(m.id) for m in members if not m.bot]

    async def member_callback(self, interaction: discord.Interaction):
        if self.member_select.values and self.member_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีใครให้สุ่มเลยคัป!", ephemeral=True)

        self.selected_ids = self.member_select.values
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"Team split member_callback error: {e}")

    def _get_chosen_members(self, interaction: discord.Interaction):
        """ตรวจสิทธิ์ + ดึงรายชื่อสมาชิกที่ถูกเลือกไว้ออกมาเป็น object จริง
        คืนค่า (chosen_members, error_message) — ถ้า error_message ไม่ใช่ None แปลว่าใช้ไม่ได้
        """
        if interaction.user.id != self.author.id:
            return None, "ต้องเป็นคนสั่งสุ่มทีมเท่านั้นถึงจะกดยืนยันได้ครับ!"

        if not self.selected_ids:
            return None, "ยังไม่ได้เลือกใครเลยครับ รบกวนเลือกก่อนนะ!"

        chosen_members = []
        for m_id in self.selected_ids:
            if m_id == "none":
                continue
            member = interaction.guild.get_member(int(m_id))
            if member:
                chosen_members.append(member)

        if len(chosen_members) < self.num_teams:
            return None, f"❌ คนที่เลือกมีแค่ {len(chosen_members)} คน แต่จะแบ่ง {self.num_teams} ทีมไม่พอครับ!"

        return chosen_members, None

    async def confirm_all_callback(self, interaction: discord.Interaction):
        chosen_members, error = self._get_chosen_members(interaction)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        # 🎲 สุ่มลำดับแล้วแจกเข้าทีมแบบวนรอบ (จำนวนคนในแต่ละทีมจะเท่ากันที่สุดเท่าที่จะทำได้)
        random.shuffle(chosen_members)
        teams = [[] for _ in range(self.num_teams)]
        for idx, member in enumerate(chosen_members):
            teams[idx % self.num_teams].append(member)

        report_lines = ["🎲 **ผลการสุ่มทีมจากแบ็คลี่!**\n"]
        for i, team in enumerate(teams, 1):
            names = "\n".join(f"• {_get_saved_voice_name(m)}" for m in team)
            report_lines.append(f"**ทีม {i}**\n{names}\n")
        report = "\n".join(report_lines)

        for item in self.children:
            item.disabled = True

        try:
            await interaction.response.edit_message(content=report, view=self)
        except discord.NotFound:
            await interaction.channel.send(report)
        except Exception as e:
            print(f"❌ ระบบสุ่มทีมพัง: {e}")
            try:
                await interaction.response.send_message(report)
            except Exception:
                pass

        # 🔊 พูดสรุปผลออกไมค์ ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว (เอาชื่อจากคลังก่อน ไม่มีค่อยใช้ชื่อโปรไฟล์)
        if interaction.guild.voice_client:
            team_names_spoken = " ".join(
                f"ทีม {i} มี {', '.join(_get_saved_voice_name(m) for m in team)}"
                for i, team in enumerate(teams, 1)
            )
            try:
                await bagley_speak(interaction.guild, f"สุ่มทีมเรียบร้อยครับ {team_names_spoken}")
            except Exception as e:
                print(f"Team split speak error: {e}")

        # 🔀 ถามต่อว่าจะให้แบ็คลี่แยกห้องจริงตามผลสุ่มเลยมั้ย
        await _ask_to_split_rooms(interaction, self.author, teams, self.origin_channel)

    async def confirm_stepwise_callback(self, interaction: discord.Interaction):
        chosen_members, error = self._get_chosen_members(interaction)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        for item in self.children:
            item.disabled = True

        draw_view = TeamDrawView(self.author, chosen_members, self.num_teams, self.origin_channel)
        report = draw_view.build_report()

        try:
            await interaction.response.edit_message(content=report, view=draw_view)
        except discord.NotFound:
            msg = await interaction.channel.send(report, view=draw_view)
            draw_view.message = msg
        except Exception as e:
            print(f"❌ ระบบสุ่มทีมทีละคนพัง: {e}")
            try:
                msg = await interaction.response.send_message(report, view=draw_view)
                draw_view.message = msg
            except Exception:
                pass

        # 🔊 พูดบอกว่าเริ่มจับสลากทีละคนแล้ว ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว
        if interaction.guild.voice_client:
            try:
                await bagley_speak(interaction.guild, "เริ่มจับสลากทีละคนแล้วนะครับ")
            except Exception as e:
                print(f"Stepwise draw start speak error: {e}")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class TeamDrawView(discord.ui.View):
    """โหมดสุ่มทีละคน — กดปุ่มทีละครั้งเพื่อดึงคนถัดไปเข้าทีมแบบวนรอบ เพิ่มความตื่นเต้นทีละคน
    พูดชื่อ (ใช้ชื่อจากคลังก่อน ไม่มีค่อยใช้ชื่อโปรไฟล์) ทุกครั้งที่สุ่มได้คนใหม่
    พอสุ่มครบทุกคนแล้ว ปุ่มจะเปลี่ยนเป็น 'สรุปผล' — กดอีกครั้งเพื่อให้แบ็คลี่พูดสรุปทั้งหมดพร้อมส่งรายละเอียดว่าใครอยู่ทีมไหน
    """

    def __init__(self, author, chosen_members, num_teams, origin_channel=None):
        super().__init__(timeout=180)
        self.author = author
        self.num_teams = num_teams
        self.remaining = list(chosen_members)
        self.teams = [[] for _ in range(num_teams)]
        self.summarized = False
        self.message = None
        # 🏠 ห้องเสียงต้นทางที่สุ่มออกมา (ใช้ตอนถามว่าจะแยกห้องจริงมั้ย)
        self.origin_channel = origin_channel

        self.draw_btn = discord.ui.Button(label="🎯 สุ่มคนต่อไป!", style=discord.ButtonStyle.green)
        self.draw_btn.callback = self.draw_callback
        self.add_item(self.draw_btn)

    def build_report(self, just_drawn=None, team_number=None, done=False, summarized=False):
        lines = ["🎯 **สุ่มทีมทีละคน — แบ็คลี่กำลังจับสลาก!**\n"]
        for i, team in enumerate(self.teams, 1):
            names = "\n".join(f"• {_get_saved_voice_name(m)}" for m in team) if team else "_ยังไม่มีใคร_"
            lines.append(f"**ทีม {i}**\n{names}\n")

        if just_drawn and team_number:
            lines.append(f"🎉 คุณ **{_get_saved_voice_name(just_drawn)}** อยู่ ทีม {team_number} ครับ\n")

        if summarized:
            lines.append("✅ สรุปผลการสุ่มทีมทั้งหมดตามด้านบนเลยครับ!")
        elif done:
            lines.append("✅ สุ่มครบทุกคนแล้วครับ! กดปุ่มด้านล่างอีกครั้งเพื่อให้แบ็คลี่สรุปผลทั้งหมด")
        elif self.remaining:
            lines.append(f"เหลืออีก {len(self.remaining)} คนที่ยังไม่ถูกสุ่ม... กดปุ่มด้านล่างเพื่อสุ่มคนต่อไป!")

        return "\n".join(lines)

    async def draw_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("ต้องเป็นคนสั่งสุ่มทีมเท่านั้นถึงจะกดสุ่มได้ครับ!", ephemeral=True)

        # ---------- กรณีสุ่มครบทุกคนไปแล้ว: กดครั้งนี้ = สรุปผลทั้งหมด ----------
        if not self.remaining:
            if self.summarized:
                return await interaction.response.send_message("สรุปผลไปแล้วครับ!", ephemeral=True)

            self.summarized = True
            self.draw_btn.disabled = True

            report = self.build_report(done=True, summarized=True)

            try:
                await interaction.response.edit_message(content=report, view=self)
            except discord.NotFound:
                await interaction.channel.send(report)
            except Exception as e:
                print(f"❌ ระบบสุ่มทีมทีละคนพัง (summarize): {e}")

            # 🔊 พูดสรุปผลทั้งหมด ใครอยู่ทีมไหนบ้าง (เอาชื่อจากคลังก่อน ไม่มีค่อยใช้ชื่อโปรไฟล์)
            if interaction.guild.voice_client:
                team_names_spoken = " ".join(
                    f"ทีม {i} มี {', '.join(_get_saved_voice_name(m) for m in team)}"
                    for i, team in enumerate(self.teams, 1)
                )
                try:
                    await bagley_speak(interaction.guild, f"สรุปผลการสุ่มทีมครับ {team_names_spoken}")
                except Exception as e:
                    print(f"Team draw summarize speak error: {e}")

            # 🔀 ถามต่อว่าจะให้แบ็คลี่แยกห้องจริงตามผลสุ่มเลยมั้ย
            await _ask_to_split_rooms(interaction, self.author, self.teams, self.origin_channel)
            return

        # ---------- กรณียังมีคนเหลือ: สุ่มคนถัดไปแบบไม่ซ้ำ แล้วยัดเข้าทีมแบบวนรอบ ----------
        picked = random.choice(self.remaining)
        self.remaining.remove(picked)

        already_assigned = sum(len(t) for t in self.teams)
        team_idx = already_assigned % self.num_teams
        team_number = team_idx + 1
        self.teams[team_idx].append(picked)

        done = not self.remaining
        if done:
            self.draw_btn.label = "📢 สรุปผลทีมทั้งหมด!"
            self.draw_btn.style = discord.ButtonStyle.blurple

        report = self.build_report(just_drawn=picked, team_number=team_number, done=done)

        try:
            await interaction.response.edit_message(content=report, view=self)
        except discord.NotFound:
            await interaction.channel.send(report)
        except Exception as e:
            print(f"❌ ระบบสุ่มทีมทีละคนพัง (draw): {e}")

        # 🔊 ประกาศชื่อคนที่เพิ่งสุ่มได้ออกไมค์ทันทีทุกครั้ง ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว
        # (เอาชื่อจากคลังความจำที่บันทึกไว้ก่อน ถ้าไม่มีค่อยใช้ชื่อโปรไฟล์ดิสคอร์ดปัจจุบัน — ผ่าน _get_saved_voice_name)
        if interaction.guild.voice_client:
            picked_voice_name = _get_saved_voice_name(picked)
            try:
                await bagley_speak(interaction.guild, f"คุณ {picked_voice_name} อยู่ ทีม {team_number} ครับ")
            except Exception as e:
                print(f"Team draw speak error: {e}")

    async def on_timeout(self):
        self.draw_btn.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ============================================================
# 🔀🏠 ระบบแยกห้องเสียงจริงหลังสุ่มทีมเสร็จ + คำสั่ง /back พากลับมารวมกัน
# หลังสุ่มทีมเสร็จ (ไม่ว่าโหมดสุ่มทีเดียว หรือสุ่มทีละคน) แบ็คลี่จะถามว่า
# จะให้แยกห้องจริงตามผลสุ่มมั้ย ถ้าตกลง -> สร้างห้องทีมละ 1 ห้อง (ทีม 1, ทีม 2, ...)
# แล้วย้ายแต่ละทีมเข้าห้องของตัวเอง ส่วนแบ็คลี่จะรออยู่ห้องเดิมเสมอ
# พอแข่งเสร็จ ใครก็ได้ที่ถูกแยกไป พิมพ์ back เพื่อพาทุกคนกลับมารวมกันที่ห้องเดิม
# โดยแบ็คลี่จะไม่รายงานทีละคนว่าใครเข้ามาบ้าง (กันด้วย is_moving_group เหมือนฟีเจอร์ย้ายห้องอื่น ๆ)
# ============================================================

async def _ask_to_split_rooms(interaction: discord.Interaction, author, teams, origin_channel):
    """หลังสุ่มทีมเสร็จ (ทั้งสองโหมด) ถามผู้สั่งว่าจะให้แบ็คลี่แยกห้องเสียงจริงตามผลสุ่มเลยมั้ย"""
    if not interaction.guild or not origin_channel:
        return
    if not teams or all(len(t) == 0 for t in teams):
        return

    prompt_text = (
        f"อยากให้แบ็คลี่แยกห้องเสียงตามผลสุ่มนี้เลยมั้ยครับ? "
        f"(จะสร้างห้องทีมทั้งหมด {len([t for t in teams if t])} ห้อง แล้วย้ายแต่ละทีมเข้าห้องของตัวเอง "
        f"ส่วนแบ็คลี่จะรออยู่ห้อง **{origin_channel.name}** เหมือนเดิมครับ)"
    )

    view = TeamRoomSplitPromptView(author, teams, origin_channel)
    try:
        msg = await interaction.channel.send(prompt_text, view=view)
        view.message = msg
    except Exception as e:
        print(f"❌ ถามแยกห้องทีมไม่ได้: {e}")

    # 🔊 พูดถามออกไมค์ด้วย ถ้าแบ็คลี่อยู่ในห้องเสียงอยู่แล้ว (ให้เหมือนพร้อมท์ยืนยันอื่น ๆ ในบอท)
    if interaction.guild.voice_client:
        try:
            await bagley_speak(
                interaction.guild,
                f"อยากให้ผมแยกห้องเสียงตามผลสุ่มนี้เลยมั้ยครับ จะรออยู่ห้อง {origin_channel.name} เหมือนเดิมนะครับถ้าแยกให้"
            )
        except Exception as e:
            print(f"Ask split rooms speak error: {e}")


class TeamRoomSplitPromptView(discord.ui.View):
    def __init__(self, author, teams, origin_channel):
        super().__init__(timeout=120)
        self.author = author
        self.teams = teams
        self.origin_channel = origin_channel
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "ต้องเป็นคนสั่งสุ่มทีมเท่านั้นถึงจะตอบคำถามนี้ได้ครับ!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ แยกห้องเลยครับ", style=discord.ButtonStyle.green)
    async def confirm_split(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await _execute_team_room_split(interaction, self.teams, self.origin_channel)

    @discord.ui.button(label="❌ ไม่ต้องครับ", style=discord.ButtonStyle.grey)
    async def decline_split(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(content="ได้ครับ ไม่แยกห้องให้ก็ได้ครับ 👍", view=self)
        except Exception:
            try:
                await interaction.response.send_message("ได้ครับ ไม่แยกห้องให้ก็ได้ครับ 👍", ephemeral=True)
            except Exception:
                pass

        # 🔊 พูดตอบด้วย ให้เหมือนพูดถามก่อนหน้านี้
        if interaction.guild.voice_client:
            try:
                await bagley_speak(interaction.guild, "ได้ครับ ไม่แยกห้องให้ก็ได้ครับ")
            except Exception as e:
                print(f"Decline split speak error: {e}")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def _execute_team_room_split(interaction: discord.Interaction, teams, origin_channel):
    """สร้างห้องทีมละ 1 ห้อง ย้ายสมาชิกแต่ละทีมเข้าห้องของตัวเอง แล้วบันทึก session ไว้ให้ /back ใช้ทีหลัง"""
    guild = interaction.guild
    category = origin_channel.category

    state.is_moving_group = True  # 🔇 กันไม่ให้แบ็คลี่รายงานทีละคนตอนย้ายกันยกทีม
    created_channels = []
    moved_member_ids = set()
    total_moved = 0

    try:
        for i, team in enumerate(teams, 1):
            if not team:
                continue
            room_name = f"ทีม {i}"
            try:
                new_channel = await guild.create_voice_channel(name=room_name, category=category)
            except Exception as e:
                print(f"❌ สร้างห้อง {room_name} ไม่ได้: {e}")
                continue

            created_channels.append(new_channel.id)
            state.created_party_channels.append(new_channel.id)

            for member in team:
                fresh_member = guild.get_member(member.id)
                if fresh_member and fresh_member.voice:
                    try:
                        await fresh_member.edit(voice_channel=new_channel)
                        moved_member_ids.add(fresh_member.id)
                        total_moved += 1
                    except Exception as e:
                        print(f"❌ ย้าย {fresh_member.display_name} เข้าห้อง {room_name} ไม่ได้: {e}")
    finally:
        await asyncio.sleep(1)
        state.is_moving_group = False

    if not created_channels:
        try:
            await interaction.channel.send("❌ สร้างห้องทีมไม่สำเร็จเลยครับ ขอโทษด้วยนะครับ")
        except Exception:
            pass
        return

    # 🛡️ [กันหลุด] ระบบ auto-follow เจ้านาย (follow_creator_task) จะเช็ค room_guard_status
    # ทุกรอบ ถ้าเจ้านายไปอยู่ห้องอื่นระหว่างที่แบ็คลี่ต้องรออยู่ห้องเดิม บอทจะโดนลากตามออกไปทันที
    # เลยต้องเปิดโหมดเฝ้าห้องชั่วคราวไว้ตลอดรอบแยกทีม (เก็บค่าดั้งเดิมไว้คืนให้ตอน /back)
    prev_guard_status = state.room_guard_status.get(guild.id, False)
    state.room_guard_status[guild.id] = True

    # 💾 บันทึก session ของกิลด์นี้ไว้ ให้คำสั่ง /back รู้ว่าต้องพาใครกลับไปห้องไหน
    state.active_team_splits[guild.id] = {
        "origin_channel_id": origin_channel.id,
        "team_channel_ids": created_channels,
        "moved_member_ids": moved_member_ids,
        "prev_guard_status": prev_guard_status,
    }

    try:
        await interaction.channel.send(
            f"🔀 แยกห้องเรียบร้อยครับ! ย้ายไป {len(created_channels)} ห้อง รวม {total_moved} คน\n"
            f"แบ็คลี่จะรออยู่ห้อง **{origin_channel.name}** เหมือนเดิมนะครับ (ล็อกโหมดเฝ้าห้องไว้ชั่วคราว จะได้ไม่แอบตามใครออกไประหว่างแข่ง) "
            f"พอแข่งเสร็จแล้ว ใครก็ได้ในกลุ่มที่ถูกแยกไป พิมพ์ `back` (หรือ `/back`) เพื่อพากลับมารวมกันได้เลยครับ!"
        )
    except Exception as e:
        print(f"❌ ส่งข้อความสรุปแยกห้องไม่ได้: {e}")

    if guild.voice_client:
        try:
            await bagley_speak(
                guild,
                f"แยกห้องเรียบร้อยครับ ผมจะรออยู่ห้อง {origin_channel.name} เหมือนเดิมนะครับ ไม่แอบตามใครออกไปแน่นอน "
                f"พร้อมแล้วพิมพ์ back เพื่อกลับมารวมกันได้เลยครับ"
            )
        except Exception as e:
            print(f"Team room split speak error: {e}")


# ============================================================
# 🎲 ระบบสุ่มของทั่วไป (/random) — เดิมชื่อ /random_map แต่ตอนนี้ใช้สุ่มอะไรก็ได้
# ผู้ใช้พิมพ์รายการเอง (คั่นด้วย , หรือขึ้นบรรทัดใหม่) แบ็คลี่แค่สุ่มให้ฝั่ง Python
# ใช้ได้ทั้งสุ่มแมพ สุ่มชื่อคน สุ่มเลข หรือรายการอะไรก็ได้ที่พิมพ์มา
# (เดิมใช้ AI + Google Search ไปค้นชื่อแมพ แต่โควต้า grounding แยกจากแชทปกติ
#  และจำกัดกว่ามาก ทำให้ 429 บ่อย เลยตัดการพึ่ง AI ออกไปเลย ไม่ต้องยิง API เพิ่ม)
# ============================================================

_RANDOM_ITEM_SPLIT_PATTERN = regex_lib.compile(r"[,\n、，]+")


def _parse_item_list(raw: str):
    """แยกรายการจากข้อความดิบ คั่นด้วย , หรือขึ้นบรรทัดใหม่
    ตัดช่องว่างหน้า-หลัง และตัดตัวซ้ำ (ไม่สนตัวพิมพ์เล็ก/ใหญ่) โดยคงชื่อแบบแรกที่เจอไว้
    """
    seen = set()
    result = []
    for part in _RANDOM_ITEM_SPLIT_PATTERN.split(raw or ""):
        name = part.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result
