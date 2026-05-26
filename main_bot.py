"""
Bagley Discord Bot - Main Entry Point

A feature-rich Discord bot with AI integration, voice capabilities, and advanced features.
"""

# --- Imports ---
import discord
from discord.ext import commands
import asyncio
import os
import sys

# --- Local Imports ---
from config.config import (
    DISCORD_TOKEN,
    OWNER_DISCORD_ID,
    COMMAND_PREFIX
)
from utils import get_database_connection

# --- Initialize Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    help_command=None
)

# --- Database Connection ---
conn = get_database_connection()


@bot.event
async def on_ready():
    """Called when the bot connects to Discord"""
    print(f"✅ Bot logged in as {bot.user}")
    print(f"🤖 Bot ID: {bot.user.id}")
    print(f"📊 Serving {len(bot.guilds)} guild(s)")
    print(f"📦 Loaded {len(bot.cogs)} cog(s): {', '.join(bot.cogs.keys())}")
    
    # Sync commands with Discord
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")


@bot.event
async def on_message(message):
    """Handle incoming messages"""
    if message.author == bot.user:
        return
    
    await bot.process_commands(message)
    

def init_db():
    """Initialize database tables"""
    global conn
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS chat_history (user_id INTEGER, role TEXT, text TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_channels (channel_id TEXT PRIMARY KEY, channel_name TEXT, last_video_id TEXT, guild_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_settings (guild_id TEXT PRIMARY KEY, target_channel_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS registration_settings(guild_id INTEGER PRIMARY KEY, questions TEXT, target_role_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_status(user_id TEXT PRIMARY KEY, status_message TEXT, is_away INTEGER, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS teach_memory (keyword TEXT PRIMARY KEY, response TEXT)''')
    conn.commit()


# Initialize database
init_db()


async def load_cogs():
    """Load all cogs from the cogs directory"""
    cogs_dir = "cogs"
    cog_count = 0
    
    if not os.path.exists(cogs_dir):
        print(f"⚠️  No cogs directory found at {cogs_dir}")
        return
    
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            cog_name = filename[:-3]
            try:
                await bot.load_extension(f"cogs.{cog_name}")
                print(f"✅ Loaded cog: {cog_name}")
                cog_count += 1
            except Exception as e:
                print(f"❌ Failed to load cog {cog_name}: {e}")
    
    print(f"📦 Loaded {cog_count} cog(s)")

async def main():
    """Main entry point"""
    if not DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN not found in .env file")
        print("📝 Please copy .env.example to .env and fill in your credentials")
        sys.exit(1)
    
    print("🚀 Starting Bagley Bot...")
    print(f"⚙️  Owner ID: {OWNER_DISCORD_ID}")
    
    # Load cogs
    await load_cogs()
    
    # Run bot
    try:
        await bot.start
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        sys.exit(1)


if _try: #TODO: indent wrong need to recheck further
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot shutdown by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1__ == "__main__":
    main()
