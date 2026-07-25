from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import GROWTH_CYCLES, SHOP_ITEMS, get_plant_grow_time, inv_get
from world_modes import GameScope, POLICY_CHOICE, normalize_world_mode_config, resolve_game_scope


STARTER_SEED = "schwag seed"
STARTER_STRAIN = "schwag"
STARTER_SEED_COST = int(SHOP_ITEMS[STARTER_SEED]["cost"])


@dataclass(frozen=True, slots=True)
class OnboardingStep:
    key: str
    emoji: str
    title: str
    command: str
    reason: str


def _positive_total(values: Any) -> int:
    if not isinstance(values, dict):
        return 0
    total = 0
    for value in values.values():
        try:
            total += max(0, int(value))
        except (TypeError, ValueError):
            continue
    return total


def _owned_plantable_seed(profile: dict[str, Any]) -> str | None:
    level = max(1, int(profile.get("level", 1) or 1))
    unlocked = {
        str(value).strip().lower()
        for value in profile.get("unlocked_strains", [])
        if str(value).strip()
    }
    candidates: list[tuple[int, str]] = []
    for strain, data in GROWTH_CYCLES.items():
        if int(data.get("level_req", 1)) > level:
            continue
        if unlocked and strain not in unlocked:
            continue
        seed_name = f"{strain} seed"
        if inv_get(profile, seed_name) <= 0:
            continue
        cost = int(SHOP_ITEMS.get(seed_name, {}).get("cost", 0) or 0)
        candidates.append((cost, strain))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def _ready_plant_count(profile: dict[str, Any], world: dict[str, Any], now: float) -> int:
    ready = 0
    for plant in profile.get("plants", []) or []:
        if not isinstance(plant, dict):
            continue
        planted_at = float(plant.get("planted_at", now) or now)
        if now - planted_at >= get_plant_grow_time(profile, world, plant):
            ready += 1
    return ready


def _water_due(profile: dict[str, Any], now: float) -> bool:
    for plant in profile.get("plants", []) or []:
        if not isinstance(plant, dict):
            continue
        last_watered = float(plant.get("last_watered", 0) or 0)
        if now - last_watered > 300:
            return True
    return False


def _completed_batch_count(profile: dict[str, Any], now: float) -> int:
    return sum(
        1
        for item in profile.get("processing_queue", []) or []
        if isinstance(item, dict) and now >= float(item.get("finish_time", now + 1))
    )


def choose_onboarding_step(
    scope: GameScope,
    profile: dict[str, Any],
    world: dict[str, Any],
    *,
    now: float | None = None,
) -> OnboardingStep:
    current_time = time.time() if now is None else float(now)

    if scope.policy == POLICY_CHOICE and not scope.selection_explicit:
        return OnboardingStep(
            "world_mode",
            "🌍",
            "Choose which save you want to grow in",
            "/world-mode",
            "This server uses Player Choice. Solo and Open World progress are separate, so choose before building your operation.",
        )

    flower_total = _positive_total(profile.get("flower_stash"))
    if flower_total:
        return OnboardingStep(
            "sell",
            "🤝",
            "Turn your harvested flower into cash",
            "/sell amount:all",
            f"You have {flower_total:,}g of flower waiting in this save. Sale value follows the current market.",
        )

    ready_plants = _ready_plant_count(profile, world, current_time)
    if ready_plants:
        return OnboardingStep(
            "harvest",
            "✂️",
            "Harvest your ready plants",
            "/harvest",
            f"{ready_plants} plant(s) are ready. Harvesting moves flower into your stash; it does not pay cash until you sell it.",
        )

    completed_batches = _completed_batch_count(profile, current_time)
    if completed_batches:
        return OnboardingStep(
            "collect",
            "📦",
            "Collect your completed lab work",
            "/collect",
            f"{completed_batches} lab batch(es) are finished and waiting in this active save.",
        )

    plants = [item for item in profile.get("plants", []) or [] if isinstance(item, dict)]
    if plants:
        if _water_due(profile, current_time):
            return OnboardingStep(
                "water",
                "💧",
                "Water the plants that are ready for attention",
                "/water",
                "At least one growing plant can be watered. Use `/status` afterward to see progress and remaining time.",
            )
        return OnboardingStep(
            "status",
            "⏳",
            "Check your garden while it grows",
            "/status",
            "Your plants are still growing. Weather and equipment can change the timer, so the live garden view is the source of truth.",
        )

    owned_seed = _owned_plantable_seed(profile)
    if owned_seed:
        return OnboardingStep(
            "plant",
            "🌱",
            f"Plant your {owned_seed.title()} seed",
            f"/plant strain_name:{owned_seed}",
            "You already own a seed that your current level can grow, and at least one pot is empty.",
        )

    wallet = max(0, int(profile.get("grams", 0) or 0))
    if wallet >= STARTER_SEED_COST:
        return OnboardingStep(
            "buy_seed",
            "🛒",
            "Buy your first inexpensive seed",
            f"/buy item_name:{STARTER_SEED}",
            f"A {STARTER_SEED.title()} costs ${STARTER_SEED_COST:,}, grows quickly, and is available at Level 1.",
        )

    return OnboardingStep(
        "daily",
        "☀️",
        "Rebuild your starter cash",
        "/growdaily",
        f"You need at least ${STARTER_SEED_COST:,} for the cheapest seed. Claim the daily reward, then check `/growquests` for more progress.",
    )


