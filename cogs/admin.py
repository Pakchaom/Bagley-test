"""
Admin Commands Cog
Owner-only commands for bot management
"""
import discord
from discord.ext import commands
from discord import app_commands
from config.config import OWNER_DISCORD_ID, ALLOWED_SHUTDOWN_USERS, ALLOWED_TEACH_USERS
from utils import load_user_data, save_user_data


class AdminCommands(commands.Cog):
    """Admin and owner-only commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="shutdown", description="Shutdown the bot (Owner only)")
    async def shutdown(self, interaction: discord.Interaction):
        """Shutdown bot - owner only"""
        if interaction.user.id not in ALLOWED_SHUTDOWN_USERS:
            await interaction.response.send_message(
                "❌ You don't have permission to shutdown the bot!",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message("🛑 Shutting down...")
        await self.bot.close()
    
    @app_commands.command(name="teach", description="Teach the bot new responses")
    async def teach(self, interaction: discord.Interaction, keyword: str, response: str):
        """Teach bot new keyword-response pairs"""
        if interaction.user.id not in ALLOWED_TEACH_USERS:
            await interaction.response.send_message(
                "❌ You don't have permission to teach the bot!",
                ephemeral=True
            )
            return
        
        try:
            import sqlite3
            conn = sqlite3.connect('data/bagley_memory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO teach_memory (keyword, response) VALUES (?, ?)",
                          (keyword.lower(), response))
            conn.commit()
            conn.close()
            
            await interaction.response.send_message(
                f"✅ เรียนรู้สำเร็จครับเมท! ตั้งชื่อว่า **{keyword}** -> **{response}**",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="sync", description="Sync commands (Owner only)")
    async def sync(self, interaction: discord.Interaction):
        """Sync commands with Discord - owner only"""
        if interaction.user.id != OWNER_DISCORD_ID:
            await interaction.response.send_message(
                "❌ Owner only!",
                ephemeral=True
            )
            return
        
        try:
            synced = await self.bot.tree.sync()
            await interaction.response.send_message(
                f"✅ Synced {len(synced)} commands",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
