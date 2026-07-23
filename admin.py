import asyncio
import os
import sys

import discord
from discord.ext import commands

from economy_integrity import require_positive_amount
from utils import db_manager, inv_add


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
        """Request a database synchronization."""
        await self.bot.db.save()
        await ctx.send("💾 **Database save queued.**")

    @commands.command(name="setmoney", hidden=True)
    async def setmoney(self, ctx, target: discord.User, amount: int):
        """Set a user's non-negative cash balance."""
        if amount < 0:
            return await ctx.send("❌ Balance cannot be negative.")

        async with self.bot.db.lock:
            user = self.bot.db.get_user(target.id)
            user["grams"] = int(amount)
            await self.bot.db.save()
        await ctx.send(f"✅ Set {target.name}'s balance to **${amount:,}**.")

    @commands.command(name="giveitem", hidden=True)
    async def giveitem(self, ctx, target: discord.User, item_name: str, amount: int = 1):
        """Spawn a positive quantity of items for a user."""
        try:
            quantity = require_positive_amount(amount)
        except ValueError:
            return await ctx.send("❌ Item amount must be a positive integer.")

        clean_name = item_name.lower().strip()
        if not clean_name:
            return await ctx.send("❌ Item name cannot be empty.")

        async with self.bot.db.lock:
            user = self.bot.db.get_user(target.id)
            inv_add(user, clean_name, quantity)
            await self.bot.db.save()
        await ctx.send(f"✅ Gave **x{quantity} {clean_name}** to {target.name}.")

    @commands.command(name="setlevel", hidden=True)
    async def setlevel(self, ctx, target: discord.User, level: int):
        """Set a user's level to one or higher."""
        try:
            validated_level = require_positive_amount(level)
        except ValueError:
            return await ctx.send("❌ Level must be a positive integer.")

        async with self.bot.db.lock:
            user = self.bot.db.get_user(target.id)
            user["level"] = validated_level
            user["xp"] = 0
            await self.bot.db.save()
        await ctx.send(f"✅ Set {target.name}'s level to **{validated_level}**.")

    @commands.command(name="wipeuser", hidden=True)
    async def wipeuser(self, ctx, target: discord.User):
        """Reset a user's profile completely."""
        await ctx.send(
            f"⚠️ **WARNING:** Are you sure you want to WIPE {target.name}? Type `yes`."
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

        from utils import make_default_user

        uid = str(target.id)
        async with self.bot.db.lock:
            if uid not in self.bot.db.data:
                return await ctx.send("❌ User not found in DB.")
            self.bot.db.data[uid] = make_default_user()
            await self.bot.db.save()
        await ctx.send(f"💀 **Wiped {target.name}.** RIP.")

    @commands.command(name="announce", hidden=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message):
        """Make the bot say something."""
        await channel.send(message)
        await ctx.message.add_reaction("✅")


async def setup(bot):
    await bot.add_cog(Admin(bot))
