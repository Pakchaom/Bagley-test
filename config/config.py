"""
Configuration file for Bagley Discord Bot
Load environment variables and define bot settings
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# API Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
YT_API_KEY = os.getenv('YT_API_KEY')

# Bot Owner and Authorized Users
OWNER_DISCORD_ID = 1133740216822267954

# Users allowed to shutdown the bot
ALLOWED_SHUTDOWN_USERS = [
    1133740216822267954,  # Chakrom
    856568101919653918    # Chacha
]

# Users allowed to teach/train the bot
ALLOWED_TEACH_USERS = [
    1133740216822267954,  # Chakrom
    856568101919653918,    # Chacha
    732953446172327956,    # Ball
    1073827310026903612    # Lung Korn
]

# Bot Settings
SPAM_THRESHOLD = 3
COMMAND_PREFIX = '!'

# File Paths
DATABASE_PATH = 'data/bagley_memory.db'
SERVER_SETTINGS_FILE = 'data/server_settings.json'
USER_DATA_FILE = 'data/user_data.json'
VOICE_STATS_FILE = 'data/voice_stats.json'
REMINDERS_FILE = 'data/check_friend_reminders.json'

# Voice Settings
TTS_VOICE = "th-TH-NiwatNeural"  # Thai voice

# FFmpeg Path - Works with Docker and local development
# In Docker: FFmpeg is installed as system package, available in PATH
# Locally: Can override with FFMPEG_PATH environment variable
# Default: Use 'ffmpeg' which works on Linux (Docker) and systems with FFmpeg in PATH
FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')

# Audio Settings
VOICE_CHANNEL_TIMEOUT = 300  # seconds
