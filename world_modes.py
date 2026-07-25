from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id


# Discord guild snowflakes are far larger than 1. This reserved positive scope lets
# the existing, proven guild-profile/world persistence tables hold one shared Open
# World without a parallel database implementation or a destructive migration.
OPEN_WORLD_SCOPE_ID = 1

WORLD_MODE_CONFIG_KEY = "world_mode_config"
PLAYER_MODE_SELECTION_KEY = "world_mode_selection"

POLICY_SERVER = "server"
POLICY_SOLO = "solo"
POLICY_OPEN = "open"
POLICY_CHOICE = "choice"

MODE_SERVER = "server"
MODE_SOLO = "solo"
MODE_OPEN = "open"

VALID_POLICIES = {POLICY_SERVER, POLICY_SOLO, POLICY_OPEN, POLICY_CHOICE}
VALID_PLAYER_MODES = {MODE_SOLO, MODE_OPEN}

DEFAULT_PLAYER_MODE = MODE_SOLO
DEFAULT_SWITCH_COOLDOWN_SECONDS = 7 * 24 * 60 * 60
SOLO_POT_CAP = 5
SOLO_PROCESSING_QUEUE_CAP = 3
SOLO_MARKET_MULTIPLIER_CAP = 1.25

POLICY_LABELS = {
    POLICY_SERVER: "Current Server World",
    POLICY_SOLO: "Solo Grow",
    POLICY_OPEN: "Open World",
    POLICY_CHOICE: "Player Choice",
}
MODE_LABELS = {
    MODE_SERVER: "Current Server World",
    MODE_SOLO: "Solo Grow",
    MODE_OPEN: "Open World",
}
MODE_EMOJIS = {
    MODE_SERVER: "🏙️",
    MODE_SOLO: "🔒",
    MODE_OPEN: "🌍",
}

MULTIPLAYER_FEATURE_LABELS = {
    "transfer": "player transfers",
    "theft": "player theft",
    "auction": "the auction house",
    "crew": "crews",
    "crew_bank": "crew banking",
    "crew_heist": "crew heists",
    "raid": "crew raids",
    "district": "district wars",
    "leaderboard": "shared leaderboards",
}


class WorldModeError(RuntimeError):
    """Base error for world-mode selection and feature checks."""


class WorldModeDenied(WorldModeError):
    """Raised when the active mode does not permit an interaction."""


class WorldModeSwitchCooldown(WorldModeError):
    def __init__(self, remaining_seconds: int) -> None:
        self.remaining_seconds = max(0, int(remaining_seconds))
        super().__init__(
            f"World mode can be changed again in {format_duration(self.remaining_seconds)}"
        )


@dataclass(frozen=True, slots=True)
class GameScope:
    guild_id: int
    user_id: int
    policy: str
    mode: str
    scope_id: int
    selection_explicit: bool = False

    @property
    def label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode.title())

    @property
    def emoji(self) -> str:
        return MODE_EMOJIS.get(self.mode, "🌿")

    @property
    def multiplayer(self) -> bool:
        return self.mode in {MODE_SERVER, MODE_OPEN}

    @property
    def cross_server(self) -> bool:
        return self.mode == MODE_OPEN

    @property
    def solo(self) -> bool:
        return self.mode == MODE_SOLO


@dataclass(frozen=True, slots=True)
class PlayerModeSelection:
    mode: str
    selected_at: float
    switch_available_at: float
    explicit: bool


def new_world_mode_config() -> dict[str, Any]:
    """Safe default for a newly created guild world."""
    return {
        "policy": POLICY_SOLO,
        "default_player_mode": DEFAULT_PLAYER_MODE,
        "switch_cooldown_seconds": DEFAULT_SWITCH_COOLDOWN_SECONDS,
        "configured": False,
        "updated_at": 0,
    }


