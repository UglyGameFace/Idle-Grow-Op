import asyncio
import os
import sys

import discord
from discord.ext import commands

from economy_integrity import require_positive_amount
from persistence_context import (
    get_context_profile,
    mark_context_profile_dirty,
    require_guild_id,
)
from scoped_database import make_default_profile
from utils import inv_add


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        """Only allow the bot owner to use these commands."""
        return await self.bot.is_owner(ctx.author)

    @commands.command(hidden=True)
    async def sync(self, ctx):
        """Sync slash commands."""
        msg = await ctx.send("⚙️ Syncing commands...")
        try:
            synced = await self.bot.tree.sync()
            await msg.edit(content=f"✅ **Synced {len(synced)} slash commands.**")
        except Exception as exc:
            await msg.edit(content=f"❌ Sync failed: {exc}")

    @commands.command(hidden=True)
    async def reload(self, ctx, extension):
        """Reload a canonical root extension, such as ``!reload farming``."""
        extension_name = extension.removeprefix("cogs.").strip()
        if extension_name not in getattr(self.bot, "extensions", {}):
            return await ctx.send(f"❌ Unknown or unloaded extension: `{extension_name}`")

        try:
            await self.bot.reload_extension(extension_name)
            await ctx.send(f"✅ Reloaded `{extension_name}`")
        except Exception as exc:
            await ctx.send(f"❌ Error: {exc}")

    @commands.command(hidden=True)
    async def restart(self, ctx):
        """Restart the bot process."""
        await ctx.send("👋 Restarting...")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @commands.command(hidden=True)
    async def backup(self, ctx):
        """Flush all currently dirty scoped records."""
        result = await self.bot.db.flush()
        await ctx.send(f"💾 **Saved {result.saved_count} dirty record(s).**")

    @commands.command(name="setmoney", hidden=True)
    async def setmoney(self, ctx, target: discord.User, amount: int):
        """Set a user's cash balance in the current server."""
        if amount < 0:
            return await ctx.send("❌ Balance cannot be negative.")

        require_guild_id(ctx)
        async with self.bot.db.lock:
            profile = await get_context_profile(self.bot.db, ctx, target.id)
            profile["grams"] = int(amount)
            mark_context_profile_dirty(self.bot.db, ctx, target.id)
        await ctx.send(f"✅ Set {target.name}'s balance to **${amount:,}** in this server.")

    @commands.command(name="giveitem", hidden=True)
    async def giveitem(self, ctx, target: discord.User, item_name: str, amount: int = 1):
        """Spawn a positive quantity of items in the current server."""
        try:
            quantity = require_positive_amount(amount)
        except ValueError:
            return await ctx.send("❌ Item amount must be a positive integer.")

        clean_name = item_name.lower().strip()
        if not clean_name:
            return await ctx.send("❌ Item name cannot be empty.")

        require_guild_id(ctx)
        async with self.bot.db.lock:
            profile = await get_context_profile(self.bot.db, ctx, target.id)
            inv_add(profile, clean_name, quantity)
            mark_context_profile_dirty(self.bot.db, ctx, target.id)
        await ctx.send(f"✅ Gave **x{quantity} {clean_name}** to {target.name} in this server.")

    @commands.command(name="setlevel", hidden=True)
    async def setlevel(self, ctx, target: discord.User, level: int):
        """Set a user's local level to one or higher."""
        try:
            validated_level = require_positive_amount(level)
        except ValueError:
            return await ctx.send("❌ Level must be a positive integer.")

        require_guild_id(ctx)
        async with self.bot.db.lock:
            profile = await get_context_profile(self.bot.db, ctx, target.id)
            profile["level"] = validated_level
            profile["xp"] = 0
            mark_context_profile_dirty(self.bot.db, ctx, target.id)
        await ctx.send(f"✅ Set {target.name}'s level to **{validated_level}** in this server.")

    @commands.command(name="wipeuser", hidden=True)
    async def wipeuser(self, ctx, target: discord.User):
        """Reset a user's profile in the current server only."""
        require_guild_id(ctx)
        await ctx.send(
            f"⚠️ **WARNING:** Wipe {target.name}'s Idle Grow profile in this server? Type `yes`."
        )

        def check(message):
            return (
                message.author == ctx.author
                and message.channel == ctx.channel
                and message.content.lower() == "yes"
            )

        try:
            await self.bot.wait_for("message", timeout=15.0, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("❌ Cancelled.")

        async with self.bot.db.lock:
            profile = await get_context_profile(self.bot.db, ctx, target.id)
            profile.clear()
            profile.update(make_default_profile())
            mark_context_profile_dirty(self.bot.db, ctx, target.id)
        await ctx.send(f"💀 **Wiped {target.name}'s profile in this server.**")

    @commands.command(name="announce", hidden=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message):
        """Make the bot say something."""
        await channel.send(message)
        await ctx.message.add_reaction("✅")


async def setup(bot):
    await bot.add_cog(Admin(bot))
