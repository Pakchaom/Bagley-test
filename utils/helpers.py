"""
Helper functions for text processing and utilities
"""
import re as regex_lib
import time
import asyncio
import discord
import edge_tts
import os
from config.config import TTS_VOICE, FFMPEG_PATH


def clean_emoji(text):
    """Remove Discord emojis and special characters"""
    text = regex_lib.sub(r'<a?:\w+:\d+>', '', text)
    text = regex_lib.sub(r'[^\w\s\u0e00-\u0e7f]+', '', text)
    return text.strip()


def generate_unique_filename(extension='.mp3'):
    """Generate a unique filename based on timestamp"""
    return f"speak_{int(time.time() * 1000)}{extension}"


async def bagley_speak_wait(guild, text, filename=None):
    """
    Play TTS audio in voice channel and wait for completion
    
    Args:
        guild: Discord guild
        text: Text to convert to speech
        filename: Optional custom filename
    """
    if not guild:
        return
    
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return
    
    # Wait for current audio to finish
    while vc.is_playing():
        await asyncio.sleep(0.1)
    
    try:
        unique_name = filename or generate_unique_filename()
        
        # Generate speech using edge_tts with Thai voice
        communicate = edge_tts.Communicate(text, TTS_VOICE)
        await communicate.save(unique_name)
        
        # Wait for file to be saved
        await asyncio.sleep(0.5)
        
        # Play audio
        source = discord.FFmpegPCMAudio(unique_name, executable=FFMPEG_PATH)
        vc.play(source)
        
        # Wait for audio to finish
        while vc.is_playing():
            await asyncio.sleep(0.1)
        
        # Clean up
        try:
            os.remove(unique_name)
        except:
            pass
            
    except Exception as e:
        print(f"Error in TTS: {e}")


async def bagley_hijack_alert(voice_channel, message_text):
    """
    Alert function - moves bot to a voice channel and sends message
    
    Args:
        voice_channel: Target Discord voice channel
        message_text: Message text to announce
    """
    vc = None
    guild = voice_channel.guild
    old_channel = None
    
    try:
        # Remember the bot's current channel
        if guild.voice_client and guild.voice_client.channel:
            old_channel = guild.voice_client.channel
        
        # Safely connect to target channel
        if guild.voice_client:
            await guild.voice_client.move_to(voice_channel)
            vc = guild.voice_client
        else:
            vc = await voice_channel.connect()
        
        # Announce message
        await bagley_speak_wait(guild, message_text)
        
        # Return to original channel
        if old_channel and old_channel != voice_channel:
            await vc.move_to(old_channel)
            
    except Exception as e:
        print(f"Error in hijack alert: {e}")
