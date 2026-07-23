import random
import time

import discord
from discord.ext import commands

from economy_integrity import calculate_harvest_outcome
from utils import (
    GROWTH_CYCLES,
    check_achievements,
    discord_relative_time,
    get_plant_grow_time,
    inv_get,
    inv_take,
    jail_guard,
)


class Farming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _add_xp(self, ctx, user, amount):
        """Add XP and handle level ups."""
        if amount <= 0:
            return

        user["xp"] = int(user.get("xp", 0)) + int(amount)
        current_level = int(user.get("level", 1))
        required = int(100 * (current_level ** 1.5))

        if user["xp"] >= required:
            user["xp"] -= required
            user["level"] = current_level + 1
            await ctx.send(f"🎉 **LEVEL UP!** You are now Level **{user['level']}**!")

    @commands.hybrid_command(name="plant", aliases=["p", "grow"])
    async def plant(self, ctx, *, strain_name: str = ""):
        """Plant a seed."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "plant"):
            return

        if not strain_name:
            return await ctx.send("🌱 **Usage:** `!plant <strain name>` (e.g., `!plant og kush`)")

        clean_name = strain_name.lower().replace(" seed", "").strip()
        seed_item_name = f"{clean_name} seed"

        if clean_name not in GROWTH_CYCLES:
            return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `!strains`.")

        strain_info = GROWTH_CYCLES[clean_name]
        if user.get("level", 1) < strain_info.get("level_req", 1):
            return await ctx.send(f"🔒 You need Level **{strain_info['level_req']}** to grow this.")

        if inv_get(user, seed_item_name) < 1:
            return await ctx.send(
                f"❌ You don't have any **{clean_name.title()} Seeds**!\nBuy some in the `!shop`."
            )

        max_pots = int(user.get("max_pots", 3))
        current_plants = user.get("plants", [])
        if len(current_plants) >= max_pots:
            return await ctx.send(
                f"🚫 **No Pots Available!** ({len(current_plants)}/{max_pots})\n"
                "Harvest plants or buy Pot Upgrades in the shop."
            )

        if not inv_take(user, seed_item_name, 1):
            return await ctx.send("❌ That seed is no longer available. Try again.")

        new_plant = {
            "strain": clean_name,
            "planted_at": time.time(),
            "last_watered": time.time(),
            "water_count": 1,
            "quality": 1.0,
        }
        user.setdefault("plants", []).append(new_plant)
        await self.bot.db.save()

        grow_time = get_plant_grow_time(user, self.bot.db.world_state, new_plant)
        ready_at = int(time.time() + grow_time)
        await ctx.send(f"🌱 **Planted:** {clean_name.title()}\n⏳ **Ready:** {discord_relative_time(ready_at)}")

    @commands.hybrid_command(name="water", aliases=["hydrate"])
    async def water(self, ctx):
        """Water all plants that are ready for watering."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "water"):
            return

        plants = user.get("plants", [])
        if not plants:
            return await ctx.send("🏜️ You have no plants to water.")

        count = 0
        now = time.time()
        for plant in plants:
            if now - plant.get("last_watered", 0) > 300:
                plant["last_watered"] = now
                plant["water_count"] = plant.get("water_count", 0) + 1
                count += 1

        if count == 0:
            return await ctx.send("💧 Plants are already wet enough.")

        await self.bot.db.save()
        await ctx.send(f"💦 **Watered {count} plants.** Keep 'em happy!")

    @commands.hybrid_command(name="harvest", aliases=["h"])
    async def harvest(self, ctx):
        """Harvest all ready plants into the flower stash."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "harvest"):
            return

        plants = user.get("plants", [])
        if not plants:
            return await ctx.send("🌱 You have no plants.")

        multiplier = 1.0
        if inv_get(user, "led lights") > 0:
            multiplier += 0.5
        if inv_get(user, "hydroponic") > 0:
            multiplier += 1.0

        world = self.bot.db.world_state
        outcome = calculate_harvest_outcome(
            plants,
            now=time.time(),
            strain_configs=GROWTH_CYCLES,
            grow_time_for_plant=lambda plant: get_plant_grow_time(user, world, plant),
            yield_multiplier=multiplier,
            randint=random.randint,
        )

        if outcome["harvested_count"] == 0:
            return await ctx.send(
                "⏳ **Nothing is ready to harvest yet.**\nUse `!status` to check remaining time."
            )

        # Harvesting produces flower only. Cash is credited later by the sell command.
        user["plants"] = outcome["remaining_plants"]
        stash = user.setdefault("flower_stash", {})
        for strain, amount in outcome["flower_by_strain"].items():
            stash[strain] = int(stash.get(strain, 0)) + int(amount)

        stats = user.setdefault("stats", {})
        stats["harvested"] = int(stats.get("harvested", 0)) + outcome["harvested_count"]

        await self._add_xp(ctx, user, outcome["total_xp"])
        await self.bot.db.save()
        await check_achievements(ctx, user)

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
        """Check plant progress."""
        user = self.bot.db.get_user(ctx.author.id)
        plants = user.get("plants", [])

        if not plants:
            embed = discord.Embed(
                title="🌱 Your Garden",
                description="Empty. Use `!plant` to start growing!",
                color=0x2F3136,
            )
            return await ctx.send(embed=embed)

        embed = discord.Embed(title=f"🌱 {ctx.author.name}'s Garden", color=discord.Color.green())
        now = time.time()
        world = self.bot.db.world_state
        lines = []
        ready_count = 0

        for index, plant in enumerate(plants, start=1):
            strain = plant["strain"]
            grow_time = get_plant_grow_time(user, world, plant)
            elapsed = now - plant["planted_at"]
            percent = min(100, int((elapsed / grow_time) * 100))
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
            embed.set_footer(text=f"{ready_count} plants ready! Type !harvest")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="strains", aliases=["seeds"])
    async def strains(self, ctx):
        """List available strains."""
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
