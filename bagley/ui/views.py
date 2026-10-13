"""bagley/ui/views.py — ปุ่ม เมนู และฟอร์ม (discord.ui) ทั้งหมด"""
import asyncio
import discord
from discord import ui

from bagley.core import state
from bagley.core.logutil import print
from bagley.core.security import is_stream_authorized
from bagley.data.storage import get_realtime_name, load_user_data, save_user_data
from bagley.phrases import say
from bagley.voice.tts import bagley_speak


# 1. คลาสสำหรับหน้าต่างเลือกสมาชิก (ใช้ ui.UserSelect ได้เลยเพราะนำเข้าไว้แล้ว)
class KickVoiceSelect(ui.UserSelect):
    def __init__(self, target_time_str: str, delay_seconds: float):
        super().__init__(
            placeholder="จิ้มเลือกรายชื่อพวกที่นอนอืดตรงนี้เลยครับ",
            min_values=1,
            max_values=25
        )
        self.target_time_str = target_time_str
        self.delay_seconds = delay_seconds

    async def callback(self, interaction: discord.Interaction):
        targets = self.values
        self.view.stop()
        
        guild_id = interaction.guild_id
        member_names = ", ".join([get_realtime_name(m.id, m.display_name) for m in targets])
        
        await interaction.response.send_message(
            f"รับทราบครับ! ล็อกเป้าหมายเรียบร้อย แบ็คลี่ตั้งนาฬิกาปลุกไว้ที่เวลา **{self.target_time_str}** "
            f"เพื่อเตรียมเคลียร์: `{member_names}` ครับผม\n"
            f"*(หากต้องการยกเลิกบางคน พิมพ์ `/kickcancel` ได้เลยครับ)*"
        )

        async def member_kick_worker(member: discord.Member):
            try:
                await asyncio.sleep(self.delay_seconds)
                
                if member.voice and member.voice.channel and member.voice.channel.guild.id == guild_id:
                    try:
                        await member.move_to(None, reason=f"แบ็คลี่เคลียร์ก๊วนนอนหลับเมื่อถึงเวลา {self.target_time_str} ครับ")
                        await interaction.channel.send(f"💥 ถึงเวลา {self.target_time_str} แล้ว! ดีดคุณ **{get_realtime_name(member.id, member.display_name)}** ออกจากห้องเสียงเรียบร้อยครับ!")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass
            finally:
                state.active_kick_tasks.pop((guild_id, member.id), None)

        loop = asyncio.get_running_loop()
        for member in targets:
            old_task = state.active_kick_tasks.get((guild_id, member.id))
            if old_task:
                old_task.cancel()
                
            task = loop.create_task(member_kick_worker(member))
            state.active_kick_tasks[(guild_id, member.id)] = task


class KickVoiceView(ui.View):
    def __init__(self, target_time_str: str, delay_seconds: float):
        super().__init__(timeout=60)
        self.add_item(KickVoiceSelect(target_time_str, delay_seconds))


class CancelVoiceSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="จิ้มเลือกรายชื่อที่ต้องการให้ 'รอด' จากคิวเตะครับ...",
            min_values=1,
            max_values=25
        )

    async def callback(self, interaction: discord.Interaction):
        targets = self.values
        self.view.stop()
        
        guild_id = interaction.guild_id
        cancelled_members = []

        for member in targets:
            key = (guild_id, member.id)
            if key in state.active_kick_tasks:
                state.active_kick_tasks[key].cancel()
                state.active_kick_tasks.pop(key, None)
                cancelled_members.append(get_realtime_name(member.id, member.display_name))

        if cancelled_members:
            names = ", ".join(cancelled_members)
            await interaction.response.send_message(
                f"รับทราบครับ! ดึงปลั๊กเรียบร้อย แบ็คลี่ยกเลิกคิวเตะให้: `{names}` ให้อยู่ต่อยาวๆ แล้วครับ!"
            )
        else:
            await interaction.response.send_message(
                "ไม่มีใครโดนยกเลิกครับ รายชื่อที่เลือกมาน่าจะไม่ได้อยู่ในคิวเตะของเซิร์ฟนี้อยู่แล้วครับ", 
                ephemeral=True
            )


class CancelVoiceView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(CancelVoiceSelect())


