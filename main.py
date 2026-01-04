import discord
import os
import asyncio
import logging
import platform
from discord.ext import commands

# Import the database from utils.py
# This ensures the DB is loaded before the bot starts
try:
    from utils import db_manager
except ImportError:
    print("❌ CRITICAL ERROR: Could not import 'db_manager' from utils.py.")
    print("   Make sure utils.py exists in the same folder!")
    exit()

# ==========================================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================================

# Setup Logging (So you can see errors in the console)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# Load Token (Supports .env files if you use python-dotenv)
TOKEN = os.getenv("DISCORD_TOKEN")
try:
    from dotenv import load_dotenv
    load_dotenv()
    if not TOKEN: 
        TOKEN = os.getenv("DISCORD_TOKEN")
except ImportError:
    pass

# Setup Discord Intents
# 'members' is CRITICAL for Economy/Social features
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True
intents.presences = True

# Initialize Bot
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# 🔗 Attach Database to Bot
# This allows Cogs to access the DB via 'self.bot.db'
bot.db = db_manager 

# ==========================================================
# 🚀 STARTUP EVENTS
# ==========================================================

@bot.event
async def on_ready():
    print(f"\n{'='*40}")
    print(f"🌿 Stoney Baloney v4.2.0 is ONLINE")
    print(f"✅ Logged in as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print(f"🐍 Python: {platform.python_version()}")
    print(f"👾 Discord.py: {discord.__version__}")
    print(f"💾 Database: {bot.db.filename}")
    print(f"{'='*40}\n")
    
    # Set Status
    await bot.change_presence(activity=discord.Game(name="!help | Growing 🌿"))

# ==========================================================
# 🧩 COG LOADER
# ==========================================================

async def load_extensions():
    """Scans the 'cogs' folder and loads every file."""
    if not os.path.exists("./cogs"):
        print("❌ 'cogs' folder not found! Creating it...")
        os.makedirs("./cogs")
        return

    print("⚙️ Loading Cogs...")
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            extension_name = f'cogs.{filename[:-3]}'
            try:
                await bot.load_extension(extension_name)
                print(f"   ✅ Loaded: {filename}")
            except Exception as e:
                print(f"   ❌ FAILED to load: {filename}")
                print(f"      Error: {e}")

# ==========================================================
# 🏁 MAIN ENTRY POINT
# ==========================================================

async def main():
    if not TOKEN:
        print("\n❌ CRITICAL ERROR: 'DISCORD_TOKEN' is missing.")
        print("   Please set it in your environment variables or .env file.")
        return

    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")