def legacy_world_mode_config() -> dict[str, Any]:
    """Compatibility interpretation for worlds created before mode controls."""
    return {
        "policy": POLICY_SERVER,
        "default_player_mode": DEFAULT_PLAYER_MODE,
        "switch_cooldown_seconds": DEFAULT_SWITCH_COOLDOWN_SECONDS,
        "configured": False,
        "legacy_compatibility": True,
        "updated_at": 0,
    }


def normalize_world_mode_config(world: dict[str, Any] | None) -> dict[str, Any]:
    raw = world.get(WORLD_MODE_CONFIG_KEY) if isinstance(world, dict) else None
    if not isinstance(raw, dict):
        return legacy_world_mode_config()

    policy = str(raw.get("policy") or POLICY_SOLO).strip().lower()
    if policy not in VALID_POLICIES:
        policy = POLICY_SOLO

    default_mode = str(raw.get("default_player_mode") or DEFAULT_PLAYER_MODE).strip().lower()
    if default_mode not in VALID_PLAYER_MODES:
        default_mode = DEFAULT_PLAYER_MODE

    try:
        cooldown = int(raw.get("switch_cooldown_seconds", DEFAULT_SWITCH_COOLDOWN_SECONDS))
    except (TypeError, ValueError):
        cooldown = DEFAULT_SWITCH_COOLDOWN_SECONDS
    cooldown = max(60 * 60, min(30 * 24 * 60 * 60, cooldown))

    try:
        updated_at = float(raw.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        updated_at = 0

    return {
        "policy": policy,
        "default_player_mode": default_mode,
        "switch_cooldown_seconds": cooldown,
        "configured": bool(raw.get("configured", False)),
        "legacy_compatibility": bool(raw.get("legacy_compatibility", False)),
        "updated_at": updated_at,
    }


def normalize_player_selection(
    profile: dict[str, Any] | None,
    config: dict[str, Any],
) -> PlayerModeSelection:
    raw = profile.get(PLAYER_MODE_SELECTION_KEY) if isinstance(profile, dict) else None
    default_mode = str(config.get("default_player_mode") or DEFAULT_PLAYER_MODE)
    if default_mode not in VALID_PLAYER_MODES:
        default_mode = DEFAULT_PLAYER_MODE

    if not isinstance(raw, dict):
        return PlayerModeSelection(default_mode, 0, 0, False)

    mode = str(raw.get("mode") or default_mode).strip().lower()
    if mode not in VALID_PLAYER_MODES:
        mode = default_mode
    try:
        selected_at = float(raw.get("selected_at", 0) or 0)
    except (TypeError, ValueError):
        selected_at = 0
    try:
        switch_available_at = float(raw.get("switch_available_at", 0) or 0)
    except (TypeError, ValueError):
        switch_available_at = 0
    explicit = bool(raw.get("explicit", selected_at > 0))
    return PlayerModeSelection(mode, selected_at, switch_available_at, explicit)


def policy_allows_open_world(policy: str) -> bool:
    return policy in {POLICY_OPEN, POLICY_CHOICE}


def policy_uses_local_world(policy: str) -> bool:
    return policy in {POLICY_SERVER, POLICY_SOLO, POLICY_CHOICE}


def policy_uses_local_multiplayer(policy: str) -> bool:
    return policy == POLICY_SERVER


def mode_for_policy(
    config: dict[str, Any],
    control_profile: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    policy = str(config.get("policy") or POLICY_SOLO)
    if policy == POLICY_SERVER:
        return MODE_SERVER, False
    if policy == POLICY_OPEN:
        return MODE_OPEN, False
    if policy == POLICY_SOLO:
        return MODE_SOLO, False
    selection = normalize_player_selection(control_profile, config)
    return selection.mode, selection.explicit


async def resolve_game_scope(database, guild_id: Any, user_id: Any) -> GameScope:
    resolved_guild = int(guild_id)
    resolved_user = int(user_id)
    if resolved_guild <= 0 or resolved_user <= 0:
        raise ValueError("guild_id and user_id must be positive")

    guild_world = await database.get_world(resolved_guild)
    config = normalize_world_mode_config(guild_world)
    control_profile = None
    if config["policy"] == POLICY_CHOICE:
        control_profile = await database.get_profile(resolved_guild, resolved_user)
    mode, explicit = mode_for_policy(config, control_profile)
    scope_id = OPEN_WORLD_SCOPE_ID if mode == MODE_OPEN else resolved_guild
    return GameScope(
        guild_id=resolved_guild,
        user_id=resolved_user,
        policy=config["policy"],
        mode=mode,
        scope_id=scope_id,
        selection_explicit=explicit,
    )


async def resolve_context_scope(database, context: Any, user_id: Any | None = None) -> GameScope:
    guild_id = require_guild_id(context)
    resolved_user_id = user_id
    if resolved_user_id is None:
        author = getattr(context, "author", None)
        resolved_user_id = getattr(author, "id", None)
    if resolved_user_id is None:
        raise ValueError("user_id is required when context has no author")
    return await resolve_game_scope(database, guild_id, resolved_user_id)


async def get_game_profile(database, guild_id: Any, user_id: Any):
    scope = await resolve_game_scope(database, guild_id, user_id)
    return scope, await database.get_profile(scope.scope_id, scope.user_id)


async def get_game_world(database, guild_id: Any, user_id: Any):
    scope = await resolve_game_scope(database, guild_id, user_id)
    return scope, await database.get_world(scope.scope_id)


async def get_game_records(database, guild_id: Any, user_id: Any):
    scope = await resolve_game_scope(database, guild_id, user_id)
    profile = await database.get_profile(scope.scope_id, scope.user_id)
    world = await database.get_world(scope.scope_id)
    return scope, profile, world


def mark_game_profile_dirty(database, scope: GameScope, user_id: Any | None = None) -> None:
    database.mark_profile_dirty(scope.scope_id, scope.user_id if user_id is None else int(user_id))


def mark_game_world_dirty(database, scope: GameScope) -> None:
    database.mark_world_dirty(scope.scope_id)


def multiplayer_denial_message(scope: GameScope, feature: str) -> str:
    label = MULTIPLAYER_FEATURE_LABELS.get(feature, "that multiplayer feature")
    if scope.solo:
        return (
            f"🔒 **{label.title()} are unavailable in Solo Grow.** "
            "Solo saves stay private and cannot exchange value with other players."
        )
    return f"❌ **{label.title()} are unavailable in the current world mode.**"


def require_multiplayer(scope: GameScope, feature: str) -> None:
    if not scope.multiplayer:
        raise WorldModeDenied(multiplayer_denial_message(scope, feature))


def require_same_multiplayer_scope(
    actor: GameScope,
    target: GameScope,
    feature: str,
) -> None:
    require_multiplayer(actor, feature)
    if not target.multiplayer or target.scope_id != actor.scope_id:
        raise WorldModeDenied(
            "🚧 **Both players must be in the same multiplayer world.** "
            "Solo Grow and Open World saves never mix."
        )


def effective_pot_capacity(profile: dict[str, Any], scope: GameScope) -> int:
    stored = max(0, int(profile.get("max_pots", 3) or 3))
    return min(stored, SOLO_POT_CAP) if scope.solo else stored


def processing_queue_limit(scope: GameScope) -> int | None:
    return SOLO_PROCESSING_QUEUE_CAP if scope.solo else None


def effective_market_multiplier(world: dict[str, Any], scope: GameScope) -> float:
    try:
        multiplier = max(0.0, float(world.get("market_multiplier", 1.0) or 1.0))
    except (TypeError, ValueError):
        multiplier = 1.0
    return min(multiplier, SOLO_MARKET_MULTIPLIER_CAP) if scope.solo else multiplier


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts[:2])


async def set_server_policy(database, guild_id: int, policy: str) -> dict[str, Any]:
    clean_policy = str(policy).strip().lower()
    if clean_policy not in VALID_POLICIES:
        raise ValueError("unsupported world policy")

    async with database.lock:
        world = await database.get_world(int(guild_id))
        current = normalize_world_mode_config(world)
        updated = {
            **current,
            "policy": clean_policy,
            "configured": True,
            "legacy_compatibility": clean_policy == POLICY_SERVER,
            "updated_at": time.time(),
        }
        world[WORLD_MODE_CONFIG_KEY] = updated
        database.mark_world_dirty(int(guild_id))
    return updated


async def choose_player_mode(
    database,
    guild_id: int,
    user_id: int,
    mode: str,
    *,
    now: float | None = None,
) -> PlayerModeSelection:
    clean_mode = str(mode).strip().lower()
    if clean_mode not in VALID_PLAYER_MODES:
        raise ValueError("mode must be solo or open")
    timestamp = time.time() if now is None else float(now)

    async with database.lock:
        world = await database.get_world(int(guild_id))
        config = normalize_world_mode_config(world)
        if config["policy"] != POLICY_CHOICE:
            raise WorldModeDenied(
                "❌ This server does not currently allow individual world selection."
            )

        control_profile = await database.get_profile(int(guild_id), int(user_id))
        current = normalize_player_selection(control_profile, config)
        if current.explicit and current.mode != clean_mode and timestamp < current.switch_available_at:
            raise WorldModeSwitchCooldown(current.switch_available_at - timestamp)

        if current.mode == clean_mode and current.explicit:
            return current

        cooldown = int(config["switch_cooldown_seconds"])
        updated = PlayerModeSelection(
            mode=clean_mode,
            selected_at=timestamp,
            switch_available_at=timestamp + cooldown,
            explicit=True,
        )
        control_profile[PLAYER_MODE_SELECTION_KEY] = {
            "mode": updated.mode,
            "selected_at": updated.selected_at,
            "switch_available_at": updated.switch_available_at,
            "explicit": True,
        }
        database.mark_profile_dirty(int(guild_id), int(user_id))
        return updated


async def world_mode_status(database, guild_id: int) -> str:
    world = await database.get_world(int(guild_id))
    config = normalize_world_mode_config(world)
    policy = config["policy"]
    label = POLICY_LABELS[policy]
    if policy == POLICY_SERVER and config.get("legacy_compatibility"):
        return "🟡 **Current Server World** — compatibility mode preserving existing local multiplayer"
    if policy == POLICY_SOLO:
        return "🔒 **Solo Grow** — private server-local saves; multiplayer value exchange disabled"
    if policy == POLICY_OPEN:
        return "🌍 **Open World** — shared cross-server economy and full multiplayer"
    return "🔀 **Player Choice** — separate Solo/Open saves with a 7-day switch cooldown"


async def build_player_mode_embed(database, guild: discord.Guild, user_id: int) -> discord.Embed:
    guild_world = await database.get_world(guild.id)
    config = normalize_world_mode_config(guild_world)
    control_profile = await database.get_profile(guild.id, user_id)
    scope = await resolve_game_scope(database, guild.id, user_id)
    selection = normalize_player_selection(control_profile, config)

    embed = discord.Embed(
        title="🌿 Your Idle Grow World",
        description=(
            "Solo Grow and Open World use completely separate saves. Cash, plants, inventory, "
            "crews, cooldowns, and progression are never copied or merged between them."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Server policy",
        value=POLICY_LABELS[config["policy"]],
        inline=True,
    )
    embed.add_field(
        name="Active save",
        value=f"{scope.emoji} **{scope.label}**",
        inline=True,
    )
    location = (
        "Follows you across participating servers"
        if scope.cross_server
        else f"Stored only for **{guild.name}**"
    )
    embed.add_field(name="Save location", value=location, inline=False)

    if scope.solo:
        embed.add_field(
            name="Solo limitations",
            value=(
                f"No transfers, theft, auctions, crews, raids, territory, or shared leaderboards. "
                f"Active grow capacity is capped at **{SOLO_POT_CAP} pots**, lab queue at "
                f"**{SOLO_PROCESSING_QUEUE_CAP} batches**, and positive market spikes at "
                f"**{SOLO_MARKET_MULTIPLIER_CAP:.2f}x**."
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Multiplayer access",
            value="Trading, auctions, crews, crew banks, raids, territory, and shared leaderboards are enabled.",
            inline=False,
        )

    if config["policy"] == POLICY_CHOICE:
        if selection.explicit:
            remaining = max(0, int(selection.switch_available_at - time.time()))
            switch_text = "Available now" if not remaining else f"Available in {format_duration(remaining)}"
        else:
            switch_text = "First choice is free"
        embed.add_field(name="Next switch", value=switch_text, inline=False)
        embed.set_footer(text="Choose carefully. After the first selection, changing worlds has a 7-day cooldown.")
    else:
        embed.set_footer(text="The server owner controls this policy through /setup.")
    return embed


async def build_server_mode_embed(database, guild: discord.Guild) -> discord.Embed:
    world = await database.get_world(guild.id)
    config = normalize_world_mode_config(world)
    embed = discord.Embed(
        title="🌍 World Mode Setup",
        description=(
            "Choose how Idle Grow saves work in this server. Changing policy never deletes or merges "
            "progress; each save waits safely in its own scope until that mode is used again."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="Current status", value=await world_mode_status(database, guild.id), inline=False)
    embed.add_field(
        name="🔒 Solo Grow",
        value="Private server-local saves. No player value exchange. Lower grow/lab caps keep Solo from becoming the easiest path.",
        inline=False,
    )
    embed.add_field(
        name="🌍 Open World",
        value="One shared cross-server save and world with trading, auctions, crews, raids, territory, and global competition.",
        inline=False,
    )
    embed.add_field(
        name="🔀 Player Choice",
        value="Players choose Solo or Open. The saves never mix, and switching is limited to once every seven days.",
        inline=False,
    )
    embed.add_field(
        name="🏙️ Current Server World",
        value="Preserves the bot's previous guild-local multiplayer behavior for existing communities and progress.",
        inline=False,
    )
    if not config.get("configured"):
        embed.add_field(
            name="Why this has not changed automatically",
            value="Existing servers remain in compatibility mode; newly created worlds use the safe Solo default until a manager chooses.",
            inline=False,
        )
    embed.set_footer(text="Select a policy, review the consequence, then confirm. No data is copied or erased.")
    return embed


class PlayerWorldModeView(discord.ui.View):
    def __init__(self, cog: "WorldModes", owner_id: int, guild_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This world selection belongs to another player or server.",
                ephemeral=True,
            )
            return False
        return True

    async def _select(self, interaction: discord.Interaction, mode: str) -> None:
        try:
            await choose_player_mode(
                self.cog.bot.db,
                self.guild_id,
                self.owner_id,
                mode,
            )
        except WorldModeError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        signatures = self.cog.bot.get_cog("ProfileSignatures")
        if signatures is not None and hasattr(signatures, "remove_user_cards"):
            await signatures.remove_user_cards(self.guild_id, self.owner_id)
        await interaction.response.edit_message(
            embed=await build_player_mode_embed(
                self.cog.bot.db,
                interaction.guild,
                self.owner_id,
            ),
            view=self,
        )

    @discord.ui.button(label="Solo Grow", emoji="🔒", style=discord.ButtonStyle.secondary)
    async def solo(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._select(interaction, MODE_SOLO)

    @discord.ui.button(label="Open World", emoji="🌍", style=discord.ButtonStyle.success)
    async def open_world(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._select(interaction, MODE_OPEN)


class ConfirmWorldPolicyView(discord.ui.View):
    def __init__(
        self,
        cog: "WorldModes",
        owner_id: int,
        guild_id: int,
        policy: str,
        *,
        timeout: float = 180,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.policy = policy

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("❌ This setup confirmation is not yours.", ephemeral=True)
            return False
        member = interaction.user
        if not isinstance(member, discord.Member) or not (
            member.guild_permissions.manage_guild or member.guild.owner_id == member.id
        ):
            await interaction.response.send_message("❌ You need **Manage Server**.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Change", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await set_server_policy(self.cog.bot.db, self.guild_id, self.policy)
        signatures = self.cog.bot.get_cog("ProfileSignatures")
        if signatures is not None and hasattr(signatures, "invalidate_guild_cards"):
            await signatures.invalidate_guild_cards(interaction.guild)
        await interaction.response.edit_message(
            embed=await build_server_mode_embed(self.cog.bot.db, interaction.guild),
            view=ServerWorldModeView(self.cog, self.owner_id, self.guild_id),
        )

    @discord.ui.button(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await build_server_mode_embed(self.cog.bot.db, interaction.guild),
            view=ServerWorldModeView(self.cog, self.owner_id, self.guild_id),
        )


class ServerWorldModeView(discord.ui.View):
    def __init__(self, cog: "WorldModes", owner_id: int, guild_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("❌ This setup panel is not yours.", ephemeral=True)
            return False
        member = interaction.user
        if not isinstance(member, discord.Member) or not (
            member.guild_permissions.manage_guild or member.guild.owner_id == member.id
        ):
            await interaction.response.send_message("❌ You need **Manage Server**.", ephemeral=True)
            return False
        return True

    async def _review(self, interaction: discord.Interaction, policy: str) -> None:
        descriptions = {
            POLICY_SOLO: "Players use private server-local saves. Multiplayer value exchange and shared competition are disabled.",
            POLICY_OPEN: "Players use the shared cross-server Open World save with every multiplayer system enabled.",
            POLICY_CHOICE: "Players choose between separate Solo and Open saves, with a seven-day switch cooldown.",
            POLICY_SERVER: "The existing guild-local multiplayer save and all current local crews/auctions remain active.",
        }
        embed = discord.Embed(
            title=f"Confirm: {POLICY_LABELS[policy]}",
            description=descriptions[policy],
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Data safety",
            value="No balances, items, plants, crews, auctions, or progression are copied, merged, reset, or deleted.",
            inline=False,
        )
        embed.set_footer(text="Confirm to change the policy, or go back without changing anything.")
        await interaction.response.edit_message(
            embed=embed,
            view=ConfirmWorldPolicyView(
                self.cog,
                self.owner_id,
                self.guild_id,
                policy,
            ),
        )

    @discord.ui.button(label="Solo Grow", emoji="🔒", style=discord.ButtonStyle.secondary, row=0)
    async def solo(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._review(interaction, POLICY_SOLO)

    @discord.ui.button(label="Open World", emoji="🌍", style=discord.ButtonStyle.success, row=0)
    async def open_world(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._review(interaction, POLICY_OPEN)

    @discord.ui.button(label="Player Choice", emoji="🔀", style=discord.ButtonStyle.primary, row=0)
    async def choice(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._review(interaction, POLICY_CHOICE)

    @discord.ui.button(label="Current Server World", emoji="🏙️", style=discord.ButtonStyle.secondary, row=1)
    async def server(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._review(interaction, POLICY_SERVER)


class WorldModes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="world-mode",
        aliases=["worldmode", "playmode"],
        description="View or choose your Idle Grow world",
    )
    @commands.guild_only()
    async def world_mode(self, ctx: commands.Context) -> None:
        try:
            guild_id = require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return
        guild_world = await self.bot.db.get_world(guild_id)
        config = normalize_world_mode_config(guild_world)
        view = (
            PlayerWorldModeView(self, ctx.author.id, guild_id)
            if config["policy"] == POLICY_CHOICE
            else None
        )
        await ctx.send(
            embed=await build_player_mode_embed(self.bot.db, ctx.guild, ctx.author.id),
            view=view,
            ephemeral=ctx.interaction is not None,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldModes(bot))
