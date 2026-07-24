import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id
from progression_core import (
    check_achievements,
    claim_daily,
    ensure_daily_quests,
    ensure_progression,
)
from progression_data import ACHIEVEMENTS


class Progression(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    async def _profile(self, ctx):
        guild_id = require_guild_id(ctx)
        profile = await self.bot.db.get_profile(guild_id, ctx.author.id)
        return guild_id, profile

    async def _claim_daily(self, ctx):
        guild_id, profile = await self._profile(ctx)
        async with self.bot.db.lock:
            result = claim_daily(profile, user_id=ctx.author.id)
            if result["ok"]:
                check_achievements(profile)
                self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)

        if result["already"]:
            return await ctx.send("⏳ You already claimed today's grow reward.")

        embed = discord.Embed(title="🌿 Daily Grow Reward", color=discord.Color.green())
        embed.add_field(name="Cash", value=f"${result['cash']:,}", inline=True)
        embed.add_field(name="XP", value=f"{result['xp']:,}", inline=True)
        embed.add_field(name="Streak", value=f"{result['streak']} day(s)", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="growdaily", aliases=["daily", "checkin", "claim"])
    async def growdaily(self, ctx):
        """Claim the server-local daily grow reward."""
        await self._claim_daily(ctx)

    @commands.hybrid_command(name="growclaim")
    async def growclaim(self, ctx):
        await self._claim_daily(ctx)

    @commands.hybrid_command(name="growcheckin")
    async def growcheckin(self, ctx):
        await self._claim_daily(ctx)

    @commands.hybrid_command(name="growquests", aliases=["quests", "dq", "dailyquests"])
    async def growquests(self, ctx):
        guild_id, profile = await self._profile(ctx)
        async with self.bot.db.lock:
            refreshed = ensure_daily_quests(profile, user_id=ctx.author.id)
            if refreshed:
                self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)
            quests = [dict(item) for item in profile.get("daily_quests", []) if isinstance(item, dict)]

        lines = []
        for quest in quests:
            progress = max(0, int(quest.get("progress", 0)))
            target = max(1, int(quest.get("target", 1)))
            marker = "✅" if quest.get("completed") else "▫️"
            lines.append(
                f"{marker} **{quest.get('name', 'Daily Quest')}**\n"
                f"{quest.get('desc', '')}\n"
                f"Progress: **{progress:,}/{target:,}** • "
                f"Reward: **${int(quest.get('reward_cash', 0)):,} + {int(quest.get('reward_xp', 0)):,} XP**"
            )

        embed = discord.Embed(
            title="📜 Daily Grow Quests",
            description="\n\n".join(lines) or "No quests are available.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="growachievements", aliases=["achievements", "achs", "ach"])
    async def growachievements(self, ctx):
        guild_id, profile = await self._profile(ctx)
        async with self.bot.db.lock:
            ensure_progression(profile)
            newly_unlocked = check_achievements(profile)
            if newly_unlocked:
                self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)
            owned = set(profile.get("achievements", []))

        lines = []
        for achievement_id, achievement in ACHIEVEMENTS.items():
            current, target = achievement.progress(profile)
            if achievement_id in owned:
                lines.append(f"✅ **{achievement.name}** — completed")
            else:
                lines.append(
                    f"▫️ **{achievement.name}** — {min(current, target):,}/{target:,}\n"
                    f"{achievement.desc}"
                )

        embed = discord.Embed(
            title=f"🏆 {ctx.author.display_name}'s Achievements",
            description="\n\n".join(lines)[:4000] or "No achievements configured.",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Unlocked: {len(owned)}/{len(ACHIEVEMENTS)}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="growlevel", aliases=["level", "lvl", "rank"])
    async def growlevel(self, ctx):
        _, profile = await self._profile(ctx)
        level = max(1, int(profile.get("level", 1)))
        xp = max(0, int(profile.get("xp", 0)))
        next_level_xp = max(100, level * 500)
        embed = discord.Embed(title=f"📈 {ctx.author.display_name}'s Progress", color=discord.Color.green())
        embed.add_field(name="Level", value=f"**{level:,}**", inline=True)
        embed.add_field(name="XP", value=f"**{xp:,}/{next_level_xp:,}**", inline=True)
        embed.add_field(name="Prestige", value=f"**{max(0, int(profile.get('prestige', 0))):,}**", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Progression(bot))
