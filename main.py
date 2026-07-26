import asyncio
import logging
import os
import platform
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from persistence_bootstrap import build_scoped_database


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
    "gambling",
    "lab",
    "notification_preferences",
    "onboarding",
    "progression",
    "quick",
    "profile_signatures",
    "sesh",
    "setup",
    "social",
    "tasks",
    "world_modes",
)

COMMAND_SYNC_ATTEMPTS = 3
COMMAND_SYNC_RETRY_SECONDS = 5
REQUIRED_PUBLIC_COMMANDS = frozenset(
    {
        "setup",
        "start",
        "help",
        "notifications",
        "world-mode",
    }
)
STALE_PUBLIC_COMMANDS = frozenset({"sesh_setup"})


async def sync_global_commands(
    tree: app_commands.CommandTree,
) -> list[app_commands.AppCommand]:
    """Publish the complete global command tree once before the bot connects."""
    local_commands = list(tree.get_commands())
    local_names = {command.name for command in local_commands}
    if not local_names:
        raise RuntimeError("Local application-command tree is empty; refusing startup")

    missing_local = REQUIRED_PUBLIC_COMMANDS - local_names
    if missing_local:
        raise RuntimeError(
            "Required public commands were not registered locally: "
            + ", ".join(sorted(missing_local))
        )

    stale_local = STALE_PUBLIC_COMMANDS & local_names
    if stale_local:
        raise RuntimeError(
            "Stale commands remain in the local command tree: "
            + ", ".join(sorted(stale_local))
        )

    last_error: discord.HTTPException | None = None
    for attempt in range(1, COMMAND_SYNC_ATTEMPTS + 1):
        try:
            synced = list(await tree.sync())
        except discord.HTTPException as exc:
            last_error = exc
            if attempt >= COMMAND_SYNC_ATTEMPTS:
                break
            delay = COMMAND_SYNC_RETRY_SECONDS * attempt
            logger.warning(
                "Global command sync failed on attempt %s/%s; retrying in %ss: %s",
                attempt,
                COMMAND_SYNC_ATTEMPTS,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            continue

        synced_names = {command.name for command in synced}
        if not synced_names:
            raise RuntimeError("Discord returned an empty global command set; refusing startup")

        missing_remote = REQUIRED_PUBLIC_COMMANDS - synced_names
        if missing_remote:
            raise RuntimeError(
                "Discord sync omitted required public commands: "
                + ", ".join(sorted(missing_remote))
            )

        stale_remote = STALE_PUBLIC_COMMANDS & synced_names
        if stale_remote:
            raise RuntimeError(
                "Discord sync retained stale commands: "
                + ", ".join(sorted(stale_remote))
            )

        logger.info(
            "Synced %s global application commands: %s",
            len(synced),
            ", ".join(sorted(synced_names)),
        )
        return synced

    raise RuntimeError(
        f"Global application-command sync failed after {COMMAND_SYNC_ATTEMPTS} attempts"
    ) from last_error


class IdleGrowBot(commands.Bot):
    async def setup_hook(self) -> None:
        """Use Discord.py's one-time startup hook to publish slash commands."""
        await sync_global_commands(self.tree)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = IdleGrowBot(command_prefix="!", intents=intents, help_command=None)


async def _configured_error_channel(guild_id: int | None):
    if guild_id is None or not hasattr(bot, "db"):
        return None
    try:
        resolved_guild_id = int(guild_id)
    except (TypeError, ValueError):
        logger.warning("Invalid guild ID supplied to error reporter: %r", guild_id)
        return None

    guild = bot.get_guild(resolved_guild_id)
    if guild is None:
        return None
    try:
        world = await bot.db.get_world(resolved_guild_id)
        channel_id = world.get("settings", {}).get("error_log_channel_id")
    except Exception:
        logger.exception("Failed to resolve error channel for guild %s", resolved_guild_id)
        return None
    if not channel_id:
        return None
    try:
        resolved_channel_id = int(channel_id)
    except (TypeError, ValueError):
        logger.warning(
            "Configured error channel ID is invalid for guild %s: %r",
            resolved_guild_id,
            channel_id,
        )
        return None
    channel = guild.get_channel(resolved_channel_id)
    return channel if isinstance(channel, discord.TextChannel) else None


async def _report_error(title: str, detail: str, *, guild_id: int | None) -> None:
    logger.error("%s | %s", title, detail)
    channel = await _configured_error_channel(guild_id)
    if channel is None:
        return
    guild = channel.guild
    member = guild.me
    if member is None:
        return
    permissions = channel.permissions_for(member)
    if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
        logger.warning("Configured error channel is unusable for guild %s", guild.id)
        return
    try:
        await channel.send(
            embed=discord.Embed(
                title=f"🚨 {title}",
                description=detail[:4000],
                color=discord.Color.red(),
            )
        )
    except discord.DiscordException:
        logger.exception("Failed to send command error to guild %s", guild.id)
    except Exception:
        logger.exception("Unexpected failure in guild error reporter for guild %s", guild.id)


async def _report_command_error(
    *,
    guild_id: int | None,
    title: str,
    description: str,
) -> None:
    await _report_error(title, description, guild_id=guild_id)


bot.report_command_error = _report_command_error


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"⏳ Try again in **{error.retry_after:.1f}s**.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Missing `{error.param.name}`. Try `/help` for usage.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("❌ I couldn't understand one of those values. Check the command usage and try again.")
    if isinstance(error, commands.CheckFailure):
        return await ctx.send("❌ You cannot use that command here.")

    original = getattr(error, "original", error)
    guild_id = getattr(ctx.guild, "id", None)
    context = (
        f"command={getattr(ctx.command, 'qualified_name', 'unknown')} "
        f"guild={guild_id} channel={getattr(ctx.channel, 'id', None)} "
        f"user={getattr(ctx.author, 'id', None)} error={type(original).__name__}: {original}"
    )
    await _report_error("Prefix command failure", context, guild_id=guild_id)
    try:
        await ctx.send("❌ Something went wrong running that command. The error was recorded.")
    except discord.HTTPException:
        pass


async def _tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    detail = (
        f"command={getattr(interaction.command, 'qualified_name', 'unknown')} "
        f"guild={interaction.guild_id} channel={interaction.channel_id} user={interaction.user.id} "
        f"error={type(original).__name__}: {original}"
    )
    await _report_error("Slash command failure", detail, guild_id=interaction.guild_id)
    message = "❌ Something went wrong running that command. The error was recorded."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


bot.tree.on_error = _tree_error


@bot.event
async def on_ready():
    logger.info("=" * 40)
    logger.info("Idle Grow Op Enterprise Scoped is ONLINE")
    logger.info("Logged in as: %s", bot.user)
    logger.info("Bot ID: %s", bot.user.id if bot.user else "unknown")
    logger.info("Python: %s", platform.python_version())
    logger.info("Discord.py: %s", discord.__version__)
    logger.info("Database: verified guild-scoped Supabase")
    logger.info("Loaded extensions: %s", ", ".join(sorted(bot.extensions)))
    logger.info("=" * 40)
    await bot.change_presence(activity=discord.Game(name="/help • /start • Growing 🌿"))


async def load_extensions() -> None:
    """Load every canonical Enterprise extension from the repository root."""
    failures = []
    for extension_name in GAME_EXTENSIONS:
        try:
            await bot.load_extension(extension_name)
            logger.info("Loaded extension: %s", extension_name)
        except Exception:
            logger.exception("Failed to load extension: %s", extension_name)
            failures.append(extension_name)
    if failures:
        raise RuntimeError(f"Required game extensions failed to load: {', '.join(failures)}")


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing from the environment")

    database = await build_scoped_database()
    bot.db = database
    try:
        async with bot:
            await load_extensions()
            await bot.start(TOKEN)
    finally:
        await database.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.critical("Fatal startup failure\n%s", traceback.format_exc())
        raise
