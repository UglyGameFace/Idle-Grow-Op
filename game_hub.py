from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any

import discord
from discord.ext import commands

from economy import ShopView
from notification_preferences import NotificationPreferencesView
from onboarding import choose_onboarding_step
from persistence_context import GuildContextRequired, require_guild_id
from plant_lifecycle import plant_is_ready, plant_ready_at
from progression_core import xp_needed_for_level
from utils import GROWTH_CYCLES
from world_modes import resolve_game_scope


logger = logging.getLogger(__name__)

HUB_PAGES = (
    ("home", "Home", "🏠"),
    ("grow", "Grow", "🌱"),
    ("inventory", "Inventory", "🎒"),
    ("market", "Market", "🔨"),
    ("lab", "Lab", "⚗️"),
    ("crime", "Crime", "🕶️"),
    ("progress", "Progress", "📈"),
    ("social", "Social", "👥"),
    ("casino", "Casino", "🎰"),
    ("settings", "Settings", "⚙️"),
)

SAFE_HUB_COMMANDS = frozenset(
    {
        "harvest",
        "status",
        "plant",
        "inventory",
        "sell",
        "process",
        "collect",
        "lab",
        "auction",
        "auction list",
        "bid",
        "heist",
        "launder",
        "heat",
        "heiststats",
        "topheists",
        "growdaily",
        "growquests",
        "growachievements",
        "growlevel",
        "profile",
        "crew",
        "district",
        "leaderboard",
        "casino",
        "casinolb",
        "world-mode",
        "profile-settings",
        "help",
    }
)


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _sum_mapping(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(_positive_int(item) for item in value.values())


def _cash(value: Any) -> str:
    return "$" + f"{_positive_int(value):,}"


class HubInteractionContext:
    """Restricted Context adapter used only by allow-listed player actions."""

    def __init__(
        self,
        bot: commands.Bot,
        interaction: discord.Interaction,
        command: commands.Command,
    ) -> None:
        self.bot = bot
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.command = command
        self.message = interaction.message or SimpleNamespace(
            created_at=interaction.created_at,
            edited_at=None,
        )

    async def send(self, content: str | None = None, **kwargs):
        kwargs["ephemeral"] = True
        if not self.interaction.response.is_done():
            await self.interaction.response.send_message(content=content, **kwargs)
            return await self.interaction.original_response()
        return await self.interaction.followup.send(
            content=content,
            wait=True,
            **kwargs,
        )


class HubPageSelect(discord.ui.Select):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(
            placeholder="Choose a game section…",
            min_values=1,
            max_values=1,
            row=0,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=emoji,
                    default=view.page == key,
                )
                for key, label, emoji in HUB_PAGES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        view.page = self.values[0]
        view.selected_seed = None
        await view.refresh(interaction)


class HubSeedSelect(discord.ui.Select):
    def __init__(self, view: "GameHubView", profile: dict) -> None:
        level = max(1, _positive_int(profile.get("level")) or 1)
        items = profile.get("items")
        items = items if isinstance(items, dict) else {}
        options = []
        for item_name, amount in sorted(items.items()):
            if not str(item_name).endswith(" seed") or _positive_int(amount) <= 0:
                continue
            strain = str(item_name)[:-5].strip().lower()
            config = GROWTH_CYCLES.get(strain)
            if not isinstance(config, dict):
                continue
            required = max(1, _positive_int(config.get("level_req")) or 1)
            if level < required:
                continue
            options.append(
                discord.SelectOption(
                    label=strain.title()[:100],
                    value=strain,
                    description=f"{_positive_int(amount)} seed(s) owned",
                    default=view.selected_seed == strain,
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label="No plantable seeds owned",
                    value="__none__",
                    description="Open Shop to buy a seed.",
                )
            ]
        super().__init__(
            placeholder="Choose a seed to plant…",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        self.view.selected_seed = None if value == "__none__" else value
        await self.view.refresh(interaction)


class HubBidModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="Place Auction Bid")
        self.hub_view = view
        self.auction_id = discord.ui.TextInput(
            label="Auction ID",
            placeholder="Example: 1007",
            max_length=24,
        )
        self.amount = discord.ui.TextInput(
            label="Bid amount",
            placeholder="Example: 2500",
            max_length=20,
        )
        self.add_item(self.auction_id)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", "").replace("$", ""))
        except ValueError:
            return await interaction.response.send_message(
                "❌ Bid amount must be a whole number.",
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                "❌ Bid amount must be positive.",
                ephemeral=True,
            )
        await self.hub_view.run_command(
            interaction,
            "bid",
            auction_id=str(self.auction_id.value).strip(),
            amount=amount,
        )


class HubAuctionListModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="List Item on Auction")
        self.hub_view = view
        self.item_name = discord.ui.TextInput(
            label="Inventory item",
            placeholder="Example: pager",
            max_length=80,
        )
        self.start_price = discord.ui.TextInput(
            label="Starting price",
            placeholder="Example: 1000",
            max_length=20,
        )
        self.buyout = discord.ui.TextInput(
            label="Buyout price (optional)",
            placeholder="0 for no buyout",
            required=False,
            default="0",
            max_length=20,
        )
        self.add_item(self.item_name)
        self.add_item(self.start_price)
        self.add_item(self.buyout)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            start_price = int(
                str(self.start_price.value).replace(",", "").replace("$", "")
            )
            buyout_raw = str(self.buyout.value or "0").replace(",", "").replace("$", "")
            buyout = int(buyout_raw or "0")
        except ValueError:
            return await interaction.response.send_message(
                "❌ Prices must be whole numbers.",
                ephemeral=True,
            )
        await self.hub_view.run_command(
            interaction,
            "auction list",
            item_name=str(self.item_name.value).strip(),
            start_price=start_price,
            buyout=buyout,
        )


class HubLaunderModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="Launder Dirty Cash")
        self.hub_view = view
        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="all or a whole number",
            default="all",
            max_length=20,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.hub_view.run_command(
            interaction,
            "launder",
            amount=str(self.amount.value).strip(),
        )


class HubActionButton(discord.ui.Button):
    def __init__(
        self,
        *,
        action: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
        row: int,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            disabled=disabled,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.handle_action(interaction, self.action)


class GameHubView(discord.ui.View):
    def __init__(
        self,
        cog: "GameHub",
        owner_id: int,
        guild_id: int,
        *,
        page: str = "home",
        timeout: float = 600,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        valid_pages = {key for key, _label, _emoji in HUB_PAGES}
        self.page = page if page in valid_pages else "home"
        self.selected_seed: str | None = None
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This game panel belongs to another player or server.",
                ephemeral=True,
            )
            return False
        return True

    async def state(self):
        return await self.cog.state(self.guild_id, self.owner_id)

    def add_action(
        self,
        action: str,
        label: str,
        emoji: str,
        *,
        row: int,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        disabled: bool = False,
    ) -> None:
        self.add_item(
            HubActionButton(
                action=action,
                label=label,
                emoji=emoji,
                row=row,
                style=style,
                disabled=disabled,
            )
        )

    def rebuild(self, scope, profile: dict, world: dict) -> None:
        del scope, world
        self.clear_items()
        self.add_item(HubPageSelect(self))
        row = 1

        if self.page == "grow":
            self.add_item(HubSeedSelect(self, profile))
            row = 2
            self.add_action(
                "plant",
                "Plant Selected",
                "🌱",
                row=row,
                style=discord.ButtonStyle.success,
                disabled=self.selected_seed is None,
            )
            self.add_action("harvest", "Harvest Ready", "✂️", row=row, style=discord.ButtonStyle.success)
            self.add_action("status", "Garden", "🪴", row=row)
            self.add_action("shop", "Shop", "🛒", row=row)
        elif self.page == "inventory":
            self.add_action("inventory", "Inventory", "🎒", row=row)
            self.add_action("sell_all", "Sell All Flower", "💵", row=row, style=discord.ButtonStyle.success)
            self.add_action("collect", "Collect Lab", "📦", row=row)
            self.add_action("shop", "Shop", "🛒", row=row)
        elif self.page == "market":
            self.add_action("auction", "Browse Auctions", "🔨", row=row)
            self.add_action("bid_modal", "Place Bid", "💰", row=row, style=discord.ButtonStyle.primary)
            self.add_action("list_modal", "List Item", "📤", row=row)
            self.add_action("leaderboard", "Leaderboard", "🏆", row=row)
        elif self.page == "lab":
            self.add_action("lab", "Lab Status", "🧪", row=row)
            self.add_action("process", "Process Menu", "⚗️", row=row)
            self.add_action("collect", "Collect Ready", "📦", row=row)
            self.add_action("shop", "Equipment Shop", "🛒", row=row)
        elif self.page == "crime":
            self.add_action("heist_stealth", "Stealth Heist", "🥷", row=row, style=discord.ButtonStyle.success)
            self.add_action("heist_loud", "Loud Heist", "💥", row=row, style=discord.ButtonStyle.danger)
            self.add_action("heist_con", "Con Job", "🎭", row=row)
            self.add_action("launder_modal", "Launder Cash", "🧼", row=row)
            self.add_action("heat", "Heat", "🔥", row=row)
            self.add_action("heiststats", "Heist Stats", "📊", row=2)
            self.add_action("topheists", "Top Heists", "🏆", row=2)
        elif self.page == "progress":
            self.add_action("daily", "Daily Reward", "☀️", row=row, style=discord.ButtonStyle.success)
            self.add_action("quests", "Quests", "📜", row=row)
            self.add_action("achievements", "Achievements", "🏆", row=row)
            self.add_action("level", "Level & XP", "📈", row=row)
        elif self.page == "social":
            self.add_action("profile", "Profile", "👤", row=row)
            self.add_action("crew", "Crew", "👥", row=row)
            self.add_action("district", "District", "🏙️", row=row)
            self.add_action("leaderboard", "Leaderboard", "🏆", row=row)
        elif self.page == "casino":
            self.add_action("casino", "Casino Menu", "🎰", row=row)
            self.add_action("casinolb", "Casino Rankings", "🏆", row=row)
        elif self.page == "settings":
            self.add_action("notifications", "Notifications", "📟", row=row)
            self.add_action("world-mode", "World Mode", "🌍", row=row)
            self.add_action("profile-settings", "Profile & Privacy", "🪪", row=row)
            self.add_action("help", "Help", "❓", row=row)
        else:
            self.add_action("shop", "Shop", "🛒", row=row, style=discord.ButtonStyle.primary)
            self.add_action("harvest", "Harvest", "✂️", row=row, style=discord.ButtonStyle.success)
            self.add_action("daily", "Daily", "☀️", row=row, style=discord.ButtonStyle.success)
            self.add_action("profile", "Profile", "👤", row=row)
            self.add_action("inventory", "Inventory", "🎒", row=row)

        self.add_action("refresh", "Refresh", "🔄", row=4)
        self.add_action("close", "Close", "✖️", row=4, style=discord.ButtonStyle.danger)

    async def refresh(self, interaction: discord.Interaction) -> None:
        scope, profile, world = await self.state()
        self.rebuild(scope, profile, world)
        await interaction.response.edit_message(
            embed=self.cog.build_embed(
                scope,
                profile,
                world,
                page=self.page,
                selected_seed=self.selected_seed,
            ),
            view=self,
        )

    async def refresh_original(self, interaction: discord.Interaction) -> None:
        scope, profile, world = await self.state()
        self.rebuild(scope, profile, world)
        message = interaction.message or self.message
        if message is not None:
            await message.edit(
                embed=self.cog.build_embed(
                    scope,
                    profile,
                    world,
                    page=self.page,
                    selected_seed=self.selected_seed,
                ),
                view=self,
            )

    async def open_shop(self, interaction: discord.Interaction) -> None:
        economy = self.cog.bot.get_cog("Economy")
        if economy is None:
            return await interaction.response.send_message(
                "⚠️ Shop is temporarily unavailable.",
                ephemeral=True,
            )
        scope, profile = await economy._profile_for(self.guild_id, self.owner_id)
        view = ShopView(economy, self.owner_id, self.guild_id)
        view.rebuild(profile)
        await interaction.response.send_message(
            embed=economy.build_shop_embed(scope, profile),
            view=view,
            ephemeral=True,
        )

    async def open_notifications(self, interaction: discord.Interaction) -> None:
        notifications = self.cog.bot.get_cog("NotificationPreferencesCog")
        if notifications is None:
            return await interaction.response.send_message(
                "⚠️ Notification settings are temporarily unavailable.",
                ephemeral=True,
            )
        scope, preferences = await notifications.get_state(self.guild_id, self.owner_id)
        view = NotificationPreferencesView(
            notifications,
            self.owner_id,
            self.guild_id,
        )
        await interaction.response.send_message(
            embed=notifications.build_panel(scope, preferences),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def run_command(
        self,
        interaction: discord.Interaction,
        command_name: str,
        **kwargs,
    ) -> None:
        if command_name not in SAFE_HUB_COMMANDS:
            return await interaction.response.send_message(
                "❌ That action is not available from the game panel.",
                ephemeral=True,
            )
        command = self.cog.bot.get_command(command_name)
        if command is None or command.cog is None:
            return await interaction.response.send_message(
                f"⚠️ /{command_name} is temporarily unavailable.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        ctx = HubInteractionContext(self.cog.bot, interaction, command)
        try:
            if not await command.can_run(ctx):
                raise commands.CheckFailure("command check failed")
            command._prepare_cooldowns(ctx)
            await command.callback(command.cog, ctx, **kwargs)
        except commands.CommandOnCooldown as exc:
            await interaction.followup.send(
                f"⏳ Try again in **{exc.retry_after:.1f}s**.",
                ephemeral=True,
            )
            return
        except commands.CheckFailure:
            await interaction.followup.send(
                "❌ You cannot use that action here.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.exception(
                "Game hub action failed command=%s guild=%s user=%s",
                command_name,
                interaction.guild_id,
                interaction.user.id,
            )
            reporter = getattr(self.cog.bot, "report_command_error", None)
            if callable(reporter):
                await reporter(
                    guild_id=interaction.guild_id,
                    title="Game hub action failure",
                    description=(
                        f"command={command_name} user={interaction.user.id} "
                        f"error={type(exc).__name__}: {exc}"
                    ),
                )
            await interaction.followup.send(
                "❌ Something went wrong running that action. The error was recorded.",
                ephemeral=True,
            )
            return
        await self.refresh_original(interaction)

    async def handle_action(self, interaction: discord.Interaction, action: str) -> None:
        if action == "refresh":
            return await self.refresh(interaction)
        if action == "close":
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()
            return
        if action == "shop":
            return await self.open_shop(interaction)
        if action == "bid_modal":
            return await interaction.response.send_modal(HubBidModal(self))
        if action == "list_modal":
            return await interaction.response.send_modal(HubAuctionListModal(self))
        if action == "launder_modal":
            return await interaction.response.send_modal(HubLaunderModal(self))
        if action == "heist_stealth":
            return await self.run_command(interaction, "heist", mode="solo", arg="stealth")
        if action == "heist_loud":
            return await self.run_command(interaction, "heist", mode="solo", arg="loud")
        if action == "heist_con":
            return await self.run_command(interaction, "heist", mode="solo", arg="con")
        if action == "notifications":
            return await self.open_notifications(interaction)
        if action == "plant":
            if not self.selected_seed:
                return await interaction.response.send_message(
                    "🌱 Choose one of your owned seeds first.",
                    ephemeral=True,
                )
            return await self.run_command(interaction, "plant", strain_name=self.selected_seed)
        if action == "sell_all":
            return await self.run_command(
                interaction,
                "sell",
                amount="all",
                strain_name=None,
            )

        command_name = {
            "harvest": "harvest",
            "status": "status",
            "inventory": "inventory",
            "collect": "collect",
            "lab": "lab",
            "process": "process",
            "auction": "auction",
            "heat": "heat",
            "heiststats": "heiststats",
            "topheists": "topheists",
            "daily": "growdaily",
            "quests": "growquests",
            "achievements": "growachievements",
            "level": "growlevel",
            "profile": "profile",
            "crew": "crew",
            "district": "district",
            "leaderboard": "leaderboard",
            "casino": "casino",
            "casinolb": "casinolb",
            "world-mode": "world-mode",
            "profile-settings": "profile-settings",
            "help": "help",
        }.get(action)
        if command_name is None:
            return await interaction.response.send_message(
                "⚠️ That game-panel action is not configured.",
                ephemeral=True,
            )
        await self.run_command(interaction, command_name)

    async def on_timeout(self) -> None:
        self.stop()


class GameHub(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx) -> bool:
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    async def state(self, guild_id: int, user_id: int):
        scope = await resolve_game_scope(self.bot.db, int(guild_id), int(user_id))
        profile = await self.bot.db.get_profile(scope.scope_id, int(user_id))
        world = await self.bot.db.get_world(scope.scope_id)
        return scope, profile, world

    def build_embed(
        self,
        scope,
        profile: dict,
        world: dict,
        *,
        page: str = "home",
        selected_seed: str | None = None,
    ) -> discord.Embed:
        now = time.time()
        plants = [
            plant
            for plant in profile.get("plants", []) or []
            if isinstance(plant, dict)
        ]
        ready_count = sum(
            1
            for plant in plants
            if plant_is_ready(profile, world, plant, now=now)
        )
        wallet = _positive_int(profile.get("grams"))
        dirty_cash = _positive_int(profile.get("dirty_cash"))
        level = max(1, _positive_int(profile.get("level")) or 1)
        xp = _positive_int(profile.get("xp"))
        needed = max(1, int(xp_needed_for_level(level)))
        flower = _sum_mapping(profile.get("flower_stash"))
        concentrates = _sum_mapping(profile.get("concentrates"))

        embed = discord.Embed(
            title={
                "home": "🌿 Idle Grow Command Center",
                "grow": "🌱 Grow Room",
                "inventory": "🎒 Inventory & Sales",
                "market": "🔨 Market & Auctions",
                "lab": "⚗️ Concentrate Lab",
                "crime": "🕶️ Crime",
                "progress": "📈 Progression",
                "social": "👥 Social & World",
                "casino": "🎰 Casino",
                "settings": "⚙️ Player Settings",
            }.get(page, "🌿 Idle Grow Command Center"),
            color=discord.Color.green(),
        )
        embed.description = (
            f"**Active save:** {scope.emoji} {scope.label}\n"
            f"💵 **Cash:** {_cash(wallet)} • ⭐ **Lv {level}** • "
            f"🌿 **{len(plants)} plants ({ready_count} ready)**"
        )

        if page == "grow":
            lines = []
            for index, plant in enumerate(plants[:10], start=1):
                strain = str(plant.get("strain", "unknown")).title()
                status = (
                    "✅ READY"
                    if plant_is_ready(profile, world, plant, now=now)
                    else f"<t:{int(plant_ready_at(profile, world, plant))}:R>"
                )
                lines.append(f"**{index}. {strain}** • {status}")
            embed.add_field(
                name="Your Garden",
                value="\n".join(lines)
                or "No plants growing. Buy a seed, choose it below, and plant.",
                inline=False,
            )
            embed.add_field(
                name="Next Plant",
                value=(
                    f"Selected seed: **{selected_seed.title()}**"
                    if selected_seed
                    else "Choose one of your owned seeds below."
                ),
                inline=False,
            )
        elif page == "inventory":
            items = profile.get("items")
            items = items if isinstance(items, dict) else {}
            item_types = sum(1 for amount in items.values() if _positive_int(amount) > 0)
            embed.add_field(
                name="Stash",
                value=(
                    f"🎒 **{item_types} item types**\n"
                    f"🌿 **{flower:,}g flower**\n"
                    f"⚗️ **{concentrates:,}g concentrates**\n"
                    f"🧼 **{_cash(dirty_cash)} dirty cash**"
                ),
                inline=False,
            )
            embed.add_field(
                name="Quick Actions",
                value="Inspect inventory, sell all flower, collect finished lab work, or open the shop.",
                inline=False,
            )
        elif page == "market":
            auctions = world.get("auctions")
            auctions = auctions if isinstance(auctions, dict) else {}
            lines = []
            for auction_id, auction in list(auctions.items())[:5]:
                if not isinstance(auction, dict):
                    continue
                lines.append(
                    f"**{auction_id}** • {str(auction.get('item_name', 'item')).title()} • "
                    f"{_cash(auction.get('current_bid', 0))}"
                )
            embed.add_field(
                name="Auction House",
                value="\n".join(lines) or "No active auctions.",
                inline=False,
            )
            embed.add_field(
                name="Controls",
                value="Browse full listings, place a bid, or list an inventory item without typing command arguments.",
                inline=False,
            )
        elif page == "lab":
            queue = [
                item
                for item in profile.get("processing_queue", []) or []
                if isinstance(item, dict)
            ]
            completed = sum(
                1
                for item in queue
                if now >= float(item.get("finish_time", now + 1))
            )
            embed.add_field(
                name="Extraction Queue",
                value=(
                    f"⚗️ **{len(queue)} active batch(es)** • "
                    f"📦 **{completed} ready to collect**\n"
                    f"🌿 Flower available: **{flower:,}g**"
                ),
                inline=False,
            )
            embed.add_field(
                name="How it works",
                value="Open Process Menu to see recipes and requirements. Collect Ready claims every completed batch.",
                inline=False,
            )
        elif page == "crime":
            stats = profile.get("stats")
            stats = stats if isinstance(stats, dict) else {}
            embed.add_field(name="Heat", value=f"**{_positive_int(profile.get('heat'))}%**", inline=True)
            embed.add_field(name="Dirty Cash", value=_cash(dirty_cash), inline=True)
            embed.add_field(
                name="Record",
                value=(
                    f"Heists won: **{_positive_int(stats.get('heists_won'))}**\n"
                    f"Robberies: **{_positive_int(stats.get('steals'))}**"
                ),
                inline=True,
            )
            embed.add_field(
                name="Jobs",
                value="Choose a solo plan directly. Launder opens a private amount form. Crew/raid actions remain protected by their multiplayer rules.",
                inline=False,
            )
        elif page == "progress":
            quests = [
                quest
                for quest in profile.get("daily_quests", []) or []
                if isinstance(quest, dict)
            ]
            completed = sum(1 for quest in quests if quest.get("completed"))
            achievements = len(profile.get("achievements", []) or [])
            embed.add_field(name="Level", value=f"**{level}** • **{xp:,}/{needed:,} XP**", inline=True)
            embed.add_field(name="Daily Quests", value=f"**{completed}/{len(quests)} completed**", inline=True)
            embed.add_field(name="Achievements", value=f"**{achievements} unlocked**", inline=True)
        elif page == "social":
            crew_name = "None"
            crew_id = profile.get("crew_id")
            crews = world.get("crews")
            if crew_id and isinstance(crews, dict):
                crew = crews.get(str(crew_id))
                if isinstance(crew, dict):
                    crew_name = str(crew.get("name") or "Unknown")
            district = world.get("district")
            district_owner = "None"
            if isinstance(district, dict) and district.get("owner_crew_id"):
                district_owner = str(district.get("owner_name") or "Unknown")
            embed.add_field(name="Crew", value=crew_name, inline=True)
            embed.add_field(name="District Owner", value=district_owner, inline=True)
            embed.add_field(
                name="Multiplayer",
                value="Enabled" if scope.multiplayer else "Unavailable in this save",
                inline=True,
            )
        elif page == "casino":
            stats = profile.get("stats")
            stats = stats if isinstance(stats, dict) else {}
            embed.add_field(name="Bankroll", value=_cash(wallet), inline=True)
            embed.add_field(
                name="Tracked Profit",
                value=_cash(stats.get("casino_total_profit", 0)),
                inline=True,
            )
            embed.add_field(
                name="Safety",
                value="The command center never places a wager automatically. Open the Casino Menu and choose a game yourself.",
                inline=False,
            )
        elif page == "settings":
            settings = profile.get("settings")
            settings = settings if isinstance(settings, dict) else {}
            privacy = profile.get("profile_signature_privacy")
            privacy = privacy if isinstance(privacy, dict) else {}
            embed.add_field(
                name="Ready-work Alerts",
                value="Enabled" if settings.get("notifications", True) is not False else "Disabled",
                inline=True,
            )
            embed.add_field(
                name="Profile Signature",
                value="Disabled" if privacy.get("signature_disabled") else "Enabled",
                inline=True,
            )
            embed.add_field(name="Save", value=f"{scope.emoji} {scope.label}", inline=True)
            embed.add_field(
                name="Panels",
                value="Notifications, World Mode, and Profile & Privacy open their full interactive controls.",
                inline=False,
            )
        else:
            step = choose_onboarding_step(scope, profile, world, now=now)
            embed.add_field(
                name=f"{step.emoji} Recommended Next Move",
                value=f"**{step.title}**\n{step.reason}",
                inline=False,
            )
            embed.add_field(
                name="Operation",
                value=(
                    f"🌦️ **Weather:** {str(world.get('weather') or 'Normal')}\n"
                    f"🌿 **Flower:** {flower:,}g • ⚗️ **Concentrates:** {concentrates:,}g\n"
                    f"🧼 **Dirty cash:** {_cash(dirty_cash)}"
                ),
                inline=False,
            )
            embed.add_field(
                name="Play from this panel",
                value="Use the section menu and buttons below. Slash commands remain available, but you should not need to memorize them.",
                inline=False,
            )

        embed.set_footer(
            text="Private player panel • refresh anytime • expires after 10 minutes"
        )
        return embed

    async def send_hub_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return await interaction.response.send_message(
                "❌ The game menu can only be used inside a server.",
                ephemeral=True,
            )
        scope, profile, world = await self.state(
            interaction.guild_id,
            interaction.user.id,
        )
        view = GameHubView(self, interaction.user.id, interaction.guild_id)
        view.rebuild(scope, profile, world)
        await interaction.response.send_message(
            embed=self.build_embed(scope, profile, world),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    @commands.hybrid_command(name="game", aliases=["menu", "play"])
    async def game(self, ctx):
        """Open the private all-in-one player command center."""
        guild_id = require_guild_id(ctx)
        scope, profile, world = await self.state(guild_id, ctx.author.id)
        view = GameHubView(self, ctx.author.id, guild_id)
        view.rebuild(scope, profile, world)
        message = await ctx.send(
            embed=self.build_embed(scope, profile, world),
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message


async def setup(bot):
    await bot.add_cog(GameHub(bot))
