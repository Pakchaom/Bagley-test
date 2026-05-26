# Bagley Bot - Function Organization Guide

This document shows how the original bot.py has been separated into organized cogs by category.

## Cogs Overview

### 1. **admin.py** - Admin/Owner Commands
**Purpose:** Owner-only administrative commands and bot management

**Functions/Commands:**
- `shutdown()` - Shutdown the bot
- `teach()` - Teach bot new keyword-response pairs
- `sync()` - Sync commands with Discord

**Related from original bot.py:**
- `ALLOWED_SHUTDOWN_USERS` - Users who can shutdown
- `ALLOWED_TEACH_USERS` - Users who can teach
- SQLite teach_memory operations

**Usage:**
```
/shutdown - Stop the bot
/teach keyword response - Teach new response
/sync - Sync all commands
```

---

### 2. **voice.py** - Voice & Text-to-Speech
**Purpose:** Voice channel operations and text-to-speech functionality

**Functions/Commands:**
- `tts()` - Text-to-speech command
- `speak()` - Alias for TTS
- `disconnect()` - Leave voice channel
- `voice_stats()` - Display voice statistics
- `on_voice_state_update()` - Track voice joins/leaves
- `track_voice_stats()` - Background task for stats

**Related from original bot.py:**
- `bagley_speak_wait()` - TTS playback function
- `bagley_hijack_alert()` - Alert hijacking function
- `bagley_speak()` - General speak function
- Voice cooldown system
- Voice report status tracking

**Usage:**
```
/tts "Hello" - Convert text to speech
/speak "Message" - Speak in voice channel
/disconnect - Bot leaves voice
/voice_stats - Show voice statistics
```

---

### 3. **music.py** - Music Playback
**Purpose:** YouTube music streaming and queue management

**Functions/Commands:**
- `play()` - Play music from YouTube
- `stop()` - Stop playback
- `pause()` - Pause music
- `resume()` - Resume music
- `queue()` - Display music queue
- `play_song()` - Internal song player
- `check_queue()` - Process queue

**Related from original bot.py:**
- `song_queue` list
- `is_playing_music` flag
- YDL_OPTIONS - YouTube-DL settings
- FFMPEG_OPTIONS - Audio processing
- `play_song()` original function
- `check_queue()` original function

**Usage:**
```
/play "song name" - Play song
/stop - Stop playback
/pause - Pause music
/resume - Resume music
/queue - Show upcoming songs
```

---

### 4. **ai.py** - AI & Chat
**Purpose:** Google Gemini AI integration for chat and analysis

**Functions/Commands:**
- `ask()` - Ask AI a question
- `translate()` - Translate text
- `summarize()` - Summarize text

**Related from original bot.py:**
- `client` - Gemini API client
- `ask_bagley_ai()` - Original AI function
- `SYSTEM_PROMPT` - Bot personality
- `MODEL_NAME` - Gemini model
- Free chat/DM handling

**Usage:**
```
/ask "question" - Ask Gemini AI
/translate "text" language - Translate text
/summarize "text" - Get summary
```

---

### 5. **reminders.py** - Reminders & Notifications
**Purpose:** User reminders and friend notifications

**Functions/Commands:**
- `remind()` - Set personal reminder
- `reminders()` - View all reminders
- `remind_friend()` - Set reminder for friend
- `clear_reminders()` - Clear all reminders
- `check_reminders()` - Background task (1 min)
- `check_friend_reminders()` - Friend reminder task

**Related from original bot.py:**
- `get_reminders_for_user()` - Fetch user reminders
- `add_reminder()` - Add reminder
- `check_reminders` task
- `check_friend_reminders` task
- Reminder storage in user_data.json
- `bagley_hijack_alert()` - Alert delivery

**Usage:**
```
/remind 21:00 "message" - Set reminder
/reminders - View reminders
/remind_friend @user 15:00 "message" - Remind friend
/clear_reminders - Delete all reminders
```

---

### 6. **users.py** - User Profiles
**Purpose:** Store and retrieve user information

**Functions/Commands:**
- `remember()` - Store user information
- `profile()` - View user profile
- `profiles()` - List all profiles in server
- `forget()` - Delete user profile

**Related from original bot.py:**
- `load_user_data()` - Load user JSON
- `save_user_data()` - Save user JSON
- User memory system
- Birthday tracking
- Nickname storage
- "รายชื่อคนในดิส" command

**Usage:**
```
/remember @user nickname "Cool Guy" - Remember nickname
/remember @user birthday "1990-01-01" - Remember birthday
/profile @user - Show profile
/profiles - List all profiles
/forget @user - Delete profile
```

---

### 7. **youtube.py** - YouTube Monitoring
**Purpose:** Monitor YouTube channels for new uploads

**Functions/Commands:**
- `yt_add()` - Add channel to monitor
- `yt_remove()` - Remove channel
- `yt_alert_channel()` - Set alert destination
- `check_youtube_updates()` - Background task (3 min)
- `send_yt_alert()` - Send alert message

**Related from original bot.py:**
- `check_youtube_updates` task
- `send_yt_alert()` function
- YouTube database tables
- YouTube API integration
- Channel tracking

**Usage:**
```
/yt_add channel_id "Channel Name" - Add YouTube channel
/yt_remove channel_id - Remove channel
/yt_alert_channel #channel - Set where alerts go
```

---

### 8. **events.py** - Discord Events
**Purpose:** Handle Discord events and lifecycle

