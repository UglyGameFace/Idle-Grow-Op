import time

import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id
from world_modes import (
    effective_market_multiplier,
    effective_pot_capacity,
    resolve_game_scope,
)
from utils import (
    GROWTH_CYCLES,
    SHOP_ITEMS,
    _shop_price,
    get_plant_grow_time,
    inv_get,
    inv_take,
    jail_guard,
    jail_left_seconds,
)

QPLANT_MAX_PLANT_PER_CALL = 25


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _seed_cost(seed_key: str) -> int:
    item = SHOP_ITEMS.get(seed_key)
    return int(_shop_price(item) or 0) if item else 0


def _plant_is_ready(profile: dict, world: dict, plant: dict, now: float) -> bool:
    planted_at = float(plant.get("planted_at", now) or now)
    return now - planted_at >= get_plant_grow_time(profile, world, plant)


class Quick(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    async def _scope(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        world = await self.bot.db.get_world(scope.scope_id)
        return scope, profile, world

    @commands.hybrid_command(name="qhelp", aliases=["quickhelp"])
    async def qhelp(self, ctx):
        embed = discord.Embed(title="⚡ Quick Commands", color=discord.Color.blurple())
        embed.add_field(name="Status", value="`/quick` • `/cooldowns` • `/ready`", inline=False)
        embed.add_field(name="Progression", value="`/growdaily` • `/growquests` • `/growachievements`", inline=False)
        embed.add_field(name="Calculator", value="`/calc strain:<strain>`", inline=False)
        embed.add_field(name="Smart Plant", value="`/qplant` or `/qplant count:<number>`", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="quick", aliases=["q"])
    async def quick(self, ctx, option: str = None):
        if option:
            option = option.lower().strip()
            if option in {"grow", "plants", "garden"}:
                command = self.bot.get_command("ready")
                return await ctx.invoke(command) if command else await ctx.send("⚠️ `/ready` is unavailable.")
            if option in {"all", "full", "stats", "profile"}:
                command = self.bot.get_command("profile")
                return await ctx.invoke(command) if command else await ctx.send("⚠️ `/profile` is unavailable.")

        _, profile, world = await self._scope(ctx)
        plants = profile.get("plants", []) or []
        now = time.time()
        ready = sum(1 for plant in plants if _plant_is_ready(profile, world, plant, now))
        heat = max(0, _safe_int(profile.get("heat")))
        jail_time = max(0, _safe_int(jail_left_seconds(profile)))
        status = "🟢"
        if jail_time:
            status = "🔒 JAILED"
        elif heat > 80:
            status = "🔥 HOT"
        elif ready:
            status = "✂️ HARVEST"
        event = world.get("event")
        if isinstance(event, dict):
            status += f" | 🚨 {event.get('name', 'Event')}"
        await ctx.send(
            f"**{ctx.author.display_name}** | {status}\n"
            f"💸 **${max(0, _safe_int(profile.get('grams'))):,}** | "
            f"🧼 **${max(0, _safe_int(profile.get('dirty_cash'))):,}** | 🚓 **{heat}%**\n"
            f"🌿 **{len(plants)} Plants** ({ready} Ready)"
        )

    @commands.hybrid_command(name="cooldowns", aliases=["cd", "timers"])
    async def cooldowns(self, ctx):
        scope, profile, world = await self._scope(ctx)
        now = time.time()
        last_daily = float(profile.get("last_daily", 0) or 0)
        remaining = 86_400 - (now - last_daily)
        daily = "✅ **READY**" if remaining <= 0 else f"⏳ {int(remaining // 3600)}h {int((remaining % 3600) // 60)}m"
        jail_remaining = max(0, _safe_int(jail_left_seconds(profile)))
        jail = "🔓 Free" if not jail_remaining else f"🔒 {jail_remaining // 60}m {jail_remaining % 60}s"
        embed = discord.Embed(title="⏱️ Timers", color=discord.Color.blue())
        embed.add_field(name="☀️ Daily Reward", value=daily, inline=True)
        embed.add_field(name="👮 Jail Time", value=jail, inline=True)
        if scope.multiplayer and profile.get("crew_id"):
            district = world.get("district", {}) or {}
            expires_at = float(district.get("expires_at", 0) or 0)
            if expires_at > now:
                embed.add_field(name="🏙️ District", value=f"🛡️ Protected ({int((expires_at - now) / 60)}m)", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ready", aliases=["r"])
    async def ready(self, ctx):
        _, profile, world = await self._scope(ctx)
        now = time.time()
        ready_plants = [
            f"🌿 **{str(plant.get('strain', 'unknown')).title()}**"
            for plant in profile.get("plants", []) or []
            if _plant_is_ready(profile, world, plant, now)
        ]
        if not ready_plants:
            return await ctx.send("⏳ No plants ready.")
        await ctx.send("✂️ **Ready to Harvest:**\n" + "\n".join(ready_plants[:30]))

    @commands.hybrid_command(name="calc", aliases=["profit"])
    async def calc(self, ctx, *, strain: str):
        strain = str(strain or "").lower().strip()
        if strain not in GROWTH_CYCLES:
            return await ctx.send("❌ Unknown strain.")
        _, _, world = await self._scope(ctx)
        data = GROWTH_CYCLES[strain]
        seed_cost = _seed_cost(f"{strain} seed")
        average_yield = sum(data["yield"]) / 2
        market = effective_market_multiplier(world, scope)
        revenue = average_yield * float(data.get("base_value", 0) or 0) * market
        embed = discord.Embed(title=f"📊 Analysis: {strain.title()}", color=discord.Color.gold())
        embed.add_field(name="⏱️ Time", value=f"{int(float(data.get('time', 0)) / 60)} mins", inline=True)
        embed.add_field(name="🌱 Seed Cost", value=f"${seed_cost:,}", inline=True)
        embed.add_field(name="📦 Avg Yield", value=f"{average_yield:.1f}g", inline=True)
        embed.add_field(name="💰 Est. Revenue", value=f"${int(revenue):,}", inline=True)
        embed.add_field(name="📈 Net Profit", value=f"**${int(revenue - seed_cost):,}**", inline=False)
        embed.set_footer(text=f"Current Market: {int(market * 100)}%")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="qplant", aliases=["qp", "quickplant"])
    async def qplant(self, ctx, count: int = None):
        scope, profile, _ = await self._scope(ctx)
        if await jail_guard(ctx, profile, "plant"):
            return
        desired = max(1, min(_safe_int(count, QPLANT_MAX_PLANT_PER_CALL), QPLANT_MAX_PLANT_PER_CALL)) if count is not None else None

        async with self.bot.db.lock:
            plants = profile.setdefault("plants", [])
            max_pots = effective_pot_capacity(profile, scope)
            free_slots = max(0, max_pots - len(plants))
            if free_slots <= 0:
                return await ctx.send(f"🚫 **No Pots Available!** ({len(plants)}/{max_pots})")
            desired = min(desired or free_slots, free_slots)
            level = max(1, _safe_int(profile.get("level"), 1))
            candidates = []
            for strain, data in GROWTH_CYCLES.items():
                if level < _safe_int(data.get("level_req"), 1):
                    continue
                seed = f"{strain} seed"
                owned = max(0, _safe_int(inv_get(profile, seed)))
                if not owned:
                    continue
                low, high = data.get("yield", (0, 0))
                score = float(data.get("base_value", 0) or 0) * ((float(low) + float(high)) / 2)
                candidates.append((score, strain, seed, owned))
            if not candidates:
                return await ctx.send("❌ You don't have any plantable seeds for your current level.")
            candidates.sort(reverse=True)
            planted = []
            now = time.time()
            for _, strain, seed, owned in candidates:
                for _ in range(min(owned, desired - len(planted))):
                    if not inv_take(profile, seed, 1):
                        break
                    plants.append(
                        {
                            "strain": strain,
                            "planted_at": now,
                            "last_watered": now,
                            "water_count": 1,
                            "quality": 1.0,
                        }
                    )
                    planted.append(strain)
                    if len(planted) >= desired:
                        break
                if len(planted) >= desired:
                    break
            if planted:
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        if not planted:
            return await ctx.send("⚠️ Couldn't plant anything.")
        preview = ", ".join(name.title() for name in planted[:10])
        if len(planted) > 10:
            preview += f" … (+{len(planted) - 10} more)"
        await ctx.send(f"✅ Planted **{len(planted)}** plant(s).\n🌱 {preview}")


async def setup(bot):
    await bot.add_cog(Quick(bot))
