"""
Music Playback Commands
Handle YouTube music streaming and queue management
"""
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
from config.config import YT_API_KEY, FFMPEG_PATH
from utils import bagley_speak_wait


class MusicCommands(commands.Cog):
    """Music playback and queue management"""
    
    def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        self.is_playing_music = False
    
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'auto',
        'nocheckcertificate': True
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
        'executable': FFMPEG_PATH
    }
    
    @app_commands.command(name="play", description="Play music from YouTube")
    async def play(self, interaction: discord.Interaction, search: str):
        """Play music from YouTube URL or search term"""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You need to be in a voice channel!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()
        
        if self.is_playing_music:
            self.song_queue.append(search)
            await interaction.followup.send(f"📋 Added to queue: **{search}**")
        else:
            await self.play_song(interaction, search)
    
    @app_commands.command(name="stop", description="Stop music playback")
    async def stop(self, interaction: discord.Interaction):
        """Stop current playback and clear queue"""
        if not interaction.guild.voice_client:
            await interaction.response.send_message(
                "❌ Bot is not playing anything!",
                ephemeral=True
            )
            return
        
        interaction.guild.voice_client.stop()
        self.song_queue.clear()
        self.is_playing_music = False
        
        await interaction.response.send_message("⏹️ Stopped playback and cleared queue")
    
    @app_commands.command(name="pause", description="Pause music")
    async def pause(self, interaction: discord.Interaction):
        """Pause current playback"""
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            await interaction.response.send_message(
                "❌ Nothing is playing!",
                ephemeral=True
            )
            return
        
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("⏸️ Music paused")
    
    @app_commands.command(name="resume", description="Resume music")
    async def resume(self, interaction: discord.Interaction):
        """Resume paused playback"""
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_paused():
            await interaction.response.send_message(
                "❌ Music is not paused!",
                ephemeral=True
            )
            return
        
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("▶️ Music resumed")
    
    @app_commands.command(name="queue", description="Show music queue")
    async def queue(self, interaction: discord.Interaction):
        """Display current song queue"""
        if not self.song_queue:
            await interaction.response.send_message(
                "🎵 Queue is empty!",
                ephemeral=True
            )
            return
        
        queue_display = "🎵 **Current Queue:**\n"
        for i, song in enumerate(self.song_queue[:10], 1):
            queue_display += f"{i}. {song}\n"
        
        if len(self.song_queue) > 10:
            queue_display += f"\n... and {len(self.song_queue) - 10} more songs"
        
        await interaction.response.send_message(queue_display)
    
    async def play_song(self, interaction: discord.Interaction, search: str):
        """Internal function to play a song"""
        try:
            with yt_dlp.YoutubeDL(self.YDL_OPTIONS) as ydl:
                if search.startswith("http"):
                    info = ydl.extract_info(search, download=False)
                else:
                    info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
                
                if 'entries' in info:
                    info = info['entries'][0]
                
                url = info['url']
                title = info['title']
                
                def after_playing(error):
                    self.is_playing_music = False
                    if error:
                        print(f"Player error: {error}")
                    self.bot.loop.create_task(self.check_queue(interaction))
                
                self.is_playing_music = True
                raw_source = discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS)
                volume_controlled_source = discord.PCMVolumeTransformer(raw_source)
                volume_controlled_source.volume = 0.15
                
                interaction.guild.voice_client.play(
                    volume_controlled_source,
                    after=after_playing
                )
                
                msg_text = f"🎵 Now playing: **{title}**"
                await interaction.followup.send(msg_text)
                
        except Exception as e:
            self.is_playing_music = False
            error_msg = f"❌ Error playing song: {e}"
            await interaction.followup.send(error_msg, ephemeral=True)
    
    async def check_queue(self, interaction: discord.Interaction):
        """Check queue and play next song"""
        if len(self.song_queue) > 0:
            self.is_playing_music = True
            next_search = self.song_queue.pop(0)
            await self.play_song(interaction, next_search)
        else:
            self.is_playing_music = False
            if interaction.guild.voice_client:
                await bagley_speak_wait(
                    interaction.guild,
                    "เพลงในคิวหมดแล้วครับเมท ถ้าอยากฟังต่อก็สั่งเปิดเพลงใหม่ได้เลยนะครับ"
                )


async def setup(bot):
    await bot.add_cog(MusicCommands(bot))
