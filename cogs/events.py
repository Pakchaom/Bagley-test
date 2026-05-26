"""
Events Cog
Handle Discord events like member joins, leaves, etc
"""
import discord
from discord.ext import commands


class EventHandlers(commands.Cog):
    """Discord event handlers"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Bot ready event"""
        print(f'✅ {self.bot.user.name} is online')
        
        # Sync commands
        try:
            synced = await self.bot.tree.sync()
            print(f"📡 Synced {len(synced)} commands")
        except Exception as e:
            print(f"Sync error: {e}")
        
        # Load cogs
        print("📦 All cogs loaded successfully")
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Member joins guild"""
        print(f"👤 {member.display_name} joined {member.guild.name}")
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Member leaves guild"""
        print(f"👋 {member.display_name} left {member.guild.name}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle incoming messages"""
        if message.author == self.bot.user:
            return
        
        # Let bot process commands
        await self.bot.process_commands(message)


async def setup(bot):
    await bot.add_cog(EventHandlers(bot))
