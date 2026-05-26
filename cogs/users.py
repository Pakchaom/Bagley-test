"""
User Profile and Data Commands
Store and retrieve user information
"""
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from utils import load_user_data, save_user_data


class UserProfileCommands(commands.Cog):
    """User profile and memory system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="remember", description="Store information about someone")
    async def remember(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        info_type: str,
        info: str
    ):
        """Remember user information (nickname, birthday, etc)"""
        try:
            data = load_user_data()
            user_id_str = str(user.id)
            
            if user_id_str not in data or isinstance(data[user_id_str], str):
                data[user_id_str] = {
                    "nickname": "No nickname",
                    "birthday": "Not specified"
                }
            
            if info_type.lower() == "birthday":
                data[user_id_str]["birthday"] = info
                msg = f"✅ Saved birthday for {user.mention}: **{info}**"
            else:
                data[user_id_str]["nickname"] = info
                msg = f"✅ Saved nickname for {user.mention}: **{info}**"
            
            save_user_data(data)
            await interaction.response.send_message(msg)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="profile", description="View user profile")
    async def profile(self, interaction: discord.Interaction, user: discord.User = None):
        """View user's saved profile"""
        if user is None:
            user = interaction.user
        
        try:
            data = load_user_data()
            user_id_str = str(user.id)
            
            if user_id_str not in data:
                await interaction.response.send_message(
                    f"❌ No profile data for {user.mention}",
                    ephemeral=True
                )
                return
            
            info = data[user_id_str]
            
            if isinstance(info, str):
                profile_text = f"**{user.mention}**: {info}"
            else:
                nickname = info.get("nickname", "Not set")
                birthday = info.get("birthday", "Not set")
                profile_text = (
                    f"**Profile for {user.mention}:**\n"
                    f"🎭 Nickname: {nickname}\n"
                    f"🎂 Birthday: {birthday}"
                )
            
            await interaction.response.send_message(profile_text)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="profiles", description="List all saved profiles")
    async def profiles(self, interaction: discord.Interaction):
        """List all saved user profiles in this server"""
        try:
            data = load_user_data()
            guild = interaction.guild
            
            profile_list = "📋 **Saved Profiles:**\n"
            has_profiles = False
            
            for user_id_str, info in data.items():
                if user_id_str == "reminders":
                    continue
                
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                has_profiles = True
                if isinstance(info, dict):
                    nickname = info.get("nickname", "Not set")
                    birthday = info.get("birthday", "Not set")
                    profile_list += f"• {member.mention}: {nickname} (Born: {birthday})\n"
                else:
                    profile_list += f"• {member.mention}: {info}\n"
            
            if has_profiles:
                await interaction.response.send_message(profile_list)
            else:
                await interaction.response.send_message(
                    "📋 No profiles saved for this server!",
                    ephemeral=True
                )
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="forget", description="Delete user profile data")
    async def forget(self, interaction: discord.Interaction, user: discord.User = None):
        """Delete saved profile data"""
        if user is None:
            user = interaction.user
        
        try:
            data = load_user_data()
            user_id_str = str(user.id)
            
            if user_id_str in data:
                del data[user_id_str]
                save_user_data(data)
                await interaction.response.send_message(
                    f"✅ Deleted profile for {user.mention}"
                )
            else:
                await interaction.response.send_message(
                    f"❌ No profile found for {user.mention}",
                    ephemeral=True
                )
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserProfileCommands(bot))
