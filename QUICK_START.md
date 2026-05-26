# 🚀 Quick Start Guide

## 30-Second Setup

### 1️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

### 2️⃣ Configure Environment
```bash
cp .env.example .env
# Edit .env and add your API keys
nano .env
```

### 3️⃣ Run the Bot
```bash
python main_bot.py
```

That's it! 🎉

---

## What You Need (API Keys)

### Discord Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create an application
3. Add a Bot user
4. Copy the token → paste in `.env`

### Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create API key
3. Copy → paste in `.env`

### YouTube API Key (Optional)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project → enable YouTube API
3. Create credentials → API key
4. Copy → paste in `.env`

---

## Project Structure at a Glance

```
Your bot is organized into:

📂 config/      → All settings
📂 utils/       → Shared functions
📂 cogs/        → Commands by category
📂 data/        → Database & JSON files

📄 main_bot.py  → Start here (runs the bot)
📄 README.md    → Full documentation
```

---

## Available Commands

### 🎙️ Voice
```
/tts "Hello" - Convert text to speech
/speak "Message" - Speak in voice channel
/disconnect - Bot leaves voice
/voice_stats - Show statistics
```

### 🎵 Music
```
/play "song name" - Play music
/stop - Stop playback
/pause - Pause
/resume - Resume
/queue - Show queue
```

### 🤖 AI
```
/ask "question" - Ask the AI
/translate "text" language - Translate
/summarize "text" - Get summary
```

### ⏰ Reminders
```
/remind 21:00 "message" - Set reminder
/reminders - View reminders
/remind_friend @user 15:00 "msg" - Remind friend
```

### 👤 Profiles
```
/remember @user nickname "Cool Guy" - Save nickname
/remember @user birthday "1990-01-01" - Save birthday
/profile @user - View profile
/profiles - List all profiles
```

### 👑 Admin
```
/teach keyword response - Teach bot responses
/shutdown - Stop bot
/sync - Sync commands
```

### ℹ️ Info
```
/ping - Check latency
/help - Show commands
/status - Bot status
/about - About bot
```

---

## Troubleshooting

### Bot won't start
❌ Check `.env` has valid tokens  
❌ Verify Python 3.8+  
❌ Run: `pip install -r requirements.txt`

### Commands not working
❌ Use `/` slash commands (not prefix)  
❌ Bot needs Discord permissions  
❌ Check `/help` for command names

### Voice not working
❌ Install FFmpeg first  
❌ Check bot is in voice channel  
❌ Verify `FFMPEG_PATH` in config.py

### AI not responding
❌ Check GEMINI_API_KEY in `.env`  
❌ Verify API key is valid  
❌ Check internet connection

---

## Adding New Features

### Quick Example: Add `/hello` command

1. Create `cogs/hello.py`:
```python
import discord
from discord.ext import commands
from discord import app_commands

class HelloCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="hello", description="Say hello")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message("👋 Hello!")

async def setup(bot):
    await bot.add_cog(HelloCog(bot))
```

2. Restart bot
3. Done! `/hello` command now works

---

## File Guide

| File | Purpose | When to Edit |
|------|---------|--------------|
| `.env` | API keys | Always (but don't commit!) |
| `config/config.py` | Settings | Customize behavior |
| `utils/helpers.py` | Reusable code | Add utility functions |
| `utils/storage.py` | Data saving | Modify storage |
| `cogs/` | Commands | Add new features |
| `main_bot.py` | Startup | Usually don't edit |

---

## Common Tasks

### Change bot prefix
Edit `config/config.py`:
```python
COMMAND_PREFIX = '!'  # Change this
```

### Change TTS voice
Edit `config/config.py`:
```python
TTS_VOICE = "th-TH-NiwatNeural"  # Thai voice
# or choose other voice
```

### Add owner-only command
```python
from config.config import OWNER_DISCORD_ID

@app_commands.command()
async def secret(self, interaction):
    if interaction.user.id != OWNER_DISCORD_ID:
        await interaction.response.send_message("❌ Owner only!")
        return
    # Your code here
```

### Save user data
```python
from utils import save_user_data, load_user_data

data = load_user_data()
data["user_id"] = "some info"
save_user_data(data)
```

---

## Performance Tips

- 💾 Data auto-saves to JSON
- 🔄 Tasks run automatically
- ⏰ Reminders check every minute
- 📺 YouTube checks every 3 minutes
- 🎵 Music streams from YouTube

---

## Getting Help

📖 Full docs → `README.md`  
🏗️ Architecture → `PROJECT_STRUCTURE.md`  
📦 Cogs detail → `COGS_ORGANIZATION.md`  
📁 File tree → `DIRECTORY_TREE.md`  
✨ What changed → `REORGANIZATION_SUMMARY.md`

---

## Next Steps

✅ **Setup complete!**

1. Try running `/ping` to test
2. Try `/help` to see all commands
3. Read `README.md` for details
4. Check `COGS_ORGANIZATION.md` to understand structure
5. Add your own cogs!

---

**Happy coding!** 🚀

Questions? Check the documentation files!

