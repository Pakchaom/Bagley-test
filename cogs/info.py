"""
Info and Utility Commands
General bot information and utilities
"""
import discord
from discord.ext import commands
from discord import app_commands


class InfoCommands(commands.Cog):
    """Information and utility commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        """Ping the bot to check latency"""
        latency = self.bot.latency * 1000
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Bot latency: **{latency:.2f}ms**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="help", description="Show bot help")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information"""
        embed = discord.Embed(
            title="🤖 Bagley Bot Help",
            description="Available commands:",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="🔧 General",
            value="`/ping` - Check bot status\n`/help` - Show this message",
            inline=False
        )
        embed.add_field(
            name="🎙️ Voice",
            value="`/tts [text]` - Text-to-speech\n`/speak [text]` - Speak in voice",
            inline=False
        )
        embed.add_field(
            name="🎵 Music",
            value="`/play [song]` - Play music\n`/stop` - Stop playback\n`/queue` - Show queue",
            inline=False
        )
        embed.add_field(
            name="🤖 AI",
            value="`/ask [question]` - Ask AI\n`/translate [text]` - Translate text",
            inline=False
        )
        embed.add_field(
            name="⏰ Reminders",
            value="`/remind [time] [message]` - Set reminder\n`/reminders` - View reminders",
            inline=False
        )
        embed.add_field(
            name="👤 Profiles",
            value="`/remember [user] [type] [info]` - Save user info\n`/profile [user]` - View profile",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="status", description="Show bot status")
    async def status(self, interaction: discord.Interaction):
        """Display bot status and statistics"""
        embed = discord.Embed(
            title="📊 Bot Status",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Users", value=str(len(self.bot.users)), inline=True)
        embed.add_field(name="Latency", value=f"{self.bot.latency * 1000:.2f}ms", inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="about", description="About the bot")
    async def about(self, interaction: discord.Interaction):
        """Show information about the bot"""
        embed = discord.Embed(
            title="🤖 Bagley Bot",
            description="An AI-powered Discord bot with voice, music, and memory features",
            color=discord.Color.purple()
        )
        
        embed.add_field(
            name="Features",
            value="• Text-to-speech with Thai voice\n• YouTube music streaming\n• AI chat (Gemini)\n• Reminders\n• User profiles\n• YouTube monitoring",
            inline=False
        )
        
        embed.add_field(name="Prefix", value="`/` (slash commands)", inline=True)
        
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(InfoCommands(bot))
