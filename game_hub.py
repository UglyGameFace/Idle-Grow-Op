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
from utils import CONCENTRATE_TYPES, GROWTH_CYCLES
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

CASINO_GAMES = (
    ("slots", "Slots", "🎰"),
    ("coinflip", "Coinflip", "🪙"),
    ("blackjack", "Blackjack", "🃏"),
    ("roulette", "Roulette", "🎡"),
    ("dice", "Dice", "🎲"),
    ("hilo", "HiLo", "📈"),
    ("rps", "Rock Paper Scissors", "✊"),
    ("cups", "Cups", "🥤"),
    ("crash", "Crash", "🚀"),
    ("wheel", "Wheel", "🎯"),
    ("keno", "Keno", "🔢"),
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
        "steal",
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
        "crew create",
        "crew join",
        "crew leave",
        "crew info",
        "crew deposit",
        "crew war",
        "district",
        "leaderboard",
        "casino",
        "casinolb",
        "coinflip",
        "slots",
        "dice",
        "hilo",
        "rps",
        "cups",
        "keno",
        "crash",
        "wheel",
        "blackjack",
        "roulette",
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


def _keno_bet_token(value: str) -> str:
    """Prevent small numeric Keno wagers from being parsed as number picks."""
    raw = str(value or "").strip()
    numeric = raw.replace(",", "").lstrip("$")
    return f"${numeric}" if numeric.isdigit() else raw


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
        view.selected_concentrate = None
        view.selected_steal_target = None
        view.selected_casino_game = None
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


class HubConcentrateSelect(discord.ui.Select):
    def __init__(self, view: "GameHubView", profile: dict) -> None:
        level = max(1, _positive_int(profile.get("level")) or 1)
        options = []
        for name, data in CONCENTRATE_TYPES.items():
            required_level = max(1, _positive_int(data.get("level_req")) or 1)
            required_item = str(data.get("req_item") or "").strip()
            status = f"Lv {required_level}"
            if required_item:
                status += f" • needs {required_item.title()}"
            if level < required_level:
                status = f"Locked • {status}"
            options.append(
                discord.SelectOption(
                    label=name.title()[:100],
                    value=name,
                    description=status[:100],
                    default=view.selected_concentrate == name,
                )
            )
        super().__init__(
            placeholder="Choose a concentrate to process…",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected_concentrate = self.values[0]
        await self.view.refresh(interaction)


class HubProcessModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView", concentrate_type: str) -> None:
        super().__init__(title=f"Process {concentrate_type.title()}")
        self.hub_view = view
        self.concentrate_type = concentrate_type
        self.amount = discord.ui.TextInput(
            label="Output amount (grams)",
            placeholder="Example: 5",
            default="1",
            max_length=12,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).strip().replace(",", "")
        try:
            amount = int(raw)
        except ValueError:
            return await interaction.response.send_message(
                "❌ Amount must be a whole number.",
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                "❌ Amount must be positive.",
                ephemeral=True,
            )
        await self.hub_view.run_command(
            interaction,
            "process",
            concentrate_type=self.concentrate_type,
            amount=str(amount),
        )


class HubCrewCreateModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="Create Crew")
        self.hub_view = view
        self.name_input = discord.ui.TextInput(
            label="Crew name",
            placeholder="Up to 50 characters",
            max_length=50,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.hub_view.run_command(
            interaction,
            "crew create",
            name=str(self.name_input.value).strip(),
        )


class HubCrewJoinModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="Join Crew")
        self.hub_view = view
        self.crew_id = discord.ui.TextInput(
            label="Crew ID",
            placeholder="Example: 48219",
            max_length=24,
        )
        self.add_item(self.crew_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.hub_view.run_command(
            interaction,
            "crew join",
            crew_id=str(self.crew_id.value).strip(),
        )


class HubCrewDepositModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(title="Deposit to Crew Bank")
        self.hub_view = view
        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="Example: 5000",
            max_length=20,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).strip().replace(",", "").replace("$", "")
        try:
            amount = int(raw)
        except ValueError:
            return await interaction.response.send_message(
                "❌ Deposit must be a whole number.",
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                "❌ Deposit must be positive.",
                ephemeral=True,
            )
        await self.hub_view.run_command(
            interaction,
            "crew deposit",
            amount=amount,
        )


class HubStealTargetSelect(discord.ui.UserSelect):
    def __init__(self, view: "GameHubView", *, disabled: bool = False) -> None:
        super().__init__(
            placeholder="Choose a player to rob…",
            min_values=1,
            max_values=1,
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected_steal_target = self.values[0]
        await self.view.refresh(interaction)


class HubCasinoGameSelect(discord.ui.Select):
    def __init__(self, view: "GameHubView") -> None:
        super().__init__(
            placeholder="Choose a casino game…",
            min_values=1,
            max_values=1,
            row=1,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=emoji,
                    default=view.selected_casino_game == key,
                )
                for key, label, emoji in CASINO_GAMES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected_casino_game = self.values[0]
        await self.view.refresh(interaction)


class HubCasinoBetModal(discord.ui.Modal):
    def __init__(self, view: "GameHubView", game: str) -> None:
        game_labels = {key: label for key, label, _emoji in CASINO_GAMES}
        super().__init__(title=f"Play {game_labels.get(game, game.title())}")
        self.hub_view = view
        self.game = game
        self.bet = discord.ui.TextInput(
            label="Bet",
            placeholder="100, 1k, half, all, or 25%",
            default="200" if game == "blackjack" else "100",
            max_length=20,
        )
        self.add_item(self.bet)
        self.choice = None
        self.extra = None

        choices = {
            "coinflip": ("Heads or tails", "heads"),
            "hilo": ("High, low, or 7", "high"),
            "rps": ("Rock, paper, or scissors", "rock"),
            "cups": ("Cup 1, 2, or 3", "1"),
            "roulette": ("Bet target", "red"),
            "crash": ("Cashout multiplier", "2.0"),
            "dice": ("Over or under", "over"),
            "keno": ("Picks 1-40 (up to 3)", "7"),
        }
        if game in choices:
            label, default = choices[game]
            self.choice = discord.ui.TextInput(
                label=label,
                default=default,
                max_length=50,
            )
            self.add_item(self.choice)
        if game == "dice":
            self.extra = discord.ui.TextInput(
                label="Target number (2-98)",
                default="50",
                max_length=3,
            )
            self.add_item(self.extra)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bet = str(self.bet.value).strip() or "100"
        choice = str(self.choice.value).strip() if self.choice is not None else ""

        if self.game == "slots":
            return await self.hub_view.run_command(
                interaction,
                "slots",
                amount=bet,
            )
        if self.game == "coinflip":
            return await self.hub_view.run_command(
                interaction,
                "coinflip",
                arg1=choice or "heads",
                arg2=bet,
            )
        if self.game == "blackjack":
            return await self.hub_view.run_command(
                interaction,
                "blackjack",
                bet=bet,
            )
        if self.game == "roulette":
            return await self.hub_view.run_command(
                interaction,
                "roulette",
                arg1=choice or "red",
                arg2=bet,
            )
        if self.game == "hilo":
            return await self.hub_view.run_command(
                interaction,
                "hilo",
                arg1=choice or "high",
                arg2=bet,
            )
        if self.game == "rps":
            return await self.hub_view.run_command(
                interaction,
                "rps",
                arg1=choice or "rock",
                arg2=bet,
            )
        if self.game == "cups":
            return await self.hub_view.run_command(
                interaction,
                "cups",
                arg1=choice or "1",
                arg2=bet,
            )
        if self.game == "wheel":
            return await self.hub_view.run_command(
                interaction,
                "wheel",
                bet=bet,
            )
        if self.game == "crash":
            try:
                cashout = float(choice or "2.0")
            except ValueError:
                return await interaction.response.send_message(
                    "❌ Cashout multiplier must be a number.",
                    ephemeral=True,
                )
            return await self.hub_view.run_command(
                interaction,
                "crash",
                bet=bet,
                cashout=cashout,
            )
        if self.game == "dice":
            try:
                target = int(str(self.extra.value).strip()) if self.extra is not None else 50
            except ValueError:
                return await interaction.response.send_message(
                    "❌ Dice target must be a whole number.",
                    ephemeral=True,
                )
            return await self.hub_view.run_command(
                interaction,
                "dice",
                bet=bet,
                guess=choice or "over",
                target=target,
            )
        if self.game == "keno":
            raw_picks = (
                choice.replace(",", " ")
                .replace("/", " ")
                .split()
            )
            picks = []
            for raw in raw_picks:
                try:
                    pick = int(raw)
                except ValueError:
                    return await interaction.response.send_message(
                        "❌ Keno picks must be whole numbers from 1 to 40.",
                        ephemeral=True,
                    )
                if pick < 1 or pick > 40:
                    return await interaction.response.send_message(
                        "❌ Keno picks must be between 1 and 40.",
                        ephemeral=True,
                    )
                if pick not in picks:
                    picks.append(pick)
            picks = picks[:3]
            if not picks:
                return await interaction.response.send_message(
                    "❌ Choose at least one Keno number.",
                    ephemeral=True,
                )
            values = [str(value) for value in picks]
            return await self.hub_view.run_command(
                interaction,
                "keno",
                arg1=values[0] if len(values) > 0 else None,
                arg2=values[1] if len(values) > 1 else None,
                arg3=values[2] if len(values) > 2 else None,
                arg4=_keno_bet_token(bet),
            )

        await interaction.response.send_message(
            "⚠️ That casino game is not available from the panel.",
            ephemeral=True,
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
        self.selected_concentrate: str | None = None
        self.selected_steal_target = None
        self.selected_casino_game: str | None = None
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
        self.clear_items()
        self.add_item(HubPageSelect(self))

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
        flower = _sum_mapping(profile.get("flower_stash"))
        queue = [
            item
            for item in profile.get("processing_queue", []) or []
            if isinstance(item, dict)
        ]
        completed_batches = sum(
            1
            for item in queue
            if now >= float(item.get("finish_time", now + 1))
        )
        crew_id = profile.get("crew_id")

        if self.page == "grow":
            self.add_item(HubSeedSelect(self, profile))
            self.add_action(
                "plant",
                "Plant Selected",
                "🌱",
                row=2,
                style=discord.ButtonStyle.success,
                disabled=self.selected_seed is None,
            )
            self.add_action(
                "harvest",
                "Harvest Ready",
                "✂️",
                row=2,
                style=discord.ButtonStyle.success,
                disabled=ready_count <= 0,
            )
            self.add_action("status", "Garden", "🪴", row=2)
            self.add_action("shop_seeds", "Seed Shop", "🛒", row=2)
        elif self.page == "inventory":
            self.add_action("inventory", "Inventory", "🎒", row=1)
            self.add_action(
                "sell_all",
                "Sell All Flower",
                "💵",
                row=1,
                style=discord.ButtonStyle.success,
                disabled=flower <= 0,
            )
            self.add_action(
                "collect",
                "Collect Lab",
                "📦",
                row=1,
                disabled=completed_batches <= 0,
            )
            self.add_action("shop", "Shop", "🛒", row=1)
        elif self.page == "market":
            disabled = not scope.multiplayer
            self.add_action(
                "auction",
                "Browse Auctions",
                "🔨",
                row=1,
                disabled=disabled,
            )
            self.add_action(
                "bid_modal",
                "Place Bid",
                "💰",
                row=1,
                style=discord.ButtonStyle.primary,
                disabled=disabled,
            )
            self.add_action(
                "list_modal",
                "List Item",
                "📤",
                row=1,
                disabled=disabled,
            )
            self.add_action(
                "leaderboard",
                "Leaderboard",
                "🏆",
                row=1,
                disabled=disabled,
            )
        elif self.page == "lab":
            self.add_item(HubConcentrateSelect(self, profile))
            self.add_action(
                "process_modal",
                "Start Batch",
                "⚗️",
                row=2,
                style=discord.ButtonStyle.success,
                disabled=self.selected_concentrate is None,
            )
            self.add_action("lab", "Lab Status", "🧪", row=2)
            self.add_action(
                "collect",
                "Collect Ready",
                "📦",
                row=2,
                disabled=completed_batches <= 0,
            )
            self.add_action("shop_equipment", "Equipment Shop", "🛒", row=2)
        elif self.page == "crime":
            self.add_item(
                HubStealTargetSelect(
                    self,
                    disabled=not scope.multiplayer,
                )
            )
            self.add_action(
                "heist_stealth",
                "Stealth Heist",
                "🥷",
                row=2,
                style=discord.ButtonStyle.success,
            )
            self.add_action(
                "heist_loud",
                "Loud Heist",
                "💥",
                row=2,
                style=discord.ButtonStyle.danger,
            )
            self.add_action("heist_con", "Con Job", "🎭", row=2)
            self.add_action(
                "steal_selected",
                "Rob Selected",
                "🔫",
                row=2,
                disabled=(
                    not scope.multiplayer
                    or self.selected_steal_target is None
                ),
            )
            self.add_action("launder_modal", "Launder Cash", "🧼", row=2)
            self.add_action("heat", "Heat", "🔥", row=3)
            self.add_action("heiststats", "Heist Stats", "📊", row=3)
            self.add_action("topheists", "Top Heists", "🏆", row=3)
        elif self.page == "progress":
            self.add_action(
                "daily",
                "Daily Reward",
                "☀️",
                row=1,
                style=discord.ButtonStyle.success,
            )
            self.add_action("quests", "Quests", "📜", row=1)
            self.add_action("achievements", "Achievements", "🏆", row=1)
            self.add_action("level", "Level & XP", "📈", row=1)
        elif self.page == "social":
            if not scope.multiplayer:
                self.add_action("profile", "Profile", "👤", row=1)
                self.add_action("world-mode", "World Mode", "🌍", row=1)
            elif crew_id:
                self.add_action("crew_info", "Crew Info", "👥", row=1)
                self.add_action("crew_deposit_modal", "Deposit", "🏦", row=1)
                self.add_action(
                    "crew_leave",
                    "Leave Crew",
                    "🚪",
                    row=1,
                    style=discord.ButtonStyle.danger,
                )
                self.add_action("crew_war", "Turf War", "⚔️", row=1)
                self.add_action("district", "District", "🏙️", row=1)
                self.add_action("profile", "Profile", "👤", row=2)
                self.add_action("leaderboard", "Leaderboard", "🏆", row=2)
            else:
                self.add_action(
                    "crew_create_modal",
                    "Create Crew",
                    "➕",
                    row=1,
                    style=discord.ButtonStyle.success,
                )
                self.add_action("crew_join_modal", "Join Crew", "👥", row=1)
                self.add_action("profile", "Profile", "👤", row=1)
                self.add_action("leaderboard", "Leaderboard", "🏆", row=1)
                self.add_action("district", "District", "🏙️", row=1)
        elif self.page == "casino":
            self.add_item(HubCasinoGameSelect(self))
            self.add_action(
                "casino_play",
                "Play Selected",
                "🎲",
                row=2,
                style=discord.ButtonStyle.success,
                disabled=self.selected_casino_game is None,
            )
            self.add_action("casino", "Casino Profile", "🎰", row=2)
            self.add_action("casinolb", "Casino Rankings", "🏆", row=2)
        elif self.page == "settings":
            self.add_action("notifications", "Notifications", "📟", row=1)
            self.add_action("world-mode", "World Mode", "🌍", row=1)
            self.add_action("profile-settings", "Profile & Privacy", "🪪", row=1)
            self.add_action("help", "Help", "❓", row=1)
        else:
            self.add_action(
                "next_move",
                "Do Next Move",
                "🧭",
                row=1,
                style=discord.ButtonStyle.success,
            )
            self.add_action(
                "shop",
                "Shop",
                "🛒",
                row=2,
                style=discord.ButtonStyle.primary,
            )
            self.add_action(
                "harvest",
                "Harvest",
                "✂️",
                row=2,
                style=discord.ButtonStyle.success,
                disabled=ready_count <= 0,
            )
            self.add_action(
                "daily",
                "Daily",
                "☀️",
                row=2,
                style=discord.ButtonStyle.success,
            )
            self.add_action("profile", "Profile", "👤", row=2)
            self.add_action("inventory", "Inventory", "🎒", row=2)

        self.add_action("refresh", "Refresh", "🔄", row=4)
        self.add_action(
            "close",
            "Close",
            "✖️",
            row=4,
            style=discord.ButtonStyle.danger,
        )

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

        # The Hub owns the InteractionMessage returned by the original ephemeral
        # slash response. Component interactions also expose interaction.message,
        # but discord.py treats that as a normal channel Message; editing it uses
        # the channel-message endpoint and Discord returns 10008 for ephemerals.
        message = self.message or interaction.message
        if message is not None:
            edited = await message.edit(
                embed=self.cog.build_embed(
                    scope,
                    profile,
                    world,
                    page=self.page,
                    selected_seed=self.selected_seed,
                ),
                view=self,
            )
            if edited is not None:
                self.message = edited

    async def open_shop(
        self,
        interaction: discord.Interaction,
        *,
        category: str = "all",
    ) -> None:
        economy = self.cog.bot.get_cog("Economy")
        if economy is None:
            return await interaction.response.send_message(
                "⚠️ Shop is temporarily unavailable.",
                ephemeral=True,
            )
        scope, profile = await economy._profile_for(self.guild_id, self.owner_id)
        view = ShopView(
            economy,
            self.owner_id,
            self.guild_id,
            category=category,
        )
        view.rebuild(profile)
        await interaction.response.send_message(
            embed=economy.build_shop_embed(
                scope,
                profile,
                category=category,
            ),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

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
            # Hub actions originate from component/modal interactions, not slash-command
            # invocations. HybridCommand.can_run() switches to discord.py's app-command
            # path whenever ctx.interaction is present; that path expects interaction._baton
            # to contain a real commands.Context, which component interactions do not have.
            # Run the normal Command check pipeline explicitly against our restricted context.
            if not await commands.Command.can_run(command, ctx):
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

    async def perform_next_move(self, interaction: discord.Interaction) -> None:
        scope, profile, world = await self.state()
        step = choose_onboarding_step(scope, profile, world, now=time.time())

        if step.key == "world_mode":
            return await self.run_command(interaction, "world-mode")
        if step.key == "sell":
            return await self.run_command(
                interaction,
                "sell",
                amount="all",
                strain_name=None,
            )
        if step.key == "harvest":
            return await self.run_command(interaction, "harvest")
        if step.key == "collect":
            return await self.run_command(interaction, "collect")
        if step.key == "status":
            self.page = "grow"
            return await self.refresh(interaction)
        if step.key == "plant":
            marker = "strain_name:"
            if marker in step.command:
                self.selected_seed = step.command.split(marker, 1)[1].strip()
                return await self.run_command(
                    interaction,
                    "plant",
                    strain_name=self.selected_seed,
                )
            self.page = "grow"
            return await self.refresh(interaction)
        if step.key == "buy_seed":
            return await self.open_shop(interaction, category="seeds")
        if step.key == "daily":
            return await self.run_command(interaction, "growdaily")

        return await self.run_command(interaction, "help")

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
        if action == "shop_seeds":
            return await self.open_shop(interaction, category="seeds")
        if action == "shop_equipment":
            return await self.open_shop(interaction, category="equipment")
        if action == "next_move":
            return await self.perform_next_move(interaction)
        if action == "casino_play":
            if not self.selected_casino_game:
                return await interaction.response.send_message(
                    "🎰 Choose a casino game first.",
                    ephemeral=True,
                )
            return await interaction.response.send_modal(
                HubCasinoBetModal(self, self.selected_casino_game)
            )
        if action == "process_modal":
            if not self.selected_concentrate:
                return await interaction.response.send_message(
                    "⚗️ Choose a concentrate first.",
                    ephemeral=True,
                )
            return await interaction.response.send_modal(
                HubProcessModal(self, self.selected_concentrate)
            )
        if action == "crew_create_modal":
            return await interaction.response.send_modal(HubCrewCreateModal(self))
        if action == "crew_join_modal":
            return await interaction.response.send_modal(HubCrewJoinModal(self))
        if action == "crew_deposit_modal":
            return await interaction.response.send_modal(HubCrewDepositModal(self))
        if action == "steal_selected":
            if self.selected_steal_target is None:
                return await interaction.response.send_message(
                    "🔫 Choose a player first.",
                    ephemeral=True,
                )
            return await self.run_command(
                interaction,
                "steal",
                target=self.selected_steal_target,
            )
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
            "crew_info": "crew info",
            "crew_leave": "crew leave",
            "crew_war": "crew war",
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
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
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
                value="Choose a concentrate below, tap Start Batch, enter the amount, and collect it here when finished.",
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
                value="Choose a solo plan directly. In multiplayer saves, pick a player above and tap Rob Selected. Launder opens a private amount form.",
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
            embed.add_field(
                name="Controls",
                value=(
                    "Manage your crew, district, profile, and leaderboard directly below."
                    if scope.multiplayer
                    else "This save is private. Open World Mode below if you want multiplayer systems."
                ),
                inline=False,
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
                name="Play",
                value=(
                    "Choose a game below, tap **Play Selected**, then enter the wager and "
                    "game-specific choice in the private form. No wager is placed until you submit it."
                ),
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

        # A button interaction has the same short acknowledgement window as a slash
        # command. A cold scope/profile/world load must never consume that window.
        await interaction.response.defer(ephemeral=True, thinking=True)
        scope, profile, world = await self.state(
            interaction.guild_id,
            interaction.user.id,
        )
        view = GameHubView(self, interaction.user.id, interaction.guild_id)
        view.rebuild(scope, profile, world)
        view.message = await interaction.edit_original_response(
            embed=self.build_embed(scope, profile, world),
            view=view,
        )

    async def _send_hub_context(self, ctx) -> None:
        guild_id = require_guild_id(ctx)
        interaction = ctx.interaction
        if interaction is not None:
            await ctx.defer(ephemeral=True)

        scope, profile, world = await self.state(guild_id, ctx.author.id)
        view = GameHubView(self, ctx.author.id, guild_id)
        view.rebuild(scope, profile, world)

        if interaction is not None:
            view.message = await interaction.edit_original_response(
                embed=self.build_embed(scope, profile, world),
                view=view,
            )
            return

        view.message = await ctx.send(
            embed=self.build_embed(scope, profile, world),
            view=view,
        )

    @commands.hybrid_command(name="game")
    async def game(self, ctx):
        """Open the private all-in-one player command center."""
        await self._send_hub_context(ctx)

    @commands.hybrid_command(name="menu")
    async def menu(self, ctx):
        """Open the same player command center as /game."""
        await self._send_hub_context(ctx)

    @commands.hybrid_command(name="play")
    async def play(self, ctx):
        """Open the same player command center as /game."""
        await self._send_hub_context(ctx)


async def setup(bot):
    await bot.add_cog(GameHub(bot))
