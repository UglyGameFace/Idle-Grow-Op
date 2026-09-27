import random
import time

import discord
from discord.ext import commands

from economy_integrity import calculate_harvest_outcome
from persistence_context import require_guild_id
from plant_care import (
    CARE_WATER_THRESHOLD,
    care_multiplier,
    initialize_plant_care,
    plant_care_grade,
    plant_care_status,
    plant_moisture,
    water_plant,
)
from plant_lifecycle import (
    MAX_PLANTS_PER_ACTION,
    plant_duration_seconds,
    plant_is_ready,
    plant_ready_at,
    stamp_plant_ready_at,
)
from progression_core import add_progress, check_achievements, credit_xp
from world_modes import effective_pot_capacity, resolve_game_scope
from utils import (
    GROWTH_CYCLES,
    discord_relative_time,
    inv_get,
    inv_take,
    jail_guard,
)


class StrainCatalogView(discord.ui.View):
    def __init__(
        self,
        cog: "Farming",
        owner_id: int,
        *,
        page: int = 0,
        query: str = "",
        timeout: float = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.page = max(0, int(page))
        self.query = str(query or "").strip()
        self.total_pages = 1
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.clear_items()
        previous = discord.ui.Button(
            label="Prev",
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            disabled=self.page <= 0,
        )
        previous.callback = self.previous_page
        self.add_item(previous)

        next_page = discord.ui.Button(
            label="Next",
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.total_pages - 1,
        )
        next_page.callback = self.next_page
        self.add_item(next_page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This strain browser belongs to another player.",
                ephemeral=True,
            )
            return False
        return True

    async def _render(self, interaction: discord.Interaction) -> None:
        embed, total_pages = self.cog.build_strains_embed(
            page=self.page,
            query=self.query,
        )
        self.total_pages = total_pages
        self.page = max(0, min(self.page, self.total_pages - 1))
        self._sync_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def previous_page(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        await self._render(interaction)

    async def next_page(self, interaction: discord.Interaction) -> None:
        self.page = min(max(0, self.total_pages - 1), self.page + 1)
        await self._render(interaction)


class Farming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="plant", aliases=["p", "grow"])
    async def plant(self, ctx, count: int = 1, *, strain_name: str = ""):
        """Plant one or more seeds of one selected strain."""
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, user, "plant"):
            return

        if not strain_name:
            return await ctx.send(
                "🌱 Open **`/game` → Grow** to choose an owned seed and plant it, "
                "or use the shortcut `/plant strain_name:<strain> count:<number>`."
            )

        clean_name = strain_name.lower().replace(" seed", "").strip()
        seed_item_name = f"{clean_name} seed"

        if clean_name not in GROWTH_CYCLES:
            return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `/strains`.")

        try:
            requested = int(count or 1)
        except (TypeError, ValueError):
            requested = 1
        requested = max(1, min(requested, MAX_PLANTS_PER_ACTION))

        strain_info = GROWTH_CYCLES[clean_name]
        world = await self.bot.db.get_world(scope.scope_id)

        plant_error = None
        planted_count = 0
        ready_at = 0.0
        limited_by = None
        async with self.bot.db.lock:
            if int(user.get("level", 1)) < int(strain_info.get("level_req", 1)):
                plant_error = f"🔒 You need Level **{strain_info['level_req']}** to grow this."
            else:
                owned = max(0, inv_get(user, seed_item_name))
                if owned < 1:
                    plant_error = (
                        f"❌ You don't have any **{clean_name.title()} Seeds**!\n"
                        "Open **`/game` → Grow → Seed Shop** to buy one without typing item names."
                    )
                else:
                    max_pots = effective_pot_capacity(user, scope)
                    current_plants = user.setdefault("plants", [])
                    free_slots = max(0, max_pots - len(current_plants))
                    if free_slots <= 0:
                        plant_error = (
                            f"🚫 **No Pots Available!** ({len(current_plants)}/{max_pots})\n"
                            "Harvest plants or buy Pot Upgrades in the shop."
                        )
                    else:
                        target = min(requested, owned, free_slots)
                        if target < requested:
                            if free_slots < requested and free_slots <= owned:
                                limited_by = "empty pots"
                            elif owned < requested:
                                limited_by = "owned seeds"

                        planted_at = time.time()
                        for _ in range(target):
                            if not inv_take(user, seed_item_name, 1):
                                limited_by = "owned seeds"
                                break
                            new_plant = {"strain": clean_name}
                            ready_at = stamp_plant_ready_at(
                                user,
                                world,
                                new_plant,
                                planted_at=planted_at,
                            )
                            initialize_plant_care(
                                new_plant,
                                now=planted_at,
                            )
                            current_plants.append(new_plant)
                            planted_count += 1

                        if planted_count:
                            add_progress(
                                user,
                                "plant",
                                planted_count,
                                user_id=ctx.author.id,
                            )
                            check_achievements(user)
                            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                        else:
                            plant_error = "❌ That seed is no longer available. Try again."

        if plant_error:
            return await ctx.send(plant_error)

        if planted_count == 1:
            planted_line = f"🌱 **Planted:** {clean_name.title()}"
        else:
            planted_line = (
                f"🌱 **Planted:** {planted_count} × {clean_name.title()}"
            )
        lines = [
            planted_line,
            f"⏳ **Ready:** {discord_relative_time(ready_at)}",
        ]
        if planted_count < requested:
            reason = limited_by or "current availability"
            lines.append(
                f"ℹ️ Requested **{requested}** • planted **{planted_count}** "
                f"(limited by {reason})."
            )
        await ctx.send("\n".join(lines))

    @commands.hybrid_command(name="water", aliases=["waterall"])
    async def water(self, ctx):
        """Water growing plants that currently need care."""
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, user, "water"):
            return
        world = await self.bot.db.get_world(scope.scope_id)
        now = time.time()

        watered = 0
        skipped_fresh = 0
        skipped_ready = 0
        no_plants = False
        async with self.bot.db.lock:
            plants = [
                plant
                for plant in user.get("plants", []) or []
                if isinstance(plant, dict)
            ]
            if not plants:
                no_plants = True

            for plant in plants:
                result = water_plant(user, world, plant, now=now)
                if result["watered"]:
                    watered += 1
                elif result["reason"] == "ready":
                    skipped_ready += 1
                else:
                    skipped_fresh += 1

            if watered:
                stats = user.setdefault("stats", {})
                stats["watered"] = max(0, int(stats.get("watered", 0))) + watered
                add_progress(
                    user,
                    "water",
                    watered,
                    user_id=ctx.author.id,
                )
                check_achievements(user)
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        if no_plants:
            return await ctx.send(
                "🌱 You have no growing plants to water."
            )

        if watered <= 0:
            if skipped_ready and not skipped_fresh:
                return await ctx.send(
                    "✂️ Your plants are ready to harvest. They do not need more water."
                )
            return await ctx.send(
                "💧 Your growing plants are still comfortably watered. No care action was needed."
            )

        details = [f"💧 **Watered:** {watered} plant(s)"]
        if skipped_fresh:
            details.append(f"🌿 **Still fresh:** {skipped_fresh}")
        if skipped_ready:
            details.append(f"✂️ **Already ready:** {skipped_ready}")
        details.append(
            "Care affects the **game harvest condition**, not the plant's ready time."
        )
        await ctx.send("\n".join(details))

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

                harvest_now = time.time()
                ready_care = {}
                for plant in plants:
                    if not plant_is_ready(user, world, plant, now=harvest_now):
                        continue
                    label, _care_mult, _score = plant_care_grade(
                        user,
                        world,
                        plant,
                        now=harvest_now,
                    )
                    ready_care[label] = ready_care.get(label, 0) + 1

                outcome = calculate_harvest_outcome(
                    plants,
                    now=harvest_now,
                    strain_configs=GROWTH_CYCLES,
                    grow_time_for_plant=lambda plant: plant_duration_seconds(user, world, plant),
                    yield_multiplier=multiplier,
                    randint=random.randint,
                    yield_multiplier_for_plant=lambda plant: care_multiplier(
                        user,
                        world,
                        plant,
                        now=harvest_now,
                    ),
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
        if ready_care:
            care_summary = " • ".join(
                f"{label}: {count}"
                for label, count in sorted(ready_care.items())
            )
            embed.add_field(
                name="Care Grade",
                value=care_summary,
                inline=False,
            )
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
                description="Empty. Open **`/game` → Grow** to buy, choose, and plant a seed.",
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
            planted_at = float(plant.get("planted_at", 0) or 0)
            ready_at = plant_ready_at(user, world, plant)
            duration = max(1.0, ready_at - planted_at)
            elapsed = max(0.0, now - planted_at)
            percent = min(100, max(0, int((elapsed / duration) * 100)))
            filled = int(percent / 10)
            bar = "🟩" * filled + "⬛" * (10 - filled)

            if plant_is_ready(user, world, plant, now=now):
                status_text = "✅ **READY**"
                ready_count += 1
            else:
                remaining_seconds = max(0, int(ready_at - now))
                minutes, seconds = divmod(remaining_seconds, 60)
                status_text = f"**{percent}%** ({int(minutes)}m {int(seconds)}s left)"

            exact_moisture = inv_get(user, "moisture meter") > 0
            care_text = plant_care_status(
                user,
                world,
                plant,
                now=now,
                exact=exact_moisture,
            )
            lines.append(
                f"**{index}. {strain.title()}**\n"
                f"{bar} {status_text}\n{care_text}"
            )

        embed.description = "\n\n".join(lines)
        needs_water = 0
        for plant in plants:
            if plant_is_ready(user, world, plant, now=now):
                continue
            moisture = plant_moisture(user, world, plant, now=now)
            if moisture is not None and moisture <= CARE_WATER_THRESHOLD:
                needs_water += 1
        footer_parts = []
        if ready_count > 0:
            footer_parts.append(
                f"{ready_count} ready to harvest"
            )
        if needs_water > 0:
            footer_parts.append(
                f"{needs_water} need water"
            )
        if footer_parts:
            embed.set_footer(text=" • ".join(footer_parts))
        await ctx.send(embed=embed)

    STRAIN_PAGE_SIZE = 12

    def build_strains_embed(
        self,
        *,
        page: int = 0,
        query: str = "",
    ) -> tuple[discord.Embed, int]:
        clean_query = str(query or "").strip().lower()
        strains = sorted(
            GROWTH_CYCLES.items(),
            key=lambda item: (
                max(1, int(item[1].get("level_req", 1) or 1)),
                str(item[1].get("display_name", item[0])).lower(),
            ),
        )
        if clean_query:
            strains = [
                (name, data)
                for name, data in strains
                if clean_query in name.lower()
                or clean_query
                in str(data.get("display_name", name)).lower()
                or clean_query
                in " ".join(str(value).lower() for value in data.get("genetics", []))
            ]

        total_pages = max(
            1,
            (len(strains) + self.STRAIN_PAGE_SIZE - 1)
            // self.STRAIN_PAGE_SIZE,
        )
        page = max(0, min(int(page), total_pages - 1))
        start = page * self.STRAIN_PAGE_SIZE
        visible = strains[start : start + self.STRAIN_PAGE_SIZE]

        title = "🧬 Strain Database"
        if clean_query:
            title += f" • {query.strip()[:40]}"
        embed = discord.Embed(
            title=title,
            color=discord.Color.purple(),
            description=(
                f"**{len(strains)}** matching game strain(s) • "
                f"Page **{page + 1}/{total_pages}**\n"
                "Times, yields, and levels are **game balance values**, not real cultivation guidance."
            ),
        )
        for _name, data in visible:
            genetics = "/".join(str(value) for value in data.get("genetics", [])) or "Hybrid"
            embed.add_field(
                name=f"Lv{data['level_req']} {data['display_name']}",
                value=(
                    f"🧬 {genetics}\n"
                    f"⏱️ Game cycle: {int(data['time'] / 60)}m\n"
                    f"📦 Game yield: {data['yield'][0]}-{data['yield'][1]}g"
                ),
                inline=True,
            )
        if not visible:
            embed.add_field(
                name="No matches",
                value="Try a shorter name, genetics type, or clear the query.",
                inline=False,
            )
        embed.set_footer(
            text="Use /strains query:<name or type> to jump to a strain quickly."
        )
        return embed, total_pages

    @commands.hybrid_command(name="strains", aliases=["seeds"])
    async def strains(self, ctx, page: int = 1, *, query: str = ""):
        """Browse the game strain catalog."""
        require_guild_id(ctx)
        page_index = max(0, int(page or 1) - 1)
        embed, total_pages = self.build_strains_embed(
            page=page_index,
            query=query,
        )
        page_index = max(0, min(page_index, total_pages - 1))
        view = StrainCatalogView(
            self,
            ctx.author.id,
            page=page_index,
            query=query,
        )
        view.total_pages = total_pages
        view._sync_buttons()
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Farming(bot))
