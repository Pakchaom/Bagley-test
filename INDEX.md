# 📚 Documentation Index

Welcome to the Bagley Bot documentation! This index helps you find what you need.

## 🚀 Getting Started

**New to the bot?** Start here:
- **[QUICK_START.md](QUICK_START.md)** - 30-second setup & basic commands

## 📖 Main Documentation

### Setup & Installation
- **[README.md](README.md)** - Full setup guide, features, installation
  - Prerequisites
  - Installation steps
  - API key setup
  - Configuration
  - Troubleshooting

### Using the Bot
- **[QUICK_START.md](QUICK_START.md)** - Quick reference guide
  - Command list
  - Common tasks
  - Performance tips

## 🏗️ Architecture & Organization

### Understanding the Structure
- **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** - How the project is organized
  - Directory layout
  - How to add features
  - Naming conventions
  - Best practices

### Detailed Cog Documentation
- **[COGS_ORGANIZATION.md](COGS_ORGANIZATION.md)** - Detailed breakdown of each cog
  - What each cog does
  - Functions in each cog
  - Command reference
  - Original → New function mapping
  - Global variables organization

### Complete Directory Tree
- **[DIRECTORY_TREE.md](DIRECTORY_TREE.md)** - Visual file structure
  - Complete project layout
  - Module dependencies
  - File sizes
  - Navigation guide

### Reorganization Details
- **[REORGANIZATION_SUMMARY.md](REORGANIZATION_SUMMARY.md)** - What was changed
  - Before vs After
  - Benefits of reorganization
  - Migration checklist
  - Next steps

## 📋 Quick Reference

### Commands by Category

#### 🎙️ Voice & TTS
```bash
/tts "text"              # Convert to speech
/speak "message"         # Speak in channel
/disconnect              # Leave voice
/voice_stats             # Show statistics
```

#### 🎵 Music
```bash
/play "song"             # Play music
/stop                    # Stop playback
/pause                   # Pause
/resume                  # Resume
/queue                   # Show queue
```

#### 🤖 AI & Chat
```bash
/ask "question"          # Ask AI
/translate "text" lang   # Translate
/summarize "text"        # Summarize
```

#### ⏰ Reminders
```bash
/remind 21:00 "msg"      # Set reminder
/reminders               # View reminders
/remind_friend @user ... # Remind friend
```

#### 👤 User Profiles
```bash
/remember @user nickname "name"    # Save nickname
/remember @user birthday "date"    # Save birthday
/profile @user           # View profile
/profiles                # List all profiles
```

#### 📺 YouTube
```bash
/yt_add channel_id "name"          # Monitor channel
/yt_remove channel_id              # Stop monitoring
/yt_alert_channel #channel         # Set alert channel
```

#### 👑 Admin
```bash
/teach keyword response  # Teach bot
/shutdown                # Stop bot
/sync                    # Sync commands
```

#### ℹ️ Info
```bash
/ping                    # Check latency
/help                    # Show help
/status                  # Bot status
/about                   # About bot
```

## 📁 File Organization

### Configuration
```
config/
├── config.py           - All settings & constants
└── __init__.py
```

### Utilities
```
utils/
├── storage.py          - JSON & database I/O
├── helpers.py          - Reusable functions
└── __init__.py
```

### Commands (Cogs)
```
cogs/
├── admin.py            - Owner commands
├── voice.py            - Voice & TTS
├── music.py            - Music streaming
├── ai.py               - AI commands
├── reminders.py        - Reminders
├── users.py            - User profiles
├── youtube.py          - YouTube monitoring
├── events.py           - Discord events
├── info.py             - Bot info
└── __init__.py
```

### Entry Points
```
main_bot.py            - Bot startup (run this!)
bot.py                 - Original monolithic (reference)
```

### Data
```
data/
├── bagley_memory.db
├── server_settings.json
├── user_data.json
├── voice_stats.json
└── check_friend_reminders.json
```

## 🔍 Finding Things

### If you want to...

**Add a new command**
→ See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) "How to Add New Features"

