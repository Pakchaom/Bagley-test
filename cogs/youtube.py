"""
YouTube Monitoring System
Track and alert on new uploads
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import sqlite3
from config.config import YT_API_KEY
from utils import get_database_connection, bagley_speak_wait


class YouTubeMonitoring(commands.Cog):
    """YouTube channel monitoring and alerts"""
    
    def __init__(self, bot):
        self.bot = bot
        if YT_API_KEY:
            self.check_youtube_updates.start()
    
    @app_commands.command(name="yt_add", description="Add YouTube channel to monitor")
    async def yt_add(self, interaction: discord.Interaction, channel_id: str, channel_name: str):
        """Add a YouTube channel to monitor for new uploads"""
        try:
            conn = get_database_connection()
            c = conn.cursor()
            
            c.execute(
                "INSERT OR REPLACE INTO youtube_channels (yt_id, channel_name, last_video_id, guild_id) VALUES (?, ?, ?, ?)",
                (channel_id, channel_name, "", str(interaction.guild.id))
            )
            conn.commit()
            conn.close()
            
            await interaction.response.send_message(
                f"✅ Added YouTube channel: **{channel_name}**"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="yt_remove", description="Remove YouTube channel from monitoring")
    async def yt_remove(self, interaction: discord.Interaction, channel_id: str):
        """Remove a YouTube channel from monitoring"""
        try:
            conn = get_database_connection()
            c = conn.cursor()
            
            c.execute(
                "DELETE FROM youtube_channels WHERE yt_id = ? AND guild_id = ?",
                (channel_id, str(interaction.guild.id))
            )
            conn.commit()
            conn.close()
            
            await interaction.response.send_message("✅ Removed YouTube channel from monitoring")
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="yt_alert_channel", description="Set alert channel")
    async def yt_alert_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set where to send YouTube alerts"""
        try:
            conn = get_database_connection()
            c = conn.cursor()
            
            c.execute(
                "INSERT OR REPLACE INTO youtube_settings (guild_id, target_channel_id) VALUES (?, ?)",
                (str(interaction.guild.id), str(channel.id))
            )
            conn.commit()
            conn.close()
            
            await interaction.response.send_message(
                f"✅ YouTube alerts will be sent to {channel.mention}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @tasks.loop(minutes=3)
    async def check_youtube_updates(self):
        """Check YouTube channels for new uploads"""
        if not YT_API_KEY:
            return
        
        await self.bot.wait_until_ready()
        
        conn = get_database_connection()
        c = conn.cursor()
        
        c.execute("SELECT yt_id, channel_name, last_video_id, guild_id FROM youtube_channels")
        channels = c.fetchall()
        
        for channel_id, name, last_id, guild_id in channels:
            try:
                ch_url = f"https://www.googleapis.com/youtube/v3/channels?key={YT_API_KEY}&id={channel_id}&part=contentDetails"
                ch_res = requests.get(ch_url).json()
                
                if "items" in ch_res and len(ch_res["items"]) > 0:
                    uploads_playlist_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                    
                    playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YT_API_KEY}&playlistId={uploads_playlist_id}&part=snippet&maxResults=1"
                    playlist_res = requests.get(playlist_url).json()
                    
                    if "items" in playlist_res and len(playlist_res["items"]) > 0:
                        latest_item = playlist_res["items"][0]
                        current_video_id = latest_item["snippet"]["resourceId"].get("videoId")
                        title = latest_item["snippet"]["title"]
                        
                        if current_video_id and current_video_id != last_id:
                            await self.send_yt_alert(guild_id, name, title, current_video_id)
                            
                            c.execute(
                                "UPDATE youtube_channels SET last_video_id = ? WHERE yt_id = ? AND guild_id = ?",
                                (current_video_id, channel_id, guild_id)
                            )
                            conn.commit()
                            
            except Exception as e:
                print(f"YouTube update error for {name}: {e}")
        
        conn.close()
    
    async def send_yt_alert(self, guild_id, channel_name, video_title, video_id):
        """Send alert for new YouTube video"""
        try:
            conn = get_database_connection()
            c = conn.cursor()
            
            c.execute("SELECT target_channel_id FROM youtube_settings WHERE guild_id = ?", (guild_id,))
            res = c.fetchone()
            conn.close()
            
            if res:
                target_channel = self.bot.get_channel(int(res[0]))
                if target_channel:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    display_msg = (
                        f"📢 **New Upload Alert!**\n"
                        f"Channel: **{channel_name}**\n"
                        f"Title: **{video_title}**\n"
                        f"{video_url}"
                    )
                    
                    await target_channel.send(display_msg)
                    await bagley_speak_wait(
                        target_channel.guild,
                        f"{channel_name} ลงคลิปใหม่: {video_title}"
                    )
                    
        except Exception as e:
            print(f"Send alert error: {e}")


async def setup(bot):
    await bot.add_cog(YouTubeMonitoring(bot))