class IdentityListPaginator(ui.View):
    def __init__(self, title_text: str, data_list: list, per_page: int = 10):
        super().__init__(timeout=120)  # เปิดให้ปุ่มทำงาน 2 นาทีเพื่อเซฟแรม
        self.title_text = title_text
        self.data_list = data_list
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(data_list) - 1) // per_page + 1
        self.update_buttons()

    def create_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.per_page
        end_idx = start_idx + self.per_page
        page_data = self.data_list[start_idx:end_idx]
        
        description_text = ""
        for idx, item in enumerate(page_data, start=start_idx + 1):
            description_text += f"**{idx}.** {item}\n"
            
        if not description_text:
            description_text = "*ไม่มีข้อมูลในหน้านี้ครับ*"

        embed = discord.Embed(
            title=self.title_text,
            description=description_text,
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"หน้า {self.current_page + 1} / {self.total_pages} (ทั้งหมด {len(self.data_list)} รายชื่อ)")
        return embed

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1

    @ui.button(label="◀ ย้อนกลับ", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @ui.button(label="ถัดไป ▶", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def on_timeout(self):
        """เมื่อปล่อยปุ่มทิ้งไว้จนหมดเวลา ให้เปลี่ยนปุ่มเป็นสีเทาและกดไม่ได้คัป"""
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True  # สั่งล็อกปุ่ม
                item.style = discord.ButtonStyle.gray
        
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


# --- 1. View สำหรับสร้างห้องและชวนเพื่อน ---
class GroupMoveView(discord.ui.View):
    def __init__(self, author, members, voice_channels):
        super().__init__(timeout=60)
        self.author = author
        self.selected_members = []
        self.target_channel = None

        # 👥 ดึงรายชื่อเพื่อน (ตัดเอาไม่เกิน 25 คนตามกฎ Discord คัป)
        member_options = [
            discord.SelectOption(label=get_realtime_name(m.id, m.display_name), value=str(m.id), emoji="👤")
            for m in members if not m.bot
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีตัวเลือกเลย ให้ใส่ตัวเลือกหลอกไว้ 1 อันไม่ให้บอทเอ๋อ
        if not member_options:
            member_options.append(discord.SelectOption(label="ไม่มีเพื่อนให้เลือกคัป", value="none"))

        self.member_select = discord.ui.Select(
            placeholder="เลือกเพื่อนที่จะพาไปด้วย (เลือกได้หลายคน)...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

        # 🏠 ดึงรายชื่อห้องเสียง (ตัดเอาไม่เกิน 25 ห้องคัปพ้ม)
        channel_options = [
            discord.SelectOption(label=c.name, value=str(c.id), emoji="🏠")
            for c in voice_channels
        ][:25]
        
        # 🛡️ เซฟตี้ดักจับ: ถ้าไม่มีห้องอื่นให้เลือกเลย ยัดตัวเลือกหลอกกันบอทพัง
        if not channel_options:
            channel_options.append(discord.SelectOption(label="ไม่มีห้องอื่นให้ย้ายไปคัป", value="none"))

        self.channel_select = discord.ui.Select(
            placeholder="เลือกห้องที่จะย้ายไป...",
            options=channel_options
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def member_callback(self, interaction: discord.Interaction):
        if self.member_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีรายชื่อเพื่อนที่ใช้งานได้คัป!", ephemeral=True)
            
        try:
            await interaction.response.defer(ephemeral=True) 
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values

    async def channel_callback(self, interaction: discord.Interaction):
        if self.channel_select.values[0] == "none":
            return await interaction.response.send_message("ไม่มีห้องปลายทางที่ย้ายไปได้คัป!", ephemeral=True)

        self.target_channel = interaction.guild.get_channel(int(self.channel_select.values[0]))
        
        if self.selected_members:
            if interaction.guild.voice_client:
                follow_view = discord.ui.View()
                yes_btn = discord.ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green)
                no_btn = discord.ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

                async def yes_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=True)
                    
                async def no_callback(it: discord.Interaction):
                    try: await it.response.defer(ephemeral=True)
                    except: pass
                    await self.execute_move(it, follow_bot=False)

                yes_btn.callback = yes_callback
                no_btn.callback = no_callback
                follow_view.add_item(yes_btn)
                follow_view.add_item(no_btn)

                await interaction.response.send_message(f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?", view=follow_view)
            
                msg = f"รับทราบครับ! จะให้ผมตามไปที่ห้อง **{self.target_channel.name}** ด้วยมั้ยครับ?"
                await bagley_speak(interaction.guild, msg)
                
            else:
                try: 
                    await interaction.response.defer(ephemeral=True)
                except: 
                    pass
                await self.execute_move(interaction, follow_bot=False)
        else:
            await interaction.response.send_message("รบกวนเลือกเพื่อนก่อนเลือกห้องนะ!", ephemeral=True)

    async def execute_move(self, interaction: discord.Interaction, follow_bot: bool):
        state.is_moving_group = True
    
        try:
            success_count = 0
            for m_id in self.selected_members:
                if m_id == "none": continue
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
        
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(self.target_channel)

        finally:
            await asyncio.sleep(1) 
            state.is_moving_group = False

        try:
            await interaction.edit_original_response(
                content="🚀 " + say("moved_n", n=success_count), 
                view=None
            )
        except discord.NotFound:
            print("⚠️ หมายเหตุ: ย้ายเสร็จแล้วแต่แก้ไขข้อความไม่ได้ (Interaction หมดอายุ) ไม่เป็นไรครับ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนจบงาน: {e}")


# --- 2. View สำหรับสร้างห้องและชวนเพื่อน ---
class PartyCreateView(discord.ui.View):
    def __init__(self, author, members, category, party_name):
        super().__init__(timeout=60)
        self.author = author
        self.members_in_channel = members
        self.category = category
        self.party_name = party_name
        self.selected_members = []

        # สร้างเมนูเลือกเพื่อน (เลือกได้หลายคน)
        member_options = [
            discord.SelectOption(label=get_realtime_name(m.id, m.display_name), value=str(m.id), emoji="👤")
            for m in self.members_in_channel if not m.bot
        ]
        
        self.member_select = discord.ui.Select(
            placeholder="เลือกสมาชิกที่จะพาเข้าปาร์ตี้...",
            min_values=1,
            max_values=len(member_options),
            options=member_options
        )
        self.member_select.callback = self.member_callback
        self.add_item(self.member_select)

    async def member_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"Interaction error: {e}")
            return

        self.selected_members = self.member_select.values
        
        if interaction.guild.voice_client:
            # เมื่อเลือกคนเสร็จ ถามต่อเรื่อง Bagley จะตามไปมั้ย
            follow_view = discord.ui.View()
            yes_btn = discord.ui.Button(label="พา Bagley ไปด้วย", style=discord.ButtonStyle.green, emoji="🤖")
            no_btn = discord.ui.Button(label="ไม่ต้องตามมา", style=discord.ButtonStyle.grey)

            async def yes_callback(it: discord.Interaction):
                try: await it.response.defer(ephemeral=True)
                except: pass
                await self.execute_party_create(it, follow_bot=True)

            async def no_callback(it: discord.Interaction):
                try: await it.response.defer(ephemeral=True)
                except: pass
                await self.execute_party_create(it, follow_bot=False)

            yes_btn.callback = yes_callback
            no_btn.callback = no_callback
            follow_view.add_item(yes_btn)
            follow_view.add_item(no_btn)
    
            await interaction.followup.send(
                content=f"รับทราบครับ! ผมจะสร้างห้อง **'{self.party_name}'** ให้ แล้วจะให้ผมตามไปด้วยมั้ย?", 
                view=follow_view,
                ephemeral=True
            )

            await bagley_speak(interaction.guild, f"รับทราบครับ! ผมจะสร้างห้อง '{self.party_name}' ให้ แล้วจะให้ผมตามไปด้วยมั้ย?")

        else:
            # 🔴 ถ้าบอทไม่ได้อยู่ในห้องเสียง -> ข้ามขั้นตอนดิ่งไปสร้างห้องด่วนจี๋ทันที!
            await self.execute_party_create(interaction, follow_bot=False)

    async def execute_party_create(self, interaction: discord.Interaction, follow_bot: bool):
        state.is_moving_group = True

        try:
            # 1. สร้างห้องใหม่ในหมวดหมู่เดิม
            new_channel = await interaction.guild.create_voice_channel(
                name=self.party_name,
                category=self.category
            )

            state.created_party_channels.append(new_channel.id)

            success_count = 0
            # 2. ย้ายเพื่อนที่เลือก
            for m_id in self.selected_members:
                member = interaction.guild.get_member(int(m_id))
                if member and member.voice:
                    await member.edit(voice_channel=new_channel)
                    success_count += 1

            # 4. ถ้าให้บอทตามไปด้วย
            if follow_bot and interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(new_channel)

        finally:
            # รอให้ระบบ Discord อัปเดตสถานะให้เสร็จก่อน 1 วินาที
            await asyncio.sleep(1) 
            state.is_moving_group = False  # 🔓 ปลดล็อคเสียง: กลับมาพูดได้ตามปกติแล้วครับ

        # 5. แก้ไขข้อความสรุปผล (ครอบ try-except เพื่อกัน Error 404)
        try:
            await interaction.edit_original_response(
                content=f"🎉 สร้างปาร์ตี้ **{self.party_name}** สำเร็จ! พาพรรคพวกเข้าห้องใหม่ {success_count} คนเรียบร้อย!", 
                view=None
            )
        except:
            pass


# --- 3. View สำหรับปุ่มวาร์ปชวนตี้ข้ามห้อง ---
class PartyInviteView(discord.ui.View):
    def __init__(self, target_member, host_voice_channel, timeout=60):
        super().__init__(timeout=timeout)
        self.target_member = target_member
        self.host_voice_channel = host_voice_channel
        self.accepted = False

    @discord.ui.button(label="ตอบรับคำเชิญ (ย้ายห้องทันที)", style=discord.ButtonStyle.green, emoji="🎮")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🛡️ เช็กชัวร์ว่าต้องเป็นคนที่โดนชวนเท่านั้นที่กดได้คัป
        if interaction.user.id != self.target_member.id:
            await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่โดนชวนเท่านั้นนะ!", ephemeral=True)
            return
        
        self.accepted = True
        self.stop()
        await interaction.response.send_message("🛸 รับทราบคัปพ้ม! กำลังวาร์ปข้ามมิติ...", ephemeral=True)
        
        # 🚀 ใช้พลังแอดมิน Move มนุษย์ข้ามห้องทันที!
        try:
            if self.target_member.voice:
                await self.target_member.move_to(self.host_voice_channel)
            else:
                await interaction.followup.send("❌ อ้าว ลุกออกจากห้องเสียงไปซะแล้ว ย้ายไม่สำเร็จคัปพ้ม!", ephemeral=True)
        except Exception as e:
            print(f"❌ บั๊กตอนย้ายห้องมนุษย์: {e}")

    @discord.ui.button(label="ปฏิเสธคำเชิญ", style=discord.ButtonStyle.red, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_member.id:
            await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่โดนชวนเท่านั้นนะ!", ephemeral=True)
            return
        
        self.stop()
        await interaction.response.send_message("👍 รับทราบคัป งั้นผมวาร์ปกลับละน้าา", ephemeral=True)


# --- 1. หน้าตาปุ่ม ✅/❌ ที่จะไปโผล่ใน DM ของเพื่อน (เวอร์ชันส่งลิงก์ห้องเสียงเมื่อกดตกลง) ---
class GatherResponseView(ui.View):
    def __init__(self, inviter, topic, guild, time, channel_id):
        super().__init__(timeout=None)
        self.inviter = inviter
        self.topic = topic
        self.guild = guild
        self.time = time
        self.channel_id = channel_id

    @ui.button(label="ตกลง ✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        
        # 🧠 ดึงชื่อเล่นเรียลไทม์จากคลังสมองของแบ็คลี่
        real_responder_name = get_realtime_name(interaction.user.id, interaction.user.display_name)
        real_inviter_name = get_realtime_name(self.inviter.id, self.inviter.display_name)
        
        # แสดงผลชื่อเล่นในข้อความแชท
        msg = f"✅ **{real_responder_name}** ตอบตกลงภารกิจ: `{self.topic}` ของคุณ {real_inviter_name} แล้ว!"
        if channel: await channel.send(msg)

        vc = self.guild.voice_client
        if vc and vc.is_connected():
            # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองแล้วพูดต่อ
            await bagley_speak(self.guild, f"คุณ {real_responder_name} ตอบตกลงแล้วครับ เดี๋ยวก็คงมาแล้วครับ")

        if self.inviter.voice and self.inviter.voice.channel:
            voice_channel = self.inviter.voice.channel
            try:
                invite = await voice_channel.create_invite(max_age=1800, max_uses=1)
                response_msg = f"รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว\nนี่คือลิงก์เข้าห้องเสียงครับ วาร์ปตามไปได้เลย: {invite.url}"
            except Exception as e:
                response_msg = f"รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่บอทสร้างลิงก์เชิญไม่สำเร็จ: {e})"
        else:
            response_msg = "รับทราบครับ! ผมแจ้งทางเซิร์ฟเวอร์ให้แล้ว (แต่ตอนนี้คนเรียกไม่ได้อยู่ในห้องเสียงแล้วครับ)"

        await interaction.response.send_message(response_msg, ephemeral=True)
        self.stop()

    @ui.button(label="ไม่สะดวก ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        channel = self.guild.get_channel(self.channel_id)
        
        # 🧠 ดึงชื่อเล่นเรียลไทม์จากคลังสมอง
        real_responder_name = get_realtime_name(interaction.user.id, interaction.user.display_name)
        
        msg = f"❌ **{real_responder_name}** ไม่สะดวกมาร่วมภารกิจ: `{self.topic}`"
        if channel: await channel.send(msg)
        
        vc = self.guild.voice_client
        if vc and vc.is_connected():
            # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองแล้วพูดต่อ
            await bagley_speak(self.guild, f"คุณ {real_responder_name} ปฏิเสธครับ สงสัยเขาจะติดธุระ")

        await interaction.response.send_message("รับทราบครับ ไว้นัดกันใหม่วันหลังนะ", ephemeral=True)
        self.stop()


# --- ส่วนหน้าตาเมนู คำสั่ง gather ---
class RoleSelect(discord.ui.RoleSelect):
    def __init__(self, author, topic, time):
        super().__init__(placeholder="เลือก Role ที่ต้องการเรียก...", min_values=1, max_values=10)
        self.author = author
        self.topic = topic
        self.time = time

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("เฉพาะคนเรียกเท่านั้นที่เลือกได้ครับ!", ephemeral=True)
            return

        await interaction.response.defer()
        target_roles = self.values # รายชื่อ Role ที่เลือกมา
        members_to_ping = set()
        for role in target_roles:
            for member in role.members:
                if not member.bot: members_to_ping.add(member)

        count = 0
        for member in members_to_ping:
            try:
                # สร้าง View ปุ่มกดสำหรับคนนี้
                view = GatherResponseView(self.author, self.topic, interaction.guild, self.time, interaction.channel.id)
        
                # สร้าง Embed สวยๆ
                embed = discord.Embed(title="🔔 มีสัญญาณเรียกตัวด่วน!", color=discord.Color.gold())
                embed.description = f"คุณ **{get_realtime_name(self.author.id, self.author.display_name)}** กำลังเรียกหารวมพล!"
                embed.add_field(name="ภารกิจ", value=f"**{self.topic}**", inline=False)
                embed.add_field(name="นัดหมายเวลา", value=f"`{self.time}`", inline=True)
                embed.set_footer(text="กรุณากดปุ่มเพื่อยืนยันสถานะครับ")

                await member.send(embed=embed, view=view)
                count += 1
            except: continue

        role_names = ", ".join([r.name for r in target_roles])
        await interaction.followup.send(f"กระจายคำเชิญภารกิจ `{self.topic}` ให้ยศ {role_names} รวม {count} ท่านเรียบร้อย!")

        if interaction.guild.voice_client:
            await bagley_speak(interaction.guild, f"กระจายสัญญาณแจ้งเตือนยศ {role_names} เรียบร้อยแล้วครับ รวมทั้งหมด {count} ท่านครับ")


# --- คลาสสำหรับเลือกคนรายบุคคล ---
class MemberSelect(discord.ui.UserSelect):
    def __init__(self, author, topic, time):
        super().__init__(placeholder="เลือกเพื่อนรายตัวที่ต้องการเรียก...", min_values=1, max_values=10)
        self.author = author
        self.topic = topic
        self.time = time

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("เฉพาะคนเรียกเท่านั้นที่เลือกได้ครับ!", ephemeral=True)
            return

        await interaction.response.defer()
        target_members = self.values # รายชื่อเพื่อนที่เลือก
        
        count = 0
        for member in target_members:
            if member.bot: continue
            try:
                view = GatherResponseView(self.author, self.topic, interaction.guild, self.time, interaction.channel.id)
                embed = discord.Embed(title="🔔 มีสัญญาณเรียกตัวด่วน!", color=discord.Color.gold())
                embed.description = f"คุณ **{get_realtime_name(self.author.id, self.author.display_name)}** กำลังเรียกหาคุณเป็นการส่วนตัว!"
                embed.add_field(name="ภารกิจ", value=f"**{self.topic}**", inline=False)
                embed.add_field(name="นัดหมายเวลา", value=f"`{self.time}`", inline=True)
                
                await member.send(embed=embed, view=view)
                count += 1
            except: continue

        await interaction.followup.send(f"ส่งคำเชิญแบบระบุตัวตนให้เพื่อน {count} ท่านเรียบร้อยครับ!")

        if interaction.guild.voice_client:
            await bagley_speak(interaction.guild, f"ส่งคำเชิญระบุตัวบุคคลสำหรับภารกิจ {self.topic} เรียบร้อยแล้วครับ")


# ---  RoleSelectView 2 เมนู ---
class RoleSelectView(discord.ui.View):
    def __init__(self, author, topic, time):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(author, topic, time)) # เมนูเลือก Role
        self.add_item(MemberSelect(author, topic, time)) # เมนูเลือกเพื่อน


# ==========================================
# 📑 [ส่วนเสริม: กล่องข้อความ Modal สำหรับลงทะเบียน]
# ==========================================
class RegisterModal(discord.ui.Modal):
    def __init__(self, target_role_id: int):
        super().__init__(title="ฟอร์มลงทะเบียนประวัติกับ Bagley")
        self.target_role_id = target_role_id
        
        self.nickname_input = discord.ui.TextInput(
            label="ชื่อเล่นของคุณ (สำหรับให้บอทเรียกและบันทึก)",
            placeholder="กรุณาพิมพ์ชื่อเล่นของคุณที่นี่...",
            required=True,
            max_length=20
        )
        self.birthday_input = discord.ui.TextInput(
            label="วันเกิดของคุณ (รูปแบบ วัน/เดือน เช่น 25/12)",
            placeholder="วว/ดด (เช่น 07/06 หรือ 14/02) หรือเว้นว่างไว้ก็ได้คัป",
            required=False,
            max_length=5
        )
        
        self.add_item(self.nickname_input)
        self.add_item(self.birthday_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        new_nickname = self.nickname_input.value.strip()
        birthday = self.birthday_input.value.strip() or "ยังไม่ระบุ"

        guild = interaction.guild
        member = interaction.user
        role = guild.get_role(int(self.target_role_id))

        try:
            data_memory = load_user_data() 
            user_id = str(member.id)
            
            if user_id not in data_memory or not isinstance(data_memory[user_id], dict):
                data_memory[user_id] = {}
                
            data_memory[user_id]["nickname"] = new_nickname
            data_memory[user_id]["birthday"] = birthday
            
            save_user_data(data_memory) 
            print(f"DEBUG: [Register] ซิงค์ข้อมูล {new_nickname} และวันเกิด {birthday} ลงคลังหลักเรียบร้อย!")
        except Exception as e_db:
            print(f"❌ เกิดข้อผิดพลาดขณะเซฟลงฐานข้อมูลหลัก JSON: {e_db}")

        # ==========================================
        # 👑 [มอบยศตำแหน่ง + เปลี่ยนชื่อแสดงผลในดิสคอร์ด]
        # ==========================================
        try:
            await member.edit(nick=new_nickname)
            
            if role:
                await member.add_roles(role)
            
            await interaction.followup.send(
                f"🎉 **แบ็คลี่ดำเนินการลงทะเบียนเสร็จสรรพเรียบร้อยครับ!**\n"
                f"• เปลี่ยนชื่อในดิสคอร์ดเป็น: **{new_nickname}**\n"
                f"• บันทึกวันเกิดลงคลังสมองกล: **{birthday}**\n"
                f"• มอบยศตำแหน่ง: **{role.name if role else 'ไม่พบยศ'}** เรียบร้อยครับ!\n\n"
                f"*(วันหลังหากอยากแก้ไขชื่อเล่นหรือวันเกิด สามารถพิมพ์ `/register` เพื่ออัปเดตใหม่ได้ตลอดเวลาเลยน้า)*", 
                ephemeral=True
            )
            
            await bagley_speak(guild, f"ยินดีต้อนรับสมาชิกใหม่ คุณ {new_nickname} ครับ")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ แบ็คลี่เปลี่ยนชื่อหรือให้ยศไม่ได้! (ตรวจสอบลำดับยศของบอทด้วยนะครับ)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ เกิดข้อผิดพลาดในระบบ: {e}", ephemeral=True)


class PullRoomView(ui.View):
    def __init__(self, author, target_channel):
        super().__init__(timeout=60)
        self.author = author
        self.target_channel = target_channel # ห้องหลักที่คุณชะอมนั่งอยู่คัป

        # 🔮 เปลี่ยนมาใช้ ChannelSelect ดึงเฉพาะห้องเสียง (Voice) ทั้งหมดในเซิร์ฟเวอร์แบบ Auto
        # ไม่โดนจำกัดที่ 25 ห้องแบบเดิม และสามารถพิมพ์ค้นหาชื่อห้องได้ด้วยคัปพ้ม!
        self.channel_select = ui.ChannelSelect(
            placeholder="พิมพ์ค้นหา หรือเลือกห้องต้นทางที่จะดึงคนมา...",
            channel_types=[discord.ChannelType.voice] # กรองให้เห็นเฉพาะห้องเสียงเท่านั้นคัป
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    async def channel_callback(self, interaction: discord.Interaction):
        # 🔒 เช็กสิทธิ์คนกด ต้องเป็นคนใช้คำสั่งเท่านั้นคัปพ้ม
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("ท่านอื่นห้ามกดเล่นน้าคัป!", ephemeral=True)

        # 🚪 ดึงข้อมูลห้องต้นทางที่คุณเลือกคลิกมาจาก Dropdown อัจฉริยะ
        source_channel = self.channel_select.values[0]
        
        # 🚨 ดักเซฟตี้: กันคุณเลือกห้องเสียงเดียวกับที่ตัวเองนั่งอยู่คัป 5555
        if source_channel.id == self.target_channel.id:
            return await interaction.response.send_message("❌ คุณจะดึงคนจากห้องเดียวกันมาหาตัวเองไม่ได้น้าคัปพ้ม!", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        # 👥 คัดกรองมนุษย์ในห้องนั้น (ไม่นับบอทตามลอจิกเดิมของคุณเป๊ะ ๆ)
        if source_channel and isinstance(source_channel, discord.VoiceChannel):
            members_to_move = [m for m in source_channel.members if not m.bot]
            
            if not members_to_move:
                return await interaction.followup.send(f"❌ ห้อง **{source_channel.name}** ไม่มีคนอยู่เลยคัป!", ephemeral=True)

            success_count = 0
            # 🚀 ทำการเหมาเข่งย้ายห้องตามลอจิกเดิมของคุณคัปพ้ม!
            for member in members_to_move:
                try:
                    await member.edit(voice_channel=self.target_channel)
                    success_count += 1
                except:
                    pass

            # 🎉 อัปเดตข้อความเดิมเมื่อทำงานเสร็จสิ้น
            await interaction.edit_original_response(
                content=f"🚀 วาร์ปเพื่อน ๆ จากห้อง **{source_channel.name}** มาที่ห้อง **{self.target_channel.name}** ทั้งหมด {success_count} คน เรียบร้อยคัปพ้ม!",
                view=None
            )
            
            # 🔊 แบ็คลี่ (ลุงนิวัฒน์) รายงานส่งเสียงในห้องเสียงหลักคัป
            msg = f"ย้ายปาร์ตี้จากห้อง {source_channel.name} กลับมารวมกันเรียบร้อยแล้วครับ"
            await bagley_speak(interaction.guild, msg)
        else:
            await interaction.followup.send("หาห้องเสียงดังกล่าวไม่เจอครับ!", ephemeral=True)


# ============================================================
# 🎥 [โหมดสตรีม] ปุ่มเปิด/ปิดโหมดสตรีมทีเดียว รวม 4 อย่าง:
#   1) ปิดระบบ "ชวนตี้" (party_matcher_disabled_guilds)
#   2) ปิดแจ้งเตือนเวลาเที่ยงวัน/เที่ยงคืน (daily_announcement_status)
#   3) รับคำสั่งเฉพาะเจ้าของบอท/คนที่กำลังสตรีมอยู่เท่านั้น (stream_mode_status -> เช็คใน
#      bot.check / tree.interaction_check / ก่อนเรียก ai_route_and_execute ด้านบนของไฟล์)
#   4) ปิดระบบพูดทักทายคนเข้า-ออกห้องเสียง (voice_report_status)
# ปิดโหมดสตรีมแล้ว จะคืนค่าทั้ง 4 อย่างกลับไปเป็น "เปิด" (ค่าเริ่มต้นเดิมของบอท) ให้ทั้งหมด
# ============================================================
def _bagley_apply_stream_mode(guild_id: int, enable: bool):
    """ตั้งค่าสถานะทั้ง 4 ระบบให้ตรงกับโหมดสตรีมที่ต้องการ (enable=True คือ 'เปิดโหมดสตรีม')"""
    state.stream_mode_status[guild_id] = enable
    if enable:
        state.party_matcher_disabled_guilds.add(guild_id)      # เปิดโหมดสตรีม -> ปิดชวนตี้
    else:
        state.party_matcher_disabled_guilds.discard(guild_id)
    state.daily_announcement_status[guild_id] = not enable    # เปิดโหมดสตรีม -> ปิดแจ้งเที่ยงวัน/เที่ยงคืน
    state.voice_report_status[guild_id] = not enable          # เปิดโหมดสตรีม -> ปิดทักทายคนเข้า-ออกห้อง


    # ข้อ 3 (รับคำสั่งเฉพาะเจ้าของบอท/คนที่กำลังสตรีม) อ่านค่าจาก stream_mode_status ตรงๆ ผ่าน
    # is_stream_mode_on() ที่ bot.check / tree.interaction_check / ai_route_and_execute เช็คอยู่แล้ว


class StreamModeView(discord.ui.View):
    """View แบบปุ่มเดียวกดสลับเปิด/ปิดโหมดสตรีม (persistent - ไม่หมดอายุ) — ปุ่มนี้กดได้เฉพาะ
    เจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้น (เงื่อนไขเดียวกับที่ใช้จำกัดสิทธิ์สั่งคำสั่งตอนเปิดโหมดสตรีม)"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self._sync_button_label()

    def _sync_button_label(self):
        is_on = state.stream_mode_status.get(self.guild_id, False)
        self.toggle_button.label = "🔴 ปิดโหมดสตรีม" if is_on else "🎥 เปิดโหมดสตรีม"
        self.toggle_button.style = discord.ButtonStyle.red if is_on else discord.ButtonStyle.green

    @discord.ui.button(label="🎥 เปิดโหมดสตรีม", style=discord.ButtonStyle.green, custom_id="bagley_stream_mode_toggle")
    async def toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้ในเซิร์ฟเวอร์เท่านั้นครับ", ephemeral=True)
            return

        # 🔒 กดปุ่มนี้ได้เฉพาะเจ้าของบอท/คนที่กำลังสตรีมอยู่เท่านั้น (กันคนอื่นมากดเล่น)
        if not is_stream_authorized(interaction.user, guild):
            await interaction.response.send_message(
                "🛑 ปุ่มนี้กดได้เฉพาะเจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้นนะครับ", ephemeral=True
            )
            return

        new_status = not state.stream_mode_status.get(guild.id, False)
        _bagley_apply_stream_mode(guild.id, new_status)
        self._sync_button_label()

        if new_status:
            desc = (
                "✅ **เปิดโหมดสตรีมแล้วครับ!**\n"
                "1️⃣ ปิดระบบชวนตี้ (ปิดหาคนเล่นเกมเดียวกัน)\n"
                "2️⃣ ปิดแจ้งเตือนเที่ยงวัน/เที่ยงคืน\n"
                "3️⃣ รับคำสั่งเฉพาะเจ้าของบอทหรือคนที่กำลังสตรีมอยู่เท่านั้น\n"
                "4️⃣ ปิดระบบพูดทักทายคนเข้า-ออกห้องเสียง"
            )
            voice_msg = "เปิดโหมดสตรีมแล้วครับ ผมจะเงียบๆ ไม่รบกวนตอนไลฟ์นะครับ"
        else:
            desc = "🔓 **ปิดโหมดสตรีมแล้วครับ!** คืนค่าทั้ง 4 ระบบกลับเป็นปกติเรียบร้อยครับ"
            voice_msg = "ปิดโหมดสตรีมแล้วครับ กลับมาทำงานตามปกติแล้วนะครับ"

        embed = discord.Embed(
            title="🎥 โหมดสตรีม",
            description=desc,
            color=0xff4d4d if new_status else 0x2ecc71,
        )
        await interaction.response.edit_message(embed=embed, view=self)

        if not state.is_playing_music:
            try:
                await bagley_speak(guild, voice_msg)
            except Exception as e:
                print(f"Stream Mode Toggle Speech Error: {e}")


class ScheduleDeleteView(discord.ui.View):
    """เมนู Dropdown ให้เลือกว่าจะลบตารางนัดรายการไหนออกจากคลังความจำ (ใช้กับ /delete_schedule)"""
    def __init__(self, author, schedules: list):
        super().__init__(timeout=60)
        self.author = author
        self.message = None

        # 🔒 Discord จำกัด Select ได้สูงสุด 25 ตัวเลือก เอาแค่ 25 รายการที่ใกล้ถึงที่สุดก่อน
        display_schedules = schedules[:25]

        options = []
        for s in display_schedules:
            label = f"{s.get('date', 'ไม่ระบุวันที่')} ⏰ {s.get('time', 'ไม่ระบุเวลา')}"[:100]
            description = (s.get("event") or "ไม่ระบุกิจกรรม")[:100]
            options.append(
                discord.SelectOption(label=label, description=description, value=s.get("id"), emoji="📌")
            )

        self.select_menu = discord.ui.Select(
            placeholder="เลือกตารางนัดหมายที่ต้องการลบ...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        # 🔒 กันคนอื่นมากดเมนูของคนที่ไม่ใช่เจ้าของคำสั่ง
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                "อันนี้เป็นเมนูของคนที่สั่งคำสั่งนี้เท่านั้นนะครับ ลองพิมพ์ `/delete_schedule` เองดูได้เลยครับ",
                ephemeral=True
            )

        target_id = self.select_menu.values[0]

        user_data = load_user_data()
        schedules = user_data.get("schedules", [])

        removed = None
        remaining = []
        for s in schedules:
            if removed is None and s.get("id") == target_id:
                removed = s
                continue
            remaining.append(s)

        # ปิดเมนูไว้กันกดซ้ำ ไม่ว่าจะลบสำเร็จหรือไม่ก็ตาม
        for item in self.children:
            item.disabled = True

        if removed is None:
            return await interaction.response.edit_message(
                content="❌ ไม่พบรายการนี้แล้วครับ (อาจถูกลบไปก่อนหน้านี้แล้ว)",
                view=self
            )

        user_data["schedules"] = remaining
        save_user_data(user_data)

        await interaction.response.edit_message(
            content=(
                f"🗑️ **ลบตารางนัดหมายเรียบร้อยครับ!**\n"
                f"📌 กิจกรรม: **{removed.get('event', 'ไม่ระบุกิจกรรม')}**\n"
                f"📅 วันที่: **{removed.get('date', 'ไม่ระบุวันที่')}** ⏰ เวลา: **{removed.get('time', 'ไม่ระบุเวลา')}**"
            ),
            view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