class OnboardingView(discord.ui.View):
    def __init__(
        self,
        cog: "Onboarding",
        owner_id: int,
        guild_id: int,
        *,
        timeout: float = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.message: discord.Message | discord.WebhookMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This guide belongs to another player or server.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _edit(self, interaction: discord.Interaction, embed: discord.Embed) -> None:
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next Step", emoji="🧭", style=discord.ButtonStyle.success, row=0)
    async def next_step(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._edit(
            interaction,
            await self.cog.build_start_embed(self.guild_id, self.owner_id),
        )

    @discord.ui.button(label="Grow Loop", emoji="🌱", style=discord.ButtonStyle.primary, row=0)
    async def grow_loop(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._edit(interaction, self.cog.build_grow_loop_embed())

    @discord.ui.button(label="Progression", emoji="📈", style=discord.ButtonStyle.secondary, row=0)
    async def progression(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._edit(interaction, self.cog.build_progression_embed())

    @discord.ui.button(label="World Modes", emoji="🌍", style=discord.ButtonStyle.secondary, row=0)
    async def world_modes(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._edit(
            interaction,
            await self.cog.build_world_modes_embed(self.guild_id, self.owner_id),
        )

    @discord.ui.button(label="Server Setup", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def server_setup(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._edit(interaction, self.cog.build_server_setup_embed())


class Onboarding(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def onboarding_state(
        self,
        guild_id: int,
        user_id: int,
    ) -> tuple[GameScope, dict[str, Any], dict[str, Any]]:
        scope = await resolve_game_scope(self.bot.db, guild_id, user_id)
        profile = await self.bot.db.get_profile(scope.scope_id, user_id)
        world = await self.bot.db.get_world(scope.scope_id)
        return scope, profile, world

    async def build_start_embed(self, guild_id: int, user_id: int) -> discord.Embed:
        scope, profile, world = await self.onboarding_state(guild_id, user_id)
        step = choose_onboarding_step(scope, profile, world)
        wallet = max(0, int(profile.get("grams", 0) or 0))
        plants = len([item for item in profile.get("plants", []) or [] if isinstance(item, dict)])
        flower = _positive_total(profile.get("flower_stash"))

        embed = discord.Embed(
            title=f"{step.emoji} Your Next Move",
            description=(
                f"**Active save:** {scope.emoji} {scope.label}\n"
                f"**Wallet:** ${wallet:,} • **Plants:** {plants} • **Flower:** {flower:,}g"
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name=step.title,
            value=f"Run **`{step.command}`**\n{step.reason}",
            inline=False,
        )
        embed.add_field(
            name="The money loop",
            value="Buy a seed → plant → tend/check → harvest → sell → upgrade and repeat.",
            inline=False,
        )
        embed.add_field(
            name="Easy bonuses",
            value="Use `/growdaily` and `/growquests`. Use `/notifications` to control ready-work DMs for this save.",
            inline=False,
        )
        embed.set_footer(text="This guide only reads your save. It never spends, grants, moves, or resets anything.")
        return embed

    @staticmethod
    def build_grow_loop_embed() -> discord.Embed:
        embed = discord.Embed(
            title="🌱 First Grow: Exact Steps",
            description="A new profile starts with $500, three empty pots, and no seeds.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="1. Buy a Level 1 seed",
            value=f"`/buy item_name:{STARTER_SEED}` — costs ${STARTER_SEED_COST:,}.",
            inline=False,
        )
        embed.add_field(
            name="2. Plant it",
            value=f"`/plant strain_name:{STARTER_STRAIN}`",
            inline=False,
        )
        embed.add_field(
            name="3. Watch and tend it",
            value="`/status` shows the live timer. `/water` waters eligible plants. Weather and equipment can change growth speed.",
            inline=False,
        )
        embed.add_field(
            name="4. Harvest, then sell",
            value="`/harvest` moves ready flower into your stash. `/sell amount:all` converts that flower into cash at the current market value.",
            inline=False,
        )
        embed.set_footer(text="Schwag has a five-minute base grow time before weather and other modifiers.")
        return embed

    @staticmethod
    def build_progression_embed() -> discord.Embed:
        embed = discord.Embed(
            title="📈 Grow Beyond the First Sale",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Daily progress",
            value="`/growdaily` claims cash and XP. `/growquests` shows daily objectives.",
            inline=False,
        )
        embed.add_field(
            name="Track the operation",
            value="`/profile`, `/inventory`, `/balance`, `/growlevel`, `/ready`, and `/cooldowns`.",
            inline=False,
        )
        embed.add_field(
            name="Lab expansion",
            value="After you have flower and the required level/tools, use `/process` and `/collect`. It is not required for your first grow.",
            inline=False,
        )
        embed.add_field(
            name="Private alerts",
            value="`/notifications` controls plant-ready and lab-ready DMs for the active save.",
            inline=False,
        )
        return embed

    async def build_world_modes_embed(self, guild_id: int, user_id: int) -> discord.Embed:
        scope, _profile, _world = await self.onboarding_state(guild_id, user_id)
        guild_world = await self.bot.db.get_world(guild_id)
        config = normalize_world_mode_config(guild_world)
        embed = discord.Embed(
            title="🌍 Where Your Progress Lives",
            description=f"**Current active save:** {scope.emoji} {scope.label}",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="🔒 Solo Grow",
            value="Private progress with no player value exchange and lower active grow/lab ceilings.",
            inline=False,
        )
        embed.add_field(
            name="🌍 Open World",
            value="One shared cross-server economy for trading, auctions, crews, raids, territory, and competition.",
            inline=False,
        )
        embed.add_field(
            name="🏙️ Current Server World",
            value="Guild-local multiplayer compatibility for communities that already used the old shared server save.",
            inline=False,
        )
        if config["policy"] == POLICY_CHOICE:
            message = "This server lets you choose. Use `/world-mode`; Solo and Open saves never mix, and later switches have a seven-day cooldown."
        else:
            message = "This server chooses the policy. `/world-mode` shows your active save and the consequences."
        embed.add_field(name="What to do here", value=message, inline=False)
        return embed

    @staticmethod
    def build_server_setup_embed() -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ Server Owner Launch Guide",
            description="Players do not need setup access. Server owners and Manage Server users can run `/setup`.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Recommended minimum",
            value="Choose a game channel and review World Mode. Everything else is optional and can be configured later.",
            inline=False,
        )
        embed.add_field(
            name="Optional systems",
            value="Announcements and ping role, error logging, Sesh, AI, profile signatures, and notification guidance.",
            inline=False,
        )
        embed.add_field(
            name="Player launch commands",
            value="Share `/start` for a tailored next move and `/help` for the compact command map.",
            inline=False,
        )
        embed.set_footer(text="Setup never requires copied Discord IDs or environment edits.")
        return embed

    @staticmethod
    def build_help_embed() -> discord.Embed:
        embed = discord.Embed(
            title="🌿 Idle Grow Help",
            description="Use `/start` for a next step based on your real active save.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="🌱 Core grow loop",
            value="`/shop` • `/buy` • `/plant` • `/status` • `/water` • `/harvest` • `/sell`",
            inline=False,
        )
        embed.add_field(
            name="💰 Wallet and inventory",
            value="`/balance` • `/inventory` • `/profile` • `/quick` • `/ready` • `/cooldowns`",
            inline=False,
        )
        embed.add_field(
            name="📈 Progression",
            value="`/growdaily` • `/growquests` • `/growlevel` • `/growachievements` • `/notifications`",
            inline=False,
        )
        embed.add_field(
            name="⚗️ Lab and expansion",
            value="`/process` • `/collect` • `/lab` — requires flower, levels, and sometimes equipment.",
            inline=False,
        )
        embed.add_field(
            name="🌍 Modes and multiplayer",
            value="`/world-mode` explains the active save. Transfers, shared leaderboards, auctions, crews, raids, and territory require a multiplayer mode.",
            inline=False,
        )
        embed.add_field(
            name="🛠️ Server managers",
            value="`/setup` configures the server. Ordinary players do not need Manage Server.",
            inline=False,
        )
        return embed

    async def _send_guide(self, ctx: commands.Context, embed: discord.Embed) -> None:
        guild_id = ctx.guild.id if ctx.guild is not None else None
        if guild_id is None:
            await ctx.send("❌ Idle Grow guides can only be opened inside a server.")
            return
        view = OnboardingView(self, ctx.author.id, guild_id)
        message = await ctx.send(
            embed=embed,
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message

    @commands.hybrid_command(
        name="start",
        aliases=["guide", "tutorial"],
        description="Show your next useful Idle Grow action",
    )
    @app_commands.guild_only()
    @commands.guild_only()
    async def start(self, ctx: commands.Context) -> None:
        await self._send_guide(
            ctx,
            await self.build_start_embed(ctx.guild.id, ctx.author.id),
        )

    @commands.hybrid_command(
        name="help",
        aliases=["commands"],
        description="Show the Idle Grow command guide",
    )
    @app_commands.guild_only()
    @commands.guild_only()
    async def help(self, ctx: commands.Context) -> None:
        await self._send_guide(ctx, self.build_help_embed())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Onboarding(bot))