**Understand the cog structure**
→ Read [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md)

**Find where a function went**
→ Check table in [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md) "Original bot.py Functions"

**Setup the bot**
→ Follow [README.md](README.md) "Setup Instructions"

**Get help quickly**
→ Check [QUICK_START.md](QUICK_START.md) "Troubleshooting"

**See the full directory**
→ Open [DIRECTORY_TREE.md](DIRECTORY_TREE.md)

**Understand what changed**
→ Read [REORGANIZATION_SUMMARY.md](REORGANIZATION_SUMMARY.md)

## 🛠️ Developer Guide

### Setting Up Development

1. **Clone/Download** the project
2. **Read** [QUICK_START.md](QUICK_START.md)
3. **Follow** [README.md](README.md) setup section
4. **Understand** [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)

### Adding Features

1. **Create** `cogs/my_feature.py`
2. **Reference** [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
3. **Follow** the existing cog patterns
4. **Test** your new command
5. **Commit** with clear message

### Understanding Code

1. **Read** [DIRECTORY_TREE.md](DIRECTORY_TREE.md) for layout
2. **Check** [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md) for details
3. **Review** individual cog files
4. **Reference** [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for patterns

## 💡 Common Questions

**Q: How do I run the bot?**
A: `python main_bot.py` (see [QUICK_START.md](QUICK_START.md))

**Q: Where do I put API keys?**
A: In `.env` file (see [README.md](README.md))

**Q: How do I add a new command?**
A: Create a cog in `cogs/` (see [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md))

**Q: What's in each cog?**
A: Check [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md)

**Q: Where did function X go?**
A: Find it in table in [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md)

**Q: How is the project organized?**
A: See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) and [DIRECTORY_TREE.md](DIRECTORY_TREE.md)

**Q: What changed from original bot.py?**
A: Read [REORGANIZATION_SUMMARY.md](REORGANIZATION_SUMMARY.md)

## 📊 Documentation Stats

| Document | Lines | Topics | Purpose |
|----------|-------|--------|---------|
| README.md | 300+ | Setup, Features, Usage | Complete guide |
| QUICK_START.md | 200+ | Quick reference | Fast onboarding |
| PROJECT_STRUCTURE.md | 150+ | Architecture, Patterns | Developer guide |
| COGS_ORGANIZATION.md | 250+ | Cog breakdown | Detailed reference |
| DIRECTORY_TREE.md | 180+ | File layout | Visual navigation |
| REORGANIZATION_SUMMARY.md | 120+ | What changed | Migration info |

## 📞 Need Help?

**For setup issues:**
→ Check [README.md](README.md) "Troubleshooting"

**For usage questions:**
→ Check [QUICK_START.md](QUICK_START.md) "Common Tasks"

**For architecture questions:**
→ Check [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)

**For finding code:**
→ Check [COGS_ORGANIZATION.md](COGS_ORGANIZATION.md)

## 🎯 Navigation Shortcuts

| Need | Go To | Section |
|------|-------|---------|
| Quick setup | QUICK_START.md | 30-second setup |
| Full install | README.md | Setup instructions |
| Add command | PROJECT_STRUCTURE.md | How to add features |
| Cog details | COGS_ORGANIZATION.md | Each cog breakdown |
| File layout | DIRECTORY_TREE.md | Complete structure |
| See changes | REORGANIZATION_SUMMARY.md | Before vs after |

---

## Document Map

```
Documentation Hub
│
├── 🚀 QUICK_START.md (quick reference)
│
├── 📖 README.md (full setup guide)
│
├── 🏗️ Architecture
│   ├── PROJECT_STRUCTURE.md (how to build)
│   ├── COGS_ORGANIZATION.md (cog details)
│   ├── DIRECTORY_TREE.md (file layout)
│   └── REORGANIZATION_SUMMARY.md (what changed)
│
└── 📁 Code Files
    ├── config/ (settings)
    ├── utils/ (helpers)
    ├── cogs/ (commands)
    └── main_bot.py (entry point)
```

---

**Welcome! Pick a document above to get started!** 🚀

