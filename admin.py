import discord
import os
import sys
import json
import time
from discord.ext import commands
from utils import db_manager, inv_add, inv_take, SHOP_ITEMS

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==========================================================
    # 👑 OWNER ONLY CHECKS
    # ==========================================================
    async def cog_check(self, ctx):
        """Only allow the bot owner to use these commands."""
        return await self.bot.is_owner(ctx.author)

    # ==========================================================
    # 🛠️ SYSTEM COMMANDS
    # ==========================================================
    @commands.command(hidden=True)
    async def sync(self, ctx):
        """Syncs slash commands (Important!)."""
        msg = await ctx.send("⚙️ Syncing commands...")
        try:
            synced = await self.bot.tree.sync()
            await msg.edit(content=f"✅ **Synced {len(synced)} slash commands.**")
        except Exception as e:
            await msg.edit(content=f"❌ Sync failed: {e}")

    @commands.command(hidden=True)
    async def reload(self, ctx, extension):
        """Reloads a specific cog (e.g. !reload cogs.farming)."""
        try:
            await self.bot.reload_extension(f"cogs.{extension}")
            await ctx.send(f"✅ Reloaded `{extension}`")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(hidden=True)
    async def restart(self, ctx):
        """Restarts the bot process."""
        await ctx.send("👋 Restarting...")
        os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(hidden=True)
    async def backup(self, ctx):
        """Force a database backup."""
        await self.bot.db.save()
        await ctx.send("💾 **Database Saved.**")

    # ==========================================================
    # 💰 ECONOMY MANAGEMENT
    # ==========================================================
    @commands.command(name="setmoney", hidden=True)
    async def setmoney(self, ctx, target: discord.User, amount: int):
        """Set a user's balance."""
        user = self.bot.db.get_user(target.id)
        user["grams"] = amount
        await self.bot.db.save()
        await ctx.send(f"✅ Set {target.name}'s balance to **${amount:,}**.")

    @commands.command(name="giveitem", hidden=True)
    async def giveitem(self, ctx, target: discord.User, item_name: str, amount: int = 1):
        """Spawn items for a user."""
        user = self.bot.db.get_user(target.id)
        clean_name = item_name.lower().strip()
        
        inv_add(user, clean_name, amount)
        await self.bot.db.save()
        await ctx.send(f"✅ Gave **x{amount} {clean_name}** to {target.name}.")

    @commands.command(name="setlevel", hidden=True)
    async def setlevel(self, ctx, target: discord.User, level: int):
        """Set a user's level."""
        user = self.bot.db.get_user(target.id)
        user["level"] = level
        user["xp"] = 0
        await self.bot.db.save()
        await ctx.send(f"✅ Set {target.name}'s level to **{level}**.")

    # ==========================================================
    # 🚨 MODERATION / DEBUG
    # ==========================================================
    @commands.command(name="wipeuser", hidden=True)
    async def wipeuser(self, ctx, target: discord.User):
        """Reset a user's profile completely."""
        confirm_msg = await ctx.send(f"⚠️ **WARNING:** Are you sure you want to WIPE {target.name}? Type `yes`.")
        
        def check(m):
            return m.author == ctx.author and m.content.lower() == "yes"
            
        try:
            await self.bot.wait_for("message", timeout=15.0, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("❌ Cancelled.")

        uid = str(target.id)
        if uid in self.bot.db.data:
            # We don't delete the key, just reset values to default
            # to avoid key errors elsewhere.
            from utils import make_default_user
            self.bot.db.data[uid] = make_default_user()
            await self.bot.db.save()
            await ctx.send(f"💀 **Wiped {target.name}.** RIP.")
        else:
            await ctx.send("❌ User not found in DB.")

    @commands.command(name="announce", hidden=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message):
        """Make the bot say something."""
        await channel.send(message)
        await ctx.message.add_reaction("✅")

async def setup(bot):
    await bot.add_cog(Admin(bot))