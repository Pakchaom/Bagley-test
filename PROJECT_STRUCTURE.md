# Project Structure Guide

## Directory Organization

### `/config/`
Centralized configuration management for the entire project.
- `config.py` - Main configuration file with all constants and settings
- `__init__.py` - Package initialization

### `/utils/`
Reusable utility functions and helpers.
- `storage.py` - JSON file I/O and database operations
- `helpers.py` - Text processing, TTS, voice utilities
- `__init__.py` - Package initialization with exports

### `/cogs/`
Discord.py Cogs for organizing commands by feature.
Each cog is a module that handles related commands.
- `admin.py` - Admin/owner commands (shutdown, teach, etc.)
- `voice.py` - Voice channel and TTS commands
- `music.py` - Music playback and queue management
- `ai.py` - AI integration commands
- `reminders.py` - Reminder and notification commands
- `__init__.py` - Package initialization

### `/data/`
Local data storage directory (created at runtime).
- `bagley_memory.db` - SQLite database for persistent data
- `server_settings.json` - Per-server configuration
- `user_data.json` - User profiles and reminder data
- `voice_stats.json` - Voice channel usage statistics
- `check_friend_reminders.json` - Friend check reminders

### Root Files
- `main_bot.py` - Main bot entry point (refactored to use new structure)
- `bot.py` - Original monolithic bot file (can be refactored further)
- `requirements.txt` - Python package dependencies
- `.env.example` - Template for environment variables
- `.env` - Actual environment variables (in .gitignore)
- `.gitignore` - Git ignore rules
- `README.md` - Project documentation

## How to Add New Features

### 1. Adding a New Command

Create a new file in `/cogs/` or add to existing cog:

```python
# cogs/my_feature.py
from discord.ext import commands
from discord import app_commands
import discord

class MyFeature(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="mycommand", description="My command description")
    async def my_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("Command works!")

async def setup(bot):
    await bot.add_cog(MyFeature(bot))
```

### 2. Adding a New Utility Function

Add to `/utils/helpers.py` or create new module:

```python
# In utils/helpers.py
def my_utility_function(data):
    """My utility function"""
    return processed_data
```

Then export in `/utils/__init__.py`:

```python
from .helpers import my_utility_function
```

### 3. Adding Configuration

Add to `/config/config.py`:

```python
MY_NEW_SETTING = os.getenv('MY_NEW_SETTING', 'default_value')
```

## File Relationships

```
main_bot.py
    ├─ imports from config/
    ├─ imports from utils/
    ├─ loads cogs/
    └─ contains main bot loop

config/config.py
    └─ defines all constants and env vars

utils/
    ├─ storage.py - handles data persistence
    └─ helpers.py - provides utility functions

cogs/
    ├─ admin.py - admin commands
    ├─ voice.py - voice commands
    ├─ music.py - music commands
    ├─ ai.py - AI commands
    └─ reminders.py - reminder commands
```

## Naming Conventions

- **Files**: `lowercase_with_underscores.py`
- **Classes**: `PascalCase` (e.g., `MyCommandClass`)
- **Functions**: `lowercase_with_underscores()`
- **Constants**: `UPPERCASE_WITH_UNDERSCORES`
- **Private**: `_leading_underscore` for internal use

## Data Flow

1. **Configuration** → `config.py` defines all settings
2. **Storage** → `utils/storage.py` handles data I/O
3. **Processing** → `utils/helpers.py` processes data
4. **Commands** → `cogs/` handle user interactions
5. **Output** → Bot sends responses to Discord

## Best Practices

1. Keep functions small and focused
2. Use type hints for clarity
3. Add docstrings to functions
4. Store configuration in `config.py`
5. Use `utils/` for reusable functions
6. Organize commands in logical cogs
7. Handle errors gracefully
8. Log important events

