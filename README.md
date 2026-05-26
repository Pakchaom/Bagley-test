# Bagley Discord Bot

A feature-rich Discord bot with AI integration, voice capabilities, and advanced moderation features.

## Features

- 🤖 **AI Integration**: Powered by Google Gemini for intelligent responses
- 🎙️ **Voice Features**: Text-to-speech (TTS) with Thai language support
- 🎵 **Music Playback**: YouTube integration for music streaming
- 💾 **Data Persistence**: SQLite database + JSON storage for user/server data
- ⏰ **Reminders**: User reminder system with notifications
- 🔊 **Voice Analytics**: Track voice channel usage and statistics
- 🛡️ **Moderation**: Spam detection and channel management
- 🎭 **User Teaching**: Admins can teach the bot new behaviors

## Project Structure

```
bagley-test/
├── bot.py                  # Main bot entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .gitignore            # Git ignore rules
├── README.md             # This file
│
├── config/               # Configuration files
│   ├── config.py        # Bot configuration and constants
│   └── __init__.py
│
├── cogs/                # Command modules (Discord Cogs)
│   ├── __init__.py
│   ├── admin.py         # Admin commands
│   ├── voice.py         # Voice/TTS commands
│   ├── music.py         # Music playback commands
│   ├── ai.py            # AI integration commands
│   └── reminders.py     # Reminder commands
│
├── utils/               # Utility functions
│   ├── __init__.py
│   ├── storage.py       # JSON/Database operations
│   ├── helpers.py       # Helper functions (TTS, formatting)
│   └── constants.py     # Shared constants
│
└── data/                # Local data storage (generated)
    ├── bagley_memory.db
    ├── server_settings.json
    ├── user_data.json
    ├── voice_stats.json
    └── check_friend_reminders.json
```

## Setup Instructions

### Prerequisites

- Python 3.8+
- FFmpeg (for audio processing)
- Discord Developer Account with Bot created

### Installation

1. **Clone/Download the project**
   ```bash
   cd bagley-test
   ```

2. **Create a Python virtual environment** (recommended)
   ```bash
   # Linux/macOS
   python3 -m venv venv
   source venv/bin/activate
   
   # Windows
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install FFmpeg**
   
   **Linux (Ubuntu/Debian):**
   ```bash
   sudo apt-get install ffmpeg
   ```
   
   **macOS:**
   ```bash
   brew install ffmpeg
   ```
   
   **Windows:**
   - Download from [ffmpeg.org](https://ffmpeg.org/download.html)
   - Extract and add to PATH, or update `FFMPEG_PATH` in `config/config.py`

5. **Setup environment variables**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env with your credentials
   nano .env
   ```

6. **Get your credentials**
   
   - **Discord Token**: [Discord Developer Portal](https://discord.com/developers/applications)
     1. Create a new application
     2. Go to "Bot" section and click "Add Bot"
     3. Copy the token
   
   - **Gemini API Key**: [Google AI Studio](https://aistudio.google.com/app/apikey)
     1. Create a free API key
   
   - **YouTube API Key** (optional): [Google Cloud Console](https://console.cloud.google.com/)

### Configuration

Edit `config/config.py` to customize:

- Bot owner and authorized user IDs
- TTS voice language
- FFmpeg path for your OS
- Database file locations
- Spam detection thresholds

## Usage

### Running the Bot

```bash
python bot.py
```

The bot will:
1. Load configuration from `.env` file
2. Connect to Discord
3. Initialize database and data files
4. Load all cogs from the `cogs/` directory
5. Start listening for commands

### Bot Commands

**Admin Commands** (Restricted Access):
- `/shutdown` - Shutdown the bot
- `/teach` - Teach the bot new responses

**Voice Commands**:
- `/tts [text]` - Text-to-speech announcement
- `/speak [text]` - Speak in voice channel

**Music Commands**:
- `/play [url]` - Play YouTube video
- `/stop` - Stop current playback
- `/queue` - Show current queue

**AI Commands**:
- `/ask [question]` - Ask Gemini AI

**Reminders**:
- `/remind [time] [message]` - Set a reminder
- `/reminders` - View your reminders

## Environment Variables

### Required
- `DISCORD_TOKEN` - Your bot's Discord token
- `GEMINI_API_KEY` - Google Gemini API key

### Optional
- `YT_API_KEY` - YouTube API key for music features

## Database

The bot uses:
- **SQLite** (`bagley_memory.db`) - Bot memory and long-term data
- **JSON Files** - User data, settings, reminders, and voice statistics

All data files are stored in the `data/` directory.

## Data Files

- `server_settings.json` - Per-server settings
- `user_data.json` - User profiles and reminder data
- `voice_stats.json` - Voice channel usage statistics
- `check_friend_reminders.json` - Friend check reminders

## Architecture

### Config Module (`config/`)
Centralized configuration management. All settings and constants are defined here.

### Utils Module (`utils/`)
Utility functions for common operations:
- `storage.py` - File I/O and database operations
- `helpers.py` - Text processing, TTS, voice utilities

### Cogs Module (`cogs/`)
Discord.py Cogs for organizing commands by feature:
- Each cog handles related commands
- Cogs are automatically loaded by the main bot
- Easy to enable/disable features

### Data Module (`data/`)
Local storage for bot state and user information.

## Troubleshooting

### Bot doesn't start
- Check `.env` file contains valid tokens
- Verify Python version is 3.8+
- Check all dependencies are installed: `pip install -r requirements.txt`

### Voice/TTS not working
- Verify FFmpeg is installed and in PATH
- Check `FFMPEG_PATH` in `config/config.py` is correct for your OS
- Test with: `ffmpeg -version`

### Commands not responding
- Check bot has correct permissions in Discord server
- Verify bot is in the voice channel for voice commands
- Check console for error messages

### Permission errors
- Ensure bot has required Discord permissions
- Check user is in `ALLOWED_*_USERS` list in config for restricted commands

## Contributing

To add new features:

1. **Create a new cog** in `cogs/` directory
2. **Define commands** using Discord.py's `@commands.command()` or `@app_commands.command()`
3. **Use utilities** from `utils/` module for common operations
4. **Update documentation** and project structure if needed

## License

[Your License Here]

## Support

For issues or questions, please create an issue in the project repository or contact the bot owner.

---

**Last Updated**: May 26, 2026  
**Version**: 1.0.0
