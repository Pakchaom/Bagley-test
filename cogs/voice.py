"""
Voice and Text-to-Speech Commands
Handle voice channel operations and TTS
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime
from utils import bagley_speak_wait, bagley_hijack_alert, load_voice_data, save_voice_data


class VoiceCommands(commands.Cog):
    """Voice channel and TTS commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.voice_action_cooldowns = {}
        self.voice_report_status = {}
        self.track_voice_stats.start()
    
    @app_commands.command(name="tts", description="Text-to-speech in voice channel")
    async def tts(self, interaction: discord.Interaction, text: str):
        """Convert text to speech and play in voice channel"""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You need to be in a voice channel!",
                ephemeral=True
            )
            return
        
        guild = interaction.guild
        if not guild.voice_client:
            await interaction.user.voice.channel.connect()
        
        await interaction.response.defer()
        await bagley_speak_wait(guild, text)
        await interaction.followup.send(f"🎙️ Spoken: **{text}**")
    
    @app_commands.command(name="speak", description="Speak in voice channel")
    async def speak(self, interaction: discord.Interaction, text: str):
        """Alias for TTS command"""
        await self.tts(interaction, text)
    
    @app_commands.command(name="disconnect", description="Disconnect from voice channel")
    async def disconnect(self, interaction: discord.Interaction):
        """Bot leaves voice channel"""
        if not interaction.guild.voice_client:
            await interaction.response.send_message(
                "❌ Bot is not in a voice channel!",
                ephemeral=True
            )
            return
        
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Disconnected from voice channel")
    
    @app_commands.command(name="voice_stats", description="Show voice channel statistics")
    async def voice_stats(self, interaction: discord.Interaction):
        """Display voice usage statistics"""
        data = load_voice_data()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        if not data or data.get("date") != today_str or not data.get("stats"):
            await interaction.response.send_message(
                "📊 No voice activity today yet!",
                ephemeral=True
            )
            return
        
        stats = data["stats"]
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]['total_time'], reverse=True)[:10]
        
        report = f"📊 **Voice Statistics (Today: {today_str})**\n"
        for i, (u_id, info) in enumerate(sorted_stats, 1):
            ts = info['total_time']
            time_display = f"{int(ts//3600)}h {int((ts%3600)//60)}m" if ts >= 3600 else f"{int(ts//60)}m {int(ts%60)}s"
            report += f"{i}. {info['name']}: {time_display}\n"
        
        await interaction.response.send_message(report)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track voice channel joins/leaves"""
        guild = member.guild
        guild_id = guild.id
        
        # Skip bot actions
        if member.bot:
            return
        
        # Initialize report status if not exists
        if guild_id not in self.voice_report_status:
            self.voice_report_status[guild_id] = True
        
        # Track voice time
        now = datetime.now()
        
        # Member joined voice
        if before.channel is None and after.channel is not None:
            if self.voice_report_status.get(guild_id, True):
                if guild.voice_client:
                    await bagley_speak_wait(guild, f"ยินดีต้อนรับ {member.display_name} เข้าห้องเสียง!")
        
        # Member left voice
        elif before.channel is not None and after.channel is None:
            if self.voice_report_status.get(guild_id, True):
                if guild.voice_client:
                    await bagley_speak_wait(guild, f"{member.display_name} ออกจากห้องเสียงแล้วครับ")
    
    @tasks.loop(minutes=1)
    async def track_voice_stats(self):
        """Background task to track voice statistics"""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            if guild.voice_client and guild.voice_client.channel:
                for member in guild.voice_client.channel.members:
                    if member.bot:
                        continue
                    
                    data = load_voice_data()
                    today = datetime.now().strftime("%Y-%m-%d")
                    
                    if data.get("date") != today:
                        data = {"date": today, "stats": {}}
                    
                    user_id = str(member.id)
                    if user_id not in data["stats"]:
                        data["stats"][user_id] = {"name": member.display_name, "total_time": 0}
                    
                    data["stats"][user_id]["total_time"] += 60
                    save_voice_data(data)


async def setup(bot):
    await bot.add_cog(VoiceCommands(bot))
