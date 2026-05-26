"""
Reminder Commands
User reminders and friend notifications
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
import re as regex_lib
from utils import add_reminder, get_reminders_for_user, load_reminders, save_reminders, load_user_data, bagley_hijack_alert


class ReminderCommands(commands.Cog):
    """Reminder and notification system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()
        self.check_friend_reminders.start()
    
    @app_commands.command(name="remind", description="Set a reminder")
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        """Set a reminder at specific time (HH:MM format)"""
        try:
            # Validate time format
            if ':' not in time:
                await interaction.response.send_message(
                    "❌ Use HH:MM format (e.g., 21:00)",
                    ephemeral=True
                )
                return
            
            add_reminder(interaction.user.id, time, message)
            
            await interaction.response.send_message(
                f"⏰ Reminder set for **{time}**: {message}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="reminders", description="View your reminders")
    async def reminders(self, interaction: discord.Interaction):
        """Display all pending reminders"""
        reminders = get_reminders_for_user(interaction.user.id)
        
        if reminders:
            await interaction.response.send_message(
                f"📋 **Your Reminders:**\n{reminders}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "📋 No reminders set!",
                ephemeral=True
            )
    
    @app_commands.command(name="remind_friend", description="Set reminder for friend")
    async def remind_friend(
        self, 
        interaction: discord.Interaction, 
        friend: discord.User, 
        time: str, 
        message: str
    ):
        """Set a reminder for a friend"""
        try:
            if ':' not in time:
                await interaction.response.send_message(
                    "❌ Use HH:MM format (e.g., 21:00)",
                    ephemeral=True
                )
                return
            
            reminders = load_reminders()
            reminders.append({
                "target_id": str(friend.id),
                "from": interaction.user.display_name,
                "time": time,
                "text": message
            })
            save_reminders(reminders)
            
            await interaction.response.send_message(
                f"⏰ Set reminder for {friend.mention} at **{time}**: {message}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="clear_reminders", description="Clear all reminders")
    async def clear_reminders(self, interaction: discord.Interaction):
        """Clear all your reminders"""
        from utils import load_user_data, save_user_data
        
        data = load_user_data()
        user_reminders = [r for r in data.get("reminders", []) 
                         if r['user_id'] != str(interaction.user.id)]
        data["reminders"] = user_reminders
        save_user_data(data)
        
        await interaction.response.send_message(
            "✅ All your reminders cleared!",
            ephemeral=True
        )
    
    @tasks.loop(minutes=1)
    async def check_reminders(self):
        """Check for pending reminders"""
        await self.bot.wait_until_ready()
        
        now_colon = datetime.now().strftime("%H:%M")
        now_dot = datetime.now().strftime("%H.%M")
        
        from utils import load_user_data, save_user_data
        
        data = load_user_data()
        reminders = data.get("reminders", [])
        
        remaining_reminders = []
        updated = False
        
        for r in reminders:
            if r['time'] == now_colon or r['time'] == now_dot:
                user_id = int(r['user_id'])
                try:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        content = r['content']
                        
                        # Check if user is in voice
                        member = None
                        for guild in self.bot.guilds:
                            m = guild.get_member(user_id)
                            if m and m.voice and m.voice.channel:
                                member = m
                                break
                        
                        if member:
                            # Alert in voice channel
                            self.bot.loop.create_task(
                                bagley_hijack_alert(member.voice.channel, content)
                            )
                        else:
                            # Send DM
                            await user.send(f"🔔 Reminder: {content}")
                    
                    updated = True
                    
                except Exception as e:
                    print(f"Reminder error: {e}")
                    remaining_reminders.append(r)
            else:
                remaining_reminders.append(r)
        
        if updated:
            data["reminders"] = remaining_reminders
            save_user_data(data)
    
    @tasks.loop(minutes=1)
    async def check_friend_reminders(self):
        """Check friend reminders"""
        await self.bot.wait_until_ready()
        
        reminders = load_reminders()
        if not reminders:
            return
        
        now = datetime.now().strftime("%H:%M")
        updated_reminders = []
        has_changed = False
        
        for rem in reminders:
            if rem['time'] == now:
                try:
                    target_id = int(rem['target_id'])
                    user = await self.bot.fetch_user(target_id)
                    content = rem['text']
                    
                    if user:
                        member = None
                        for guild in self.bot.guilds:
                            m = guild.get_member(target_id)
                            if m and m.voice and m.voice.channel:
                                member = m
                                break
                        
                        if member:
                            self.bot.loop.create_task(
                                bagley_hijack_alert(member.voice.channel, content)
                            )
                        else:
                            await user.send(f"⏰ Reminder: {content}")
                    
                    has_changed = True
                    
                except Exception as e:
                    print(f"Friend reminder error: {e}")
                    updated_reminders.append(rem)
            else:
                updated_reminders.append(rem)
        
        if has_changed:
            save_reminders(updated_reminders)


async def setup(bot):
    await bot.add_cog(ReminderCommands(bot))
