import random
import time

import discord
from discord.ext import commands

from economy_integrity import calculate_harvest_outcome
from persistence_context import require_guild_id
from progression_core import add_progress, check_achievements, credit_xp
from world_modes import effective_pot_capacity, resolve_game_scope
from utils import (
    GROWTH_CYCLES,
    discord_relative_time,
    get_plant_grow_time,
    inv_get,
    inv_take,
    jail_guard,
)


class Farming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="plant", aliases=["p", "grow"])
    async def plant(self, ctx, *, strain_name: str = ""):
        """Plant a seed in the current server's grow operation."""
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, user, "plant"):
            return

        if not strain_name:
            return await ctx.send("🌱 **Usage:** `/plant strain_name:<strain>` (example: `/plant strain_name:schwag`)")

        clean_name = strain_name.lower().replace(" seed", "").strip()
        seed_item_name = f"{clean_name} seed"

        if clean_name not in GROWTH_CYCLES:
            return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `/strains`.")

        strain_info = GROWTH_CYCLES[clean_name]
        world = await self.bot.db.get_world(scope.scope_id)

        plant_error = None
        planted_at = 0.0
        new_plant = None
        async with self.bot.db.lock:
            if int(user.get("level", 1)) < int(strain_info.get("level_req", 1)):
                plant_error = f"🔒 You need Level **{strain_info['level_req']}** to grow this."
            elif inv_get(user, seed_item_name) < 1:
                plant_error = (
                    f"❌ You don\'t have any **{clean_name.title()} Seeds**!\n"
                    f"Use `/shop`, then `/buy item_name:{seed_item_name}`."
                )
            else:
                max_pots = effective_pot_capacity(user, scope)
                current_plants = user.setdefault("plants", [])
                if len(current_plants) >= max_pots:
                    plant_error = (
                        f"🚫 **No Pots Available!** ({len(current_plants)}/{max_pots})\n"
                        "Harvest plants or buy Pot Upgrades in the shop."
                    )
                elif not inv_take(user, seed_item_name, 1):
                    plant_error = "❌ That seed is no longer available. Try again."
                else:
                    planted_at = time.time()
                    new_plant = {
                        "strain": clean_name,
                        "planted_at": planted_at,
                    }
                    current_plants.append(new_plant)
                    add_progress(user, "plant", 1, user_id=ctx.author.id)
                    check_achievements(user)
                    self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        if plant_error:
            return await ctx.send(plant_error)
        grow_time = get_plant_grow_time(user, world, new_plant)
        ready_at = int(planted_at + grow_time)
        await ctx.send(f"🌱 **Planted:** {clean_name.title()}\n⏳ **Ready:** {discord_relative_time(ready_at)}")

    @commands.hybrid_command(name="harvest", aliases=["h"])
    async def harvest(self, ctx):
        """Harvest ready plants into this server's flower stash."""
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, user, "harvest"):
            return
        world = await self.bot.db.get_world(scope.scope_id)

        harvest_error = None
        outcome = None
        level_before = max(1, int(user.get("level", 1) or 1))
        level_after = level_before
        async with self.bot.db.lock:
            plants = user.get("plants", [])
            if not plants:
                harvest_error = "🌱 You have no plants."
            else:
                multiplier = 1.0
                if inv_get(user, "led lights") > 0:
                    multiplier += 0.5
                if inv_get(user, "hydroponic") > 0:
                    multiplier += 1.0

                outcome = calculate_harvest_outcome(
                    plants,
                    now=time.time(),
                    strain_configs=GROWTH_CYCLES,
                    grow_time_for_plant=lambda plant: get_plant_grow_time(user, world, plant),
                    yield_multiplier=multiplier,
                    randint=random.randint,
                )

                if outcome["harvested_count"] == 0:
                    harvest_error = (
                        "⏳ **Nothing is ready to harvest yet.**\n"
                        "Use `/status` to check remaining time."
                    )
                else:
                    user["plants"] = outcome["remaining_plants"]
                    stash = user.setdefault("flower_stash", {})
                    for strain, amount in outcome["flower_by_strain"].items():
                        stash[strain] = max(0, int(stash.get(strain, 0))) + max(0, int(amount))

                    stats = user.setdefault("stats", {})
                    stats["harvested"] = max(0, int(stats.get("harvested", 0))) + outcome["harvested_count"]

                    level_before = max(1, int(user.get("level", 1) or 1))
                    credit_xp(user, outcome["total_xp"])
                    add_progress(
                        user,
                        "harvest",
                        outcome["harvested_count"],
                        user_id=ctx.author.id,
                    )
                    check_achievements(user)
                    level_after = max(1, int(user.get("level", 1) or 1))
                    self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        if harvest_error:
            return await ctx.send(harvest_error)
        if level_after > level_before:
            await ctx.send(f"🎉 **LEVEL UP!** You are now Level **{level_after}**!")

        harvested_summary = ", ".join(
            f"{strain.title()} ({amount}g)"
            for strain, amount in sorted(outcome["flower_by_strain"].items())
        )
        embed = discord.Embed(title="✂️ Harvest Successful", color=discord.Color.green())
        embed.add_field(name="Yield", value=f"**{outcome['total_yield']}g** Flower", inline=True)
        embed.add_field(name="XP Gained", value=f"+{outcome['total_xp']} XP", inline=True)
        embed.add_field(name="Plants", value=harvested_summary, inline=False)
        embed.set_footer(text=f"Remaining Plants: {len(outcome['remaining_plants'])}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="status", aliases=["quickcheck", "check", "garden"])
    async def status(self, ctx):
        """Check plant progress for the current server."""
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        plants = user.get("plants", [])

        if not plants:
            embed = discord.Embed(
                title="🌱 Your Garden",
                description="Empty. Use `/start` for your next step or `/plant` after buying a seed.",
                color=0x2F3136,
            )
            return await ctx.send(embed=embed)

        world = await self.bot.db.get_world(scope.scope_id)
        embed = discord.Embed(title=f"🌱 {ctx.author.name}'s Garden", color=discord.Color.green())
        now = time.time()
        lines = []
        ready_count = 0

        for index, plant in enumerate(plants, start=1):
            strain = plant["strain"]
            grow_time = get_plant_grow_time(user, world, plant)
            elapsed = now - float(plant["planted_at"])
            percent = min(100, max(0, int((elapsed / grow_time) * 100)))
            filled = int(percent / 10)
            bar = "🟩" * filled + "⬛" * (10 - filled)

            if percent >= 100:
                status_text = "✅ **READY**"
                ready_count += 1
            else:
                remaining_seconds = max(0, grow_time - elapsed)
                minutes, _seconds = divmod(remaining_seconds, 60)
                status_text = f"**{percent}%** ({int(minutes)}m left)"

            lines.append(f"**{index}. {strain.title()}**\n{bar} {status_text}")

        embed.description = "\n\n".join(lines)
        if ready_count > 0:
            embed.set_footer(text=f"{ready_count} plants ready! Run /harvest")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="strains", aliases=["seeds"])
    async def strains(self, ctx):
        """List available strains."""
        require_guild_id(ctx)
        embed = discord.Embed(title="🧬 Strain Database", color=discord.Color.purple())
        sorted_strains = sorted(GROWTH_CYCLES.items(), key=lambda item: item[1]["level_req"])

        for _name, data in sorted_strains:
            embed.add_field(
                name=f"Lv{data['level_req']} {data['display_name']}",
                value=f"⏱️ {int(data['time'] / 60)}m | 📦 Yield: {data['yield'][0]}-{data['yield'][1]}g",
                inline=True,
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Farming(bot))
