# 📁 Project Directory Tree

## Complete Project Structure

```
bagley-test/
│
├── 📄 main_bot.py                    ⭐ Main entry point - Clean & simple
├── 📄 bot.py                         📦 Original monolithic bot (reference)
├── 📄 requirements.txt               📦 Python dependencies
├── 📄 .env.example                   🔐 Template for environment variables
├── 📄 .gitignore                     🚫 Git ignore rules
│
├── 📚 Documentation
│   ├── 📄 README.md                  📖 Setup & usage guide
│   ├── 📄 PROJECT_STRUCTURE.md       📖 How to add features
│   ├── 📄 COGS_ORGANIZATION.md       📖 Detailed cog documentation
│   └── 📄 REORGANIZATION_SUMMARY.md  📖 What was reorganized
│
├── ⚙️ config/
│   ├── __init__.py                   Package initialization
│   └── config.py                     🎯 All configuration & constants
│
├── 🛠️ utils/
│   ├── __init__.py                   Clean exports
│   ├── storage.py                    💾 JSON & database operations
│   └── helpers.py                    🔧 Reusable utility functions
│
├── 🎯 cogs/                          Feature-based command modules
│   ├── __init__.py                   Package initialization
│   │
│   ├── admin.py                      👑 Owner commands & management
│   │   ├── shutdown()
│   │   ├── teach()
│   │   └── sync()
│   │
│   ├── voice.py                      🎙️ Voice & text-to-speech
│   │   ├── tts()
│   │   ├── speak()
│   │   ├── disconnect()
│   │   ├── voice_stats()
│   │   └── on_voice_state_update()
│   │
│   ├── music.py                      🎵 Music playback & queue
│   │   ├── play()
│   │   ├── stop()
│   │   ├── pause()
│   │   ├── resume()
│   │   └── queue()
│   │
│   ├── ai.py                         🤖 AI chat & analysis
│   │   ├── ask()
│   │   ├── translate()
│   │   └── summarize()
│   │
│   ├── reminders.py                  ⏰ Reminders & notifications
│   │   ├── remind()
│   │   ├── reminders()
│   │   ├── remind_friend()
│   │   ├── check_reminders() [task]
│   │   └── check_friend_reminders() [task]
│   │
│   ├── users.py                      👤 User profiles & memory
│   │   ├── remember()
│   │   ├── profile()
│   │   ├── profiles()
│   │   └── forget()
│   │
│   ├── youtube.py                    📺 YouTube monitoring
│   │   ├── yt_add()
│   │   ├── yt_remove()
│   │   ├── yt_alert_channel()
│   │   └── check_youtube_updates() [task]
│   │
│   ├── events.py                     📡 Discord event handlers
│   │   ├── on_ready()
│   │   ├── on_member_join()
│   │   ├── on_member_remove()
│   │   └── on_message()
│   │
│   └── info.py                       ℹ️ Bot info & utilities
│       ├── ping()
│       ├── help_command()
│       ├── status()
│       └── about()
│
└── 💾 data/                          Local data storage (generated)
    ├── bagley_memory.db              SQLite database
    ├── server_settings.json          Server config
    ├── user_data.json                User profiles & reminders
    ├── voice_stats.json              Voice statistics
    └── check_friend_reminders.json   Friend reminders
```

## Module Dependencies

```
main_bot.py
  ├─ config/config.py
  │   └─ .env file
  │
  ├─ utils/storage.py
  │   └─ data/ directory
  │
  ├─ utils/helpers.py
  │   └─ edge-tts, discord audio
  │
  └─ cogs/ [auto-loaded]
      ├─ admin.py
      ├─ voice.py → uses utils/helpers.py
      ├─ music.py → uses yt-dlp, FFmpeg
      ├─ ai.py → uses google-genai
      ├─ reminders.py → uses utils/helpers.py
      ├─ users.py → uses utils/storage.py
      ├─ youtube.py → uses requests, SQLite
      ├─ events.py
      └─ info.py
```

## File Sizes

| File | Lines | Size | Purpose |
|------|-------|------|---------|
| main_bot.py | 80 | <5KB | Entry point |
| config/config.py | 70 | 4KB | Configuration |
| utils/storage.py | 150 | 8KB | Data I/O |
| utils/helpers.py | 120 | 7KB | Utilities |
| cogs/admin.py | 90 | 5KB | Admin |
| cogs/voice.py | 180 | 11KB | Voice |
| cogs/music.py | 200 | 12KB | Music |
| cogs/ai.py | 120 | 7KB | AI |
| cogs/reminders.py | 220 | 13KB | Reminders |
| cogs/users.py | 140 | 8KB | Users |
| cogs/youtube.py | 150 | 9KB | YouTube |
| cogs/events.py | 40 | 3KB | Events |
| cogs/info.py | 80 | 5KB | Info |
| **Total Organized Code** | **1,540** | **~100KB** | **Refactored** |
| Original bot.py | 3,537 | ~180KB | Monolithic |

## How It All Works Together

```
User runs: python main_bot.py
         │
         ├─ Load config from config/config.py
         │
         ├─ Connect to Discord
         │
         ├─ Auto-discover and load all cogs from cogs/
         │  ├─ admin.py ✅
         │  ├─ voice.py ✅
         │  ├─ music.py ✅
         │  ├─ ai.py ✅
         │  ├─ reminders.py ✅
         │  ├─ users.py ✅
         │  ├─ youtube.py ✅
         │  ├─ events.py ✅
         │  └─ info.py ✅
         │
         ├─ Sync commands to Discord
         │
         ├─ Initialize database
         │
         └─ Bot is ready!
            User can now use commands ⚡
```

## Quick Reference

### To Run the Bot
```bash
python main_bot.py
```

### To Add a New Feature
1. Create `cogs/my_feature.py`
2. Define your Cog class
3. Bot auto-loads it!

### To Access Configuration
```python
from config.config import OWNER_DISCORD_ID
```

### To Use Utilities
```python
from utils import load_user_data, save_user_data, bagley_speak_wait
```

### To Store Data
```python
# Uses utils/storage.py functions
save_user_data(data)
load_user_data()
```

## Navigation Guide

**For Setup:**
→ Read `README.md`

**For Architecture:**
→ Read `PROJECT_STRUCTURE.md`

**For Cog Details:**
→ Read `COGS_ORGANIZATION.md`

**For What Changed:**
→ Read `REORGANIZATION_SUMMARY.md`

**For Code:**
→ Open `cogs/` folder

**For Config:**
→ Open `config/config.py`

**For Utilities:**
→ Open `utils/` folder

---

**The organization is clean, scalable, and ready for production!** ✨

