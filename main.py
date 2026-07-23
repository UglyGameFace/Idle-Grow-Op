import asyncio
import logging
import os
import platform

import discord
from discord.ext import commands
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

GAME_EXTENSIONS = (
    "admin",
    "ai",
    "crime",
    "economy",
    "farming",
    "lab",
    "social",
    "tasks",
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    database_backend = "Supabase" if getattr(bot.db, "supabase", None) else "memory-only fallback"
    logger.info("=" * 40)
    logger.info("Stoney Baloney v4.2.0 is ONLINE")
    logger.info("Logged in as: %s", bot.user)
    logger.info("Bot ID: %s", bot.user.id if bot.user else "unknown")
    logger.info("Python: %s", platform.python_version())
    logger.info("Discord.py: %s", discord.__version__)
    logger.info("Database: %s", database_backend)
    logger.info("Loaded extensions: %s", ", ".join(sorted(bot.extensions)))
    logger.info("=" * 40)

    await bot.change_presence(activity=discord.Game(name="!help | Growing 🌿"))


async def load_extensions() -> None:
    """Load every canonical game extension from the repository root."""
    failures = []

    for extension_name in GAME_EXTENSIONS:
        try:
            await bot.load_extension(extension_name)
            logger.info("Loaded extension: %s", extension_name)
        except Exception:
            logger.exception("Failed to load extension: %s", extension_name)
            failures.append(extension_name)

    if failures:
        failed = ", ".join(failures)
        raise RuntimeError(f"Required game extensions failed to load: {failed}")


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing from the environment")

    # Importing utils constructs the database manager and starts its background
    # sync task. This must happen after asyncio.run() has created the event loop.
    from utils import db_manager

    bot.db = db_manager

    async with bot:
        await load_extensions()
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