**Event Handlers:**
- `on_ready()` - Bot startup
- `on_member_join()` - New member joins
- `on_member_remove()` - Member leaves
- `on_message()` - Message handler

**Related from original bot.py:**
- Original `on_ready()` event
- Member join/leave logging
- `on_message()` spam check
- Command processing

**Usage:**
- Automatic - no manual commands
- Logged to console

---

### 9. **info.py** - Information & Utilities
**Purpose:** General bot information and utility commands

**Functions/Commands:**
- `ping()` - Check bot latency
- `help_command()` - Show help
- `status()` - Bot status
- `about()` - About the bot

**Related from original bot.py:**
- Simple utility commands
- Help text display

**Usage:**
```
/ping - Check latency
/help - Show commands
/status - Bot status
/about - About Bagley
```

---

## File Organization

```
cogs/
├── __init__.py           # Package init
├── admin.py              # Admin commands
├── voice.py              # Voice/TTS
├── music.py              # Music playback
├── ai.py                 # AI chat
├── reminders.py          # Reminders
├── users.py              # User profiles
├── youtube.py            # YouTube monitoring
├── events.py             # Discord events
└── info.py               # Bot info/help

utils/
├── __init__.py
├── storage.py            # JSON/Database I/O
├── helpers.py            # Voice/TTS helpers
└── constants.py          # (for future use)

config/
├── __init__.py
└── config.py             # All configuration

data/                      # (generated at runtime)
├── bagley_memory.db
├── server_settings.json
├── user_data.json
├── voice_stats.json
└── check_friend_reminders.json
```

## Original bot.py Functions → New Locations

| Original Function | New Location | Cog |
|---|---|---|
| `on_ready()` | Event handler | events.py |
| `on_message()` | Message handler | events.py |
| `bagley_speak_wait()` | utils/helpers.py | voice.py uses it |
| `bagley_hijack_alert()` | utils/helpers.py | voice.py, reminders.py use it |
| `bagley_speak()` | utils/helpers.py | voice.py uses it |
| `ask_bagley_ai()` | AICommands.ask() | ai.py |
| `save_settings()` | utils/storage.py | (config storage) |
| `load_settings()` | utils/storage.py | (config storage) |
| `save_user_data()` | utils/storage.py | users.py uses it |
| `load_user_data()` | utils/storage.py | users.py uses it |
| `save_voice_data()` | utils/storage.py | voice.py uses it |
| `load_voice_data()` | utils/storage.py | voice.py uses it |
| `get_reminders_for_user()` | utils/storage.py | reminders.py uses it |
| `add_reminder()` | utils/storage.py | reminders.py uses it |
| `load_reminders()` | utils/storage.py | reminders.py uses it |
| `save_reminders()` | utils/storage.py | reminders.py uses it |
| `clean_emoji()` | utils/helpers.py | (utility) |
| `play_song()` | MusicCommands.play_song() | music.py |
| `check_queue()` | MusicCommands.check_queue() | music.py |
| `check_youtube_updates()` | YouTubeMonitoring.check_youtube_updates() | youtube.py |
| `send_yt_alert()` | YouTubeMonitoring.send_yt_alert() | youtube.py |
| `check_reminders()` | ReminderCommands.check_reminders() | reminders.py |
| `check_friend_reminders()` | ReminderCommands.check_friend_reminders() | reminders.py |

## Global Variables → New Locations

| Original Variable | New Location |
|---|---|
| `is_moving_group` | voice.py (class variable) |
| `voice_action_cooldowns` | voice.py (class variable) |
| `song_queue` | music.py (class variable) |
| `user_join_times` | voice.py (class variable) |
| `voice_report_status` | voice.py (class variable) |
| `created_party_channels` | voice.py (class variable) |
| `is_playing_music` | music.py (class variable) |
| `is_tts_enabled` | voice.py (class variable) |
| `spam_check` | events.py (could be added) |
| `OWNER_DISCORD_ID` | config/config.py |
| `ALLOWED_SHUTDOWN_USERS` | config/config.py |
| `ALLOWED_TEACH_USERS` | config/config.py |
| `SPAM_THRESHOLD` | config/config.py |
| `conn` | utils/storage.py (connection function) |

## How to Add New Features

1. **Create a new cog file** in `cogs/`:
   ```python
   class MyFeature(commands.Cog):
       def __init__(self, bot):
           self.bot = bot
       
       @app_commands.command(name="mycommand")
       async def my_command(self, interaction: discord.Interaction):
           pass
   
   async def setup(bot):
       await bot.add_cog(MyFeature(bot))
   ```

2. **Use utilities** from `utils/`:
   ```python
   from utils import load_user_data, save_user_data, bagley_speak_wait
   ```

3. **Import config** values:
   ```python
   from config.config import OWNER_DISCORD_ID, FFMPEG_PATH
   ```

## Migration Checklist

- ✅ Admin commands → admin.py
- ✅ Voice/TTS → voice.py
- ✅ Music → music.py
- ✅ AI chat → ai.py
- ✅ Reminders → reminders.py
- ✅ User profiles → users.py
- ✅ YouTube monitoring → youtube.py
- ✅ Discord events → events.py
- ✅ Info/Help → info.py
- ✅ Utilities → utils/
- ✅ Configuration → config/
- ✅ Database → utils/storage.py

## Next Steps

1. **Test each cog** individually
2. **Update main_bot.py** to auto-load all cogs
3. **Move remaining functions** from bot.py to appropriate cogs
4. **Archive original bot.py** for reference

