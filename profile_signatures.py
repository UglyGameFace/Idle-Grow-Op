from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlparse, urlunparse

import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id
from utils import _xp_needed_for_level, get_plant_grow_time


logger = logging.getLogger(__name__)

SIGNATURE_CONFIG_KEY = "profile_signature_config"
SIGNATURE_STATE_KEY = "profile_signature_state"
SIGNATURE_ENABLED_KEY = "enabled"
SIGNATURE_CHANNELS_KEY = "channel_ids"
SIGNATURE_ALLOWED_FIELDS_KEY = "allowed_fields"

IDENTITY_KEY = "profile_identity"
GLOBAL_PRIVACY_KEY = "profile_privacy"
GUILD_PRIVACY_KEY = "profile_signature_privacy"

SIGNATURE_MARKER = "Idle Grow Live Signature"
SIGNATURE_DEBOUNCE_SECONDS = 2.5
SIGNATURE_CHANNEL_COOLDOWN_SECONDS = 8.0
SIGNATURE_USER_COOLDOWN_SECONDS = 20.0
SIGNATURE_SAME_SPEAKER_REFRESH_SECONDS = 90.0
SIGNATURE_HISTORY_SCAN_LIMIT = 100

FIELD_LABELS = {
    "level": "Level & XP",
    "crew": "Crew",
    "grow_status": "Grow status",
    "wealth": "Balance / net worth",
    "inventory": "Inventory summary",
    "rank": "Server rank",
    "achievements": "Achievements",
    "activity": "Activity details",
    "platforms": "Gaming & social platforms",
}
ALL_PROFILE_FIELDS = tuple(FIELD_LABELS)
DEFAULT_VISIBLE_FIELDS = frozenset({"level", "crew", "grow_status"})
DEFAULT_SERVER_ALLOWED_FIELDS = frozenset(
    {"level", "crew", "grow_status", "rank", "achievements", "platforms"}
)

_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")
_STEAM_ID_RE = re.compile(r"^\d{15,20}$")
_ROBLOX_ID_RE = re.compile(r"^\d{1,20}$")
_YOUTUBE_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9_.-]{3,100}$")


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    emoji: str
    hosts: frozenset[str]
    path_validator: Callable[[str], bool] | None = None
    username_url: Callable[[str], str | None] | None = None


def _single_path_segment(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return len(parts) == 1 and bool(_SLUG_RE.fullmatch(parts[0]))


def _steam_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 2:
        return False
    prefix, identifier = parts
    if prefix == "profiles":
        return bool(_STEAM_ID_RE.fullmatch(identifier))
    if prefix == "id":
        return bool(_SLUG_RE.fullmatch(identifier))
    return False


def _youtube_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if len(parts) == 1 and parts[0].startswith("@"):
        return bool(_YOUTUBE_HANDLE_RE.fullmatch(parts[0]))
    if len(parts) == 2 and parts[0] in {"channel", "c"}:
        return bool(_SLUG_RE.fullmatch(parts[1]))
    return False


def _roblox_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    return (
        len(parts) == 3
        and parts[0] == "users"
        and bool(_ROBLOX_ID_RE.fullmatch(parts[1]))
        and parts[2] == "profile"
    )


def _steam_url(username: str) -> str | None:
    value = username.strip()
    if _STEAM_ID_RE.fullmatch(value):
        return f"https://steamcommunity.com/profiles/{value}"
    if _SLUG_RE.fullmatch(value):
        return f"https://steamcommunity.com/id/{quote(value, safe='_.-')}"
    return None


def _twitch_url(username: str) -> str | None:
    value = username.strip().lstrip("@")
    if _SLUG_RE.fullmatch(value):
        return f"https://www.twitch.tv/{quote(value, safe='_.-')}"
    return None


def _kick_url(username: str) -> str | None:
    value = username.strip().lstrip("@")
    if _SLUG_RE.fullmatch(value):
        return f"https://kick.com/{quote(value, safe='_.-')}"
    return None


def _youtube_url(username: str) -> str | None:
    value = username.strip()
    if not value.startswith("@"):
        value = f"@{value}"
    if _YOUTUBE_HANDLE_RE.fullmatch(value):
        return f"https://www.youtube.com/{quote(value, safe='@_.-')}"
    return None


def _roblox_url(username: str) -> str | None:
    value = username.strip()
    if _ROBLOX_ID_RE.fullmatch(value):
        return f"https://www.roblox.com/users/{value}/profile"
    return None


PLATFORMS: dict[str, PlatformSpec] = {
    "steam": PlatformSpec(
        "steam",
        "Steam",
        "🎮",
        frozenset({"steamcommunity.com", "www.steamcommunity.com"}),
        _steam_path,
        _steam_url,
    ),
    "epic": PlatformSpec("epic", "Epic Games", "🟦", frozenset()),
    "xbox": PlatformSpec("xbox", "Xbox", "🟢", frozenset()),
    "playstation": PlatformSpec("playstation", "PlayStation", "🔵", frozenset()),
    "nintendo": PlatformSpec("nintendo", "Nintendo", "🔴", frozenset()),
    "riot": PlatformSpec("riot", "Riot", "⚔️", frozenset()),
    "battlenet": PlatformSpec("battlenet", "Battle.net", "🌀", frozenset()),
    "roblox": PlatformSpec(
        "roblox",
        "Roblox",
        "🟥",
        frozenset({"roblox.com", "www.roblox.com"}),
        _roblox_path,
        _roblox_url,
    ),
    "twitch": PlatformSpec(
        "twitch",
        "Twitch",
        "🟣",
        frozenset({"twitch.tv", "www.twitch.tv"}),
        _single_path_segment,
        _twitch_url,
    ),
    "youtube": PlatformSpec(
        "youtube",
        "YouTube",
        "▶️",
        frozenset({"youtube.com", "www.youtube.com"}),
        _youtube_path,
        _youtube_url,
    ),
    "kick": PlatformSpec(
        "kick",
        "Kick",
        "🟩",
        frozenset({"kick.com", "www.kick.com"}),
        _single_path_segment,
        _kick_url,
    ),
    "custom": PlatformSpec("custom", "Other Platform", "🔗", frozenset()),
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_platform_url(platform_key: str, raw_url: str) -> str:
    spec = PLATFORMS.get(platform_key)
    if spec is None:
        raise ValueError("Unsupported platform.")
    value = raw_url.strip()
    if not value:
        return ""
    if not spec.hosts or spec.path_validator is None:
        raise ValueError(f"{spec.label} does not have a reliable public profile-link format.")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in spec.hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Use a direct HTTPS {spec.label} profile URL.")
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not spec.path_validator(path):
        raise ValueError(f"That is not a recognized {spec.label} profile URL.")
    canonical_host = sorted(spec.hosts, key=lambda item: (item.startswith("www."), item))[0]
    return urlunparse(("https", canonical_host, path.rstrip("/"), "", "", ""))


def normalize_platform_entry(
    platform_key: str,
    username: str,
    raw_url: str = "",
    *,
    shared: bool = False,
    custom_label: str = "",
) -> dict[str, Any]:
    spec = PLATFORMS.get(platform_key)
    if spec is None:
        raise ValueError("Unsupported platform.")
    clean_username = " ".join(username.strip().split())
    if not clean_username:
        raise ValueError("Enter a username, handle, or account ID.")
    if len(clean_username) > 80:
        raise ValueError("The username is too long.")

    label = spec.label
    if platform_key == "custom":
        label = " ".join(custom_label.strip().split())
        if not label:
            raise ValueError("Enter the platform name.")
        if len(label) > 30:
            raise ValueError("The platform name is too long.")
        if raw_url.strip():
            raise ValueError("Custom platforms are username-only for safety.")

    safe_url = ""
    if raw_url.strip():
        safe_url = normalize_platform_url(platform_key, raw_url)
    elif spec.username_url is not None:
        safe_url = spec.username_url(clean_username) or ""

    return {
        "platform": platform_key,
        "label": label,
        "username": clean_username,
        "url": safe_url,
        "shared": bool(shared),
    }


def _global_privacy(account: dict[str, Any]) -> tuple[bool, set[str]]:
    raw = account.get(GLOBAL_PRIVACY_KEY)
    if not isinstance(raw, dict):
        return True, set(DEFAULT_VISIBLE_FIELDS)
    enabled = bool(raw.get("signature_enabled", True))
    visible = {
        str(value)
        for value in raw.get("visible_fields", DEFAULT_VISIBLE_FIELDS)
        if str(value) in FIELD_LABELS
    }
    return enabled, visible


def _guild_privacy(profile: dict[str, Any]) -> tuple[bool, set[str]]:
    raw = profile.get(GUILD_PRIVACY_KEY)
    if not isinstance(raw, dict):
        return False, set()
    disabled = bool(raw.get("signature_disabled", False))
    hidden = {
        str(value)
        for value in raw.get("hidden_fields", [])
        if str(value) in FIELD_LABELS
    }
    return disabled, hidden


def effective_visible_fields(
    account: dict[str, Any],
    profile: dict[str, Any],
    *,
    server_allowed: set[str] | None = None,
) -> set[str]:
    enabled, global_visible = _global_privacy(account)
    server_disabled, server_hidden = _guild_privacy(profile)
    if not enabled or server_disabled:
        return set()
    visible = global_visible - server_hidden
    if server_allowed is not None:
        visible &= server_allowed
    return visible


def shared_platform_entries(account: dict[str, Any]) -> list[dict[str, Any]]:
    identity = account.get(IDENTITY_KEY)
    if not isinstance(identity, dict):
        return []
    raw_platforms = identity.get("platforms")
    if not isinstance(raw_platforms, dict):
        return []

    entries: list[dict[str, Any]] = []
    for key, raw in raw_platforms.items():
        if not isinstance(raw, dict) or not raw.get("shared", False):
            continue
        platform_key = str(raw.get("platform") or key)
        spec = PLATFORMS.get(platform_key)
        label = str(raw.get("label") or (spec.label if spec else platform_key.title()))
        username = str(raw.get("username") or "").strip()
        if not username:
            continue
        url = ""
        raw_url = str(raw.get("url") or "").strip()
        if raw_url and platform_key in PLATFORMS:
            try:
                url = normalize_platform_url(platform_key, raw_url)
            except ValueError:
                url = ""
        entries.append(
            {
                "key": str(key),
                "platform": platform_key,
                "label": label[:30],
                "username": username[:80],
                "url": url,
                "emoji": spec.emoji if spec else "🔗",
            }
        )
    entries.sort(key=lambda item: (item["label"].lower(), item["username"].lower()))
    return entries


def _crew_name(profile: dict[str, Any], world: dict[str, Any]) -> str | None:
    crew_id = profile.get("crew_id")
    if not crew_id:
        return None
    crews = world.get("crews")
    if not isinstance(crews, dict):
        return None
    crew = crews.get(str(crew_id))
    if not isinstance(crew, dict):
        return None
    name = str(crew.get("name") or "").strip()
    return name or None


def _grow_summary(profile: dict[str, Any], world: dict[str, Any]) -> str:
    plants = profile.get("plants")
    if not isinstance(plants, list) or not plants:
        return "No active plants"
    now = time.time()
    ready = 0
    for plant in plants:
        if not isinstance(plant, dict):
            continue
        planted_at = float(plant.get("planted_at", 0) or 0)
        try:
            grow_time = float(get_plant_grow_time(profile, world, plant))
        except Exception:
            grow_time = 0
        if grow_time > 0 and now >= planted_at + grow_time:
            ready += 1
    growing = max(0, len(plants) - ready)
    pieces = []
    if ready:
        pieces.append(f"✅ {ready} ready")
    if growing:
        pieces.append(f"🌿 {growing} growing")
    return " • ".join(pieces) or "No active plants"


def _inventory_summary(profile: dict[str, Any]) -> str:
    inventory = profile.get("inventory")
    items = profile.get("items")
    flower = profile.get("flower_stash")
    concentrates = profile.get("concentrates")
    inventory_count = len(inventory) if isinstance(inventory, list) else 0
    item_count = (
        sum(max(0, _safe_int(value)) for value in items.values())
        if isinstance(items, dict)
        else 0
    )
    flower_count = (
        sum(max(0, _safe_int(value)) for value in flower.values())
        if isinstance(flower, dict)
        else 0
    )
    concentrate_count = (
        sum(max(0, _safe_int(value)) for value in concentrates.values())
        if isinstance(concentrates, dict)
        else 0
    )
    return (
        f"{inventory_count + item_count} items • "
        f"{flower_count:,}g flower • {concentrate_count:,}g concentrates"
    )


def _xp_line(profile: dict[str, Any]) -> str:
    level = max(1, _safe_int(profile.get("level"), 1))
    xp = max(0, _safe_int(profile.get("xp")))
    needed = max(1, _safe_int(_xp_needed_for_level(level), 1))
    percent = min(100, int((xp / needed) * 100))
    filled = min(10, max(0, percent // 10))
    bar = "🟦" * filled + "⬜" * (10 - filled)
    return f"**Level {level}** • {xp:,}/{needed:,} XP\n{bar} {percent}%"


class PlatformLinkView(discord.ui.View):
    def __init__(
        self,
        entries: list[dict[str, Any]],
        *,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        row = 0
        count_in_row = 0
        for entry in entries:
            url = str(entry.get("url") or "")
            if not url:
                continue
            if row >= 4:
                break
            self.add_item(
                discord.ui.Button(
                    label=str(entry.get("label") or "Profile")[:80],
                    emoji=str(entry.get("emoji") or "🔗"),
                    style=discord.ButtonStyle.link,
                    url=url,
                    row=row,
                )
            )
            count_in_row += 1
            if count_in_row >= 5:
                row += 1
                count_in_row = 0


class ProfileOwnerView(PlatformLinkView):
    def __init__(
        self,
        cog: "ProfileSignatures",
        owner_id: int,
        guild_id: int,
        entries: list[dict[str, Any]],
    ) -> None:
        super().__init__(entries, timeout=600)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.add_item(_OpenProfileSettingsButton(cog, self.owner_id, self.guild_id, row=4))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the profile owner can change these settings.",
                ephemeral=True,
            )
            return False
        return True


class _OpenProfileSettingsButton(discord.ui.Button):
    def __init__(
        self,
        cog: "ProfileSignatures",
        owner_id: int,
        guild_id: int,
        *,
        row: int,
    ) -> None:
        super().__init__(
            label="Edit Profile & Privacy",
            emoji="⚙️",
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ These settings belong to another user or server.",
                ephemeral=True,
            )
            return
        embed, view = await self.cog.build_settings_panel(
            self.guild_id,
            self.owner_id,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class PlatformEditModal(discord.ui.Modal):
    def __init__(
        self,
        parent: "ProfileSettingsView",
        platform_key: str,
    ) -> None:
        spec = PLATFORMS[platform_key]
        super().__init__(title=f"Edit {spec.label}"[:45])
        self.parent = parent
        self.platform_key = platform_key
        existing = parent.platforms.get(platform_key, {})
        self.username = discord.ui.TextInput(
            label="Username, handle, or account ID",
            default=str(existing.get("username") or "")[:80],
            max_length=80,
            required=True,
        )
        self.profile_url = discord.ui.TextInput(
            label="Official profile URL (optional)",
            default=str(existing.get("url") or "")[:200],
            max_length=200,
            required=False,
            placeholder="Leave blank when the platform has no safe public profile URL",
        )
        self.shared = discord.ui.TextInput(
            label="Show on profile cards? yes or no",
            default="yes" if existing.get("shared", False) else "no",
            max_length=3,
            required=True,
        )
        self.add_item(self.username)
        self.add_item(self.profile_url)
        self.add_item(self.shared)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        share_value = str(self.shared.value).strip().lower()
        if share_value not in {"yes", "no"}:
            await interaction.response.send_message(
                "❌ Enter **yes** or **no** for sharing.",
                ephemeral=True,
            )
            return
        try:
            entry = normalize_platform_entry(
                self.platform_key,
                str(self.username.value),
                str(self.profile_url.value),
                shared=share_value == "yes",
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await self.parent.cog.save_platform(
            self.parent.owner_id,
            self.platform_key,
            entry,
        )
        await self.parent.refresh(interaction)


class CustomPlatformModal(discord.ui.Modal, title="Edit Other Platform"):
    platform_name = discord.ui.TextInput(
        label="Platform name",
        max_length=30,
        required=True,
    )
    username = discord.ui.TextInput(
        label="Username or handle",
        max_length=80,
        required=True,
    )
    shared = discord.ui.TextInput(
        label="Show on profile cards? yes or no",
        default="no",
        max_length=3,
        required=True,
    )

    def __init__(self, parent: "ProfileSettingsView") -> None:
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction) -> None:
        share_value = str(self.shared.value).strip().lower()
        if share_value not in {"yes", "no"}:
            await interaction.response.send_message(
                "❌ Enter **yes** or **no** for sharing.",
                ephemeral=True,
            )
            return
        try:
            entry = normalize_platform_entry(
                "custom",
                str(self.username.value),
                shared=share_value == "yes",
                custom_label=str(self.platform_name.value),
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await self.parent.cog.save_platform(self.parent.owner_id, "custom", entry)
        await self.parent.refresh(interaction)


class PlatformPicker(discord.ui.Select):
    def __init__(self, parent: "ProfileSettingsView") -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=spec.label,
                value=key,
                emoji=spec.emoji,
                description=(
                    "Supports a safe profile link"
                    if spec.hosts
                    else "Username only; no guessed profile links"
                ),
            )
            for key, spec in PLATFORMS.items()
        ]
        super().__init__(
            placeholder="Add or edit a gaming/social account…",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        platform_key = self.values[0]
        if platform_key == "custom":
            await interaction.response.send_modal(CustomPlatformModal(self.parent_view))
            return
        await interaction.response.send_modal(
            PlatformEditModal(self.parent_view, platform_key)
        )


class GlobalVisibilitySelect(discord.ui.Select):
    def __init__(self, parent: "ProfileSettingsView") -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=label,
                value=key,
                default=key in parent.global_visible,
            )
            for key, label in FIELD_LABELS.items()
        ]
        super().__init__(
            placeholder="Choose fields visible by default…",
            options=options,
            min_values=0,
            max_values=len(options),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.update_global_privacy(
            self.parent_view.owner_id,
            visible_fields=set(self.values),
        )
        await self.parent_view.refresh(interaction)


class ServerHiddenFieldsSelect(discord.ui.Select):
    def __init__(self, parent: "ProfileSettingsView") -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=label,
                value=key,
                default=key in parent.server_hidden,
                description="Hide this field in the current server",
            )
            for key, label in FIELD_LABELS.items()
        ]
        super().__init__(
            placeholder="Hide additional fields in this server…",
            options=options,
            min_values=0,
            max_values=len(options),
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.update_server_privacy(
            self.parent_view.guild_id,
            self.parent_view.owner_id,
            hidden_fields=set(self.values),
        )
        await self.parent_view.refresh(interaction)


class RemovePlatformSelect(discord.ui.Select):
    def __init__(self, parent: "ProfileSettingsView") -> None:
        self.parent_view = parent
        options = []
        for key, entry in sorted(parent.platforms.items()):
            platform_key = str(entry.get("platform") or key)
            spec = PLATFORMS.get(platform_key)
            options.append(
                discord.SelectOption(
                    label=str(entry.get("label") or (spec.label if spec else key.title()))[:100],
                    value=key,
                    description=str(entry.get("username") or "")[:100],
                    emoji=spec.emoji if spec else "🔗",
                )
            )
        super().__init__(
            placeholder="Remove a saved platform…",
            options=options[:25],
            min_values=1,
            max_values=1,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.remove_platform(
            self.parent_view.owner_id,
            self.values[0],
        )
        await self.parent_view.refresh(interaction)


class ProfileSettingsView(discord.ui.View):
    def __init__(
        self,
        cog: "ProfileSignatures",
        owner_id: int,
        guild_id: int,
        account: dict[str, Any],
        profile: dict[str, Any],
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        identity = account.get(IDENTITY_KEY)
        raw_platforms = identity.get("platforms") if isinstance(identity, dict) else {}
        self.platforms = dict(raw_platforms) if isinstance(raw_platforms, dict) else {}
        self.global_enabled, self.global_visible = _global_privacy(account)
        self.server_disabled, self.server_hidden = _guild_privacy(profile)

        self.add_item(PlatformPicker(self))
        self.add_item(GlobalVisibilitySelect(self))
        self.add_item(ServerHiddenFieldsSelect(self))
        if self.platforms:
            self.add_item(RemovePlatformSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This profile settings panel belongs to another user or server.",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed, view = await self.cog.build_settings_panel(
            self.guild_id,
            self.owner_id,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(
        label="Toggle Everywhere",
        emoji="🌐",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def toggle_global(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.cog.update_global_privacy(
            self.owner_id,
            signature_enabled=not self.global_enabled,
        )
        await self.refresh(interaction)

    @discord.ui.button(
        label="Toggle This Server",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def toggle_server(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.cog.update_server_privacy(
            self.guild_id,
            self.owner_id,
            signature_disabled=not self.server_disabled,
        )
        await self.refresh(interaction)


class ProfileSignatures(commands.Cog):
    """User-controlled profile cards and non-repetitive live signatures."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._pending: dict[tuple[int, int], asyncio.Task] = {}
        self._channel_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._channel_last_update: dict[tuple[int, int], float] = {}
        self._user_last_update: dict[tuple[int, int], float] = {}
        self._rank_cache: dict[int, tuple[float, dict[int, int]]] = {}
        self._reconciled = False

    def cog_unload(self) -> None:
        for task in list(self._pending.values()):
            task.cancel()
        self._pending.clear()

    def _lock_for(self, guild_id: int, channel_id: int) -> asyncio.Lock:
        key = (int(guild_id), int(channel_id))
        lock = self._channel_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[key] = lock
        return lock

    def _schedule_user_card_cleanup(
        self,
        user_id: int,
        *,
        guild_id: int | None = None,
    ) -> None:
        async def runner() -> None:
            if guild_id is not None:
                await self.remove_user_cards(int(guild_id), int(user_id))
                return
            for guild in list(self.bot.guilds):
                await self.remove_user_cards(guild.id, int(user_id))

        task = asyncio.create_task(
            runner(),
            name=f"profile-signature-privacy-cleanup-{user_id}",
        )

        def report_failure(done: asyncio.Task) -> None:
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                logger.exception(
                    "Could not clean live profile cards after a privacy change for user %s",
                    user_id,
                )

        task.add_done_callback(report_failure)

    async def _get_signature_config(self, guild_id: int) -> dict[str, Any]:
        world = await self.bot.db.get_world(int(guild_id))
        raw = world.get(SIGNATURE_CONFIG_KEY)
        return dict(raw) if isinstance(raw, dict) else {}

    async def save_platform(
        self,
        user_id: int,
        key: str,
        entry: dict[str, Any],
    ) -> None:
        async with self.bot.db.lock:
            account = await self.bot.db.get_account(int(user_id))
            identity = account.setdefault(IDENTITY_KEY, {})
            platforms = identity.setdefault("platforms", {})
            platforms[str(key)] = dict(entry)
            self.bot.db.mark_account_dirty(int(user_id))
        self._schedule_user_card_cleanup(int(user_id))

    async def remove_platform(self, user_id: int, key: str) -> None:
        async with self.bot.db.lock:
            account = await self.bot.db.get_account(int(user_id))
            identity = account.get(IDENTITY_KEY)
            if isinstance(identity, dict):
                platforms = identity.get("platforms")
                if isinstance(platforms, dict):
                    platforms.pop(str(key), None)
                    self.bot.db.mark_account_dirty(int(user_id))
        self._schedule_user_card_cleanup(int(user_id))

    async def update_global_privacy(
        self,
        user_id: int,
        *,
        signature_enabled: bool | None = None,
        visible_fields: set[str] | None = None,
    ) -> None:
        async with self.bot.db.lock:
            account = await self.bot.db.get_account(int(user_id))
            privacy = account.setdefault(GLOBAL_PRIVACY_KEY, {})
            if signature_enabled is not None:
                privacy["signature_enabled"] = bool(signature_enabled)
            if visible_fields is not None:
                privacy["visible_fields"] = sorted(
                    value for value in visible_fields if value in FIELD_LABELS
                )
            self.bot.db.mark_account_dirty(int(user_id))
        self._schedule_user_card_cleanup(int(user_id))

    async def update_server_privacy(
        self,
        guild_id: int,
        user_id: int,
        *,
        signature_disabled: bool | None = None,
        hidden_fields: set[str] | None = None,
    ) -> None:
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(int(guild_id), int(user_id))
            privacy = profile.setdefault(GUILD_PRIVACY_KEY, {})
            if signature_disabled is not None:
                privacy["signature_disabled"] = bool(signature_disabled)
            if hidden_fields is not None:
                privacy["hidden_fields"] = sorted(
                    value for value in hidden_fields if value in FIELD_LABELS
                )
            self.bot.db.mark_profile_dirty(int(guild_id), int(user_id))
        self._schedule_user_card_cleanup(int(user_id), guild_id=int(guild_id))

    async def build_settings_panel(
        self,
        guild_id: int,
        user_id: int,
    ) -> tuple[discord.Embed, ProfileSettingsView]:
        account = await self.bot.db.get_account(int(user_id))
        profile = await self.bot.db.get_profile(int(guild_id), int(user_id))
        global_enabled, global_visible = _global_privacy(account)
        server_disabled, server_hidden = _guild_privacy(profile)

        identity = account.get(IDENTITY_KEY)
        platforms = identity.get("platforms") if isinstance(identity, dict) else {}
        lines = []
        if isinstance(platforms, dict):
            for key, entry in sorted(platforms.items()):
                if not isinstance(entry, dict):
                    continue
                platform_key = str(entry.get("platform") or key)
                spec = PLATFORMS.get(platform_key)
                label = str(entry.get("label") or (spec.label if spec else key.title()))
                emoji = spec.emoji if spec else "🔗"
                username = str(entry.get("username") or "").strip()
                if not username:
                    continue
                state = "🌐 Shared" if entry.get("shared", False) else "🔒 Private"
                link_state = " • linked" if entry.get("url") else " • username only"
                lines.append(f"{emoji} **{label}:** `{username}` — {state}{link_state}")

        embed = discord.Embed(
            title="🪪 Profile & Signature Settings",
            description=(
                "Your platform accounts are global, while this server may hide additional fields. "
                "Platform accounts stay private until you explicitly mark them as shared."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Signature status",
            value=(
                f"Everywhere: **{'Enabled' if global_enabled else 'Disabled'}**\n"
                f"This server: **{'Disabled' if server_disabled else 'Allowed'}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Visible by default",
            value=(
                ", ".join(FIELD_LABELS[key] for key in ALL_PROFILE_FIELDS if key in global_visible)
                or "Nothing"
            ),
            inline=False,
        )
        embed.add_field(
            name="Hidden in this server",
            value=(
                ", ".join(FIELD_LABELS[key] for key in ALL_PROFILE_FIELDS if key in server_hidden)
                or "Nothing extra"
            ),
            inline=False,
        )
        embed.add_field(
            name="Saved platforms",
            value="\n".join(lines[:20]) or "No gaming or social accounts saved yet.",
            inline=False,
        )
        embed.set_footer(
            text="Select a platform to add/edit it. Use the visibility menus for privacy."
        )
        return embed, ProfileSettingsView(self, user_id, guild_id, account, profile)

    async def _rank_for(self, guild_id: int, user_id: int) -> int | None:
        now = time.monotonic()
        cached = self._rank_cache.get(int(guild_id))
        if cached is None or now - cached[0] > 60:
            try:
                rows = await self.bot.db.list_guild_leaderboard(int(guild_id), limit=100)
            except Exception:
                return None
            ranks = {
                int(row_user_id): index
                for index, (row_user_id, _amount) in enumerate(rows, start=1)
            }
            cached = (now, ranks)
            self._rank_cache[int(guild_id)] = cached
        return cached[1].get(int(user_id))

    async def _profile_components(
        self,
        guild: discord.Guild,
        member: discord.Member,
        *,
        server_allowed: set[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], set[str], list[dict[str, Any]]]:
        account = await self.bot.db.get_account(member.id)
        profile = await self.bot.db.get_profile(guild.id, member.id)
        world = await self.bot.db.get_world(guild.id)
        visible = effective_visible_fields(
            account,
            profile,
            server_allowed=server_allowed,
        )
        platforms = shared_platform_entries(account) if "platforms" in visible else []
        return account, profile, world, visible, platforms

    async def build_full_profile(
        self,
        guild: discord.Guild,
        member: discord.Member,
        *,
        viewer_id: int,
    ) -> tuple[discord.Embed, discord.ui.View | None]:
        _account, profile, world, visible, platforms = await self._profile_components(
            guild,
            member,
        )
        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=member.color,
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if "level" in visible:
            embed.add_field(name="⭐ Level & XP", value=_xp_line(profile), inline=False)
        if "crew" in visible:
            embed.add_field(
                name="🧢 Crew",
                value=_crew_name(profile, world) or "No crew",
                inline=True,
            )
        if "grow_status" in visible:
            embed.add_field(
                name="🌱 Grow",
                value=_grow_summary(profile, world),
                inline=True,
            )
        if "wealth" in visible:
            embed.add_field(
                name="💰 Wealth",
                value=(
                    f"Clean: **${max(0, _safe_int(profile.get('grams'))):,}**\n"
                    f"Dirty: **${max(0, _safe_int(profile.get('dirty_cash'))):,}**"
                ),
                inline=True,
            )
        if "inventory" in visible:
            embed.add_field(
                name="🎒 Inventory",
                value=_inventory_summary(profile),
                inline=False,
            )
        if "rank" in visible:
            rank = await self._rank_for(guild.id, member.id)
            if rank is not None:
                embed.add_field(name="🏆 Server Rank", value=f"#{rank}", inline=True)
        if "achievements" in visible:
            achievements = profile.get("achievements")
            count = len(achievements) if isinstance(achievements, list) else 0
            embed.add_field(name="🏅 Achievements", value=str(count), inline=True)
        if "activity" in visible:
            embed.add_field(
                name="📈 Activity",
                value=(
                    f"Daily streak: **{max(0, _safe_int(profile.get('daily_streak')))}**\n"
                    f"Prestige: **{max(0, _safe_int(profile.get('prestige')))}**"
                ),
                inline=True,
            )
        if platforms:
            embed.add_field(
                name="🎮 Platforms",
                value="\n".join(
                    f"{entry['emoji']} **{entry['label']}:** `{entry['username']}`"
                    for entry in platforms
                )[:1024],
                inline=False,
            )
        if not embed.fields:
            embed.description = "This player keeps their profile details private."

        if viewer_id == member.id:
            return embed, ProfileOwnerView(self, member.id, guild.id, platforms)
        if any(entry.get("url") for entry in platforms):
            return embed, PlatformLinkView(platforms, timeout=None)
        return embed, None

    async def _build_signature(
        self,
        guild: discord.Guild,
        member: discord.Member,
        config: dict[str, Any],
    ) -> tuple[discord.Embed, discord.ui.View | None, str] | None:
        raw_allowed = config.get(SIGNATURE_ALLOWED_FIELDS_KEY, DEFAULT_SERVER_ALLOWED_FIELDS)
        server_allowed = {
            str(value)
            for value in raw_allowed
            if str(value) in FIELD_LABELS
        }
        _account, profile, world, visible, platforms = await self._profile_components(
            guild,
            member,
            server_allowed=server_allowed,
        )
        if not visible:
            return None

        lines: list[str] = []
        if "level" in visible:
            level = max(1, _safe_int(profile.get("level"), 1))
            xp = max(0, _safe_int(profile.get("xp")))
            needed = max(1, _safe_int(_xp_needed_for_level(level), 1))
            lines.append(f"⭐ **Level {level}** • {xp:,}/{needed:,} XP")
        if "crew" in visible:
            crew = _crew_name(profile, world)
            if crew:
                lines.append(f"🧢 **Crew:** {crew}")
        if "grow_status" in visible:
            lines.append(f"🌱 **Grow:** {_grow_summary(profile, world)}")
        if "wealth" in visible:
            total = max(0, _safe_int(profile.get("grams"))) + max(
                0, _safe_int(profile.get("dirty_cash"))
            )
            lines.append(f"💰 **Net worth:** ${total:,}")
        if "inventory" in visible:
            lines.append(f"🎒 **Inventory:** {_inventory_summary(profile)}")
        if "rank" in visible:
            rank = await self._rank_for(guild.id, member.id)
            if rank is not None:
                lines.append(f"🏆 **Server rank:** #{rank}")
        if "achievements" in visible:
            achievements = profile.get("achievements")
            count = len(achievements) if isinstance(achievements, list) else 0
            lines.append(f"🏅 **Achievements:** {count}")
        if "activity" in visible:
            lines.append(
                f"📈 **Daily streak:** {max(0, _safe_int(profile.get('daily_streak')))}"
            )
        if platforms:
            lines.append(
                "🎮 "
                + " • ".join(
                    f"**{entry['label']}:** `{entry['username']}`"
                    for entry in platforms[:6]
                )
            )
        if not lines:
            return None

        embed = discord.Embed(
            description="\n".join(lines)[:4000],
            color=member.color,
        )
        embed.set_author(
            name=member.display_name,
            icon_url=member.display_avatar.url,
        )
        embed.set_footer(text=SIGNATURE_MARKER)

        fingerprint_payload = {
            "user_id": member.id,
            "name": member.display_name,
            "avatar": str(member.display_avatar.url),
            "description": embed.description,
            "platforms": platforms,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        view = (
            PlatformLinkView(platforms, timeout=None)
            if any(entry.get("url") for entry in platforms)
            else None
        )
        return embed, view, fingerprint

    @commands.hybrid_command(
        name="profile-settings",
        aliases=["profilesettings"],
        description="Privately edit profile platforms and privacy",
    )
    @commands.guild_only()
    async def profile_settings(self, ctx: commands.Context) -> None:
        try:
            guild_id = require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return
        if ctx.interaction is None:
            await ctx.send(
                "🔒 Profile settings are private. Use `/profile-settings` in the server."
            )
            return
        embed, view = await self.build_settings_panel(guild_id, ctx.author.id)
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            message.guild is None
            or not isinstance(message.author, discord.Member)
            or message.author.bot
            or message.webhook_id is not None
            or not isinstance(message.channel, discord.TextChannel)
            or message.type not in {discord.MessageType.default, discord.MessageType.reply}
        ):
            return

        config = await self._get_signature_config(message.guild.id)
        if not config.get(SIGNATURE_ENABLED_KEY, False):
            return
        configured_ids = {
            _safe_int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        }
        if message.channel.id not in configured_ids:
            return

        context = await self.bot.get_context(message)
        if context.valid:
            return

        key = (message.guild.id, message.channel.id)
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(
            self._debounced_refresh(message),
            name=f"profile-signature-{message.guild.id}-{message.channel.id}",
        )
        self._pending[key] = task

        def _remove(done: asyncio.Task) -> None:
            if self._pending.get(key) is done:
                self._pending.pop(key, None)

        task.add_done_callback(_remove)

    async def _debounced_refresh(self, message: discord.Message) -> None:
        try:
            await asyncio.sleep(SIGNATURE_DEBOUNCE_SECONDS)
            await self._refresh_signature(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Live profile signature failed guild=%s channel=%s",
                getattr(message.guild, "id", None),
                getattr(message.channel, "id", None),
            )
            reporter = getattr(self.bot, "report_command_error", None)
            if callable(reporter) and message.guild is not None:
                await reporter(
                    guild_id=message.guild.id,
                    title="Live profile signature failure",
                    description=(
                        f"channel={message.channel.id} "
                        f"error={type(exc).__name__}. No user profile data was included."
                    ),
                )

    async def _fetch_owned_signature(
        self,
        channel: discord.TextChannel,
        message_id: int,
    ) -> discord.Message | None:
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            return None
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return None
        if not message.embeds:
            return None
        footer = message.embeds[0].footer.text or ""
        return message if footer == SIGNATURE_MARKER else None

    async def _clear_state(self, guild_id: int, channel_id: int) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            raw_state = world.get(SIGNATURE_STATE_KEY)
            if isinstance(raw_state, dict) and str(channel_id) in raw_state:
                raw_state.pop(str(channel_id), None)
                self.bot.db.mark_world_dirty(int(guild_id))

    async def _store_state(
        self,
        guild_id: int,
        channel_id: int,
        *,
        message_id: int,
        user_id: int,
        fingerprint: str,
        updated_at: float,
    ) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            state = world.setdefault(SIGNATURE_STATE_KEY, {})
            state[str(channel_id)] = {
                "message_id": int(message_id),
                "user_id": int(user_id),
                "fingerprint": str(fingerprint),
                "updated_at": float(updated_at),
            }
            self.bot.db.mark_world_dirty(int(guild_id))

    async def _refresh_signature(self, trigger: discord.Message) -> None:
        guild = trigger.guild
        channel = trigger.channel
        member = trigger.author
        if (
            guild is None
            or not isinstance(channel, discord.TextChannel)
            or not isinstance(member, discord.Member)
        ):
            return

        key = (guild.id, channel.id)
        async with self._lock_for(*key):
            config = await self._get_signature_config(guild.id)
            if not config.get(SIGNATURE_ENABLED_KEY, False):
                return
            configured_ids = {
                _safe_int(value)
                for value in config.get(SIGNATURE_CHANNELS_KEY, [])
                if _safe_int(value) > 0
            }
            if channel.id not in configured_ids or guild.me is None:
                return
            permissions = channel.permissions_for(guild.me)
            if not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
                and permissions.read_message_history
            ):
                return

            built = await self._build_signature(guild, member, config)
            if built is None:
                return
            embed, view, fingerprint = built

            world = await self.bot.db.get_world(guild.id)
            raw_state = world.get(SIGNATURE_STATE_KEY)
            state = (
                dict(raw_state.get(str(channel.id), {}))
                if isinstance(raw_state, dict)
                and isinstance(raw_state.get(str(channel.id)), dict)
                else {}
            )
            monotonic_now = time.monotonic()
            epoch_now = time.time()
            prior_user_id = _safe_int(state.get("user_id"))
            prior_fingerprint = str(state.get("fingerprint") or "")
            prior_updated = float(state.get("updated_at", 0) or 0)

            old_message = None
            old_message_id = _safe_int(state.get("message_id"))
            if old_message_id > 0:
                old_message = await self._fetch_owned_signature(channel, old_message_id)

            if (
                old_message is not None
                and channel.last_message_id == old_message.id
                and prior_user_id == member.id
                and prior_fingerprint == fingerprint
            ):
                return

            if (
                old_message is not None
                and prior_user_id == member.id
                and prior_fingerprint == fingerprint
                and epoch_now - prior_updated < SIGNATURE_SAME_SPEAKER_REFRESH_SECONDS
            ):
                return

            channel_wait = SIGNATURE_CHANNEL_COOLDOWN_SECONDS - (
                monotonic_now - self._channel_last_update.get(key, 0)
            )
            user_key = (guild.id, member.id)
            user_wait = SIGNATURE_USER_COOLDOWN_SECONDS - (
                monotonic_now - self._user_last_update.get(user_key, 0)
            )
            delay = max(0.0, channel_wait, user_wait)
            if delay:
                await asyncio.sleep(delay)

            if old_message is not None:
                try:
                    await old_message.delete()
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    return

            try:
                sent = await channel.send(
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.DiscordException:
                await self._clear_state(guild.id, channel.id)
                return

            recorded_monotonic = time.monotonic()
            recorded_epoch = time.time()
            self._channel_last_update[key] = recorded_monotonic
            self._user_last_update[user_key] = recorded_monotonic
            await self._store_state(
                guild.id,
                channel.id,
                message_id=sent.id,
                user_id=member.id,
                fingerprint=fingerprint,
                updated_at=recorded_epoch,
            )

    async def remove_user_cards(self, guild_id: int, user_id: int) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        for channel_id, descriptor in state.items():
            if not isinstance(descriptor, dict):
                continue
            if _safe_int(descriptor.get("user_id")) != int(user_id):
                continue
            channel = guild.get_channel(_safe_int(channel_id))
            if isinstance(channel, discord.TextChannel):
                message = await self._fetch_owned_signature(
                    channel,
                    _safe_int(descriptor.get("message_id")),
                )
                if message is not None:
                    try:
                        await message.delete()
                    except discord.DiscordException:
                        pass
            await self._clear_state(guild.id, _safe_int(channel_id))

    async def sync_guild_configuration(self, guild: discord.Guild) -> None:
        config = await self._get_signature_config(guild.id)
        enabled = bool(config.get(SIGNATURE_ENABLED_KEY, False))
        configured_ids = {
            _safe_int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        }
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        for channel_id, descriptor in state.items():
            resolved_channel_id = _safe_int(channel_id)
            if enabled and resolved_channel_id in configured_ids:
                continue
            if isinstance(descriptor, dict):
                channel = guild.get_channel(resolved_channel_id)
                if isinstance(channel, discord.TextChannel):
                    message = await self._fetch_owned_signature(
                        channel,
                        _safe_int(descriptor.get("message_id")),
                    )
                    if message is not None:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
            await self._clear_state(guild.id, resolved_channel_id)
        if enabled:
            await self.reconcile_guild(guild)

    async def disable_guild(self, guild: discord.Guild) -> None:
        for key, task in list(self._pending.items()):
            if key[0] == guild.id:
                task.cancel()
                self._pending.pop(key, None)
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        for channel_id, descriptor in state.items():
            if not isinstance(descriptor, dict):
                continue
            channel = guild.get_channel(_safe_int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue
            message = await self._fetch_owned_signature(
                channel,
                _safe_int(descriptor.get("message_id")),
            )
            if message is not None:
                try:
                    await message.delete()
                except discord.DiscordException:
                    pass
        async with self.bot.db.lock:
            mutable_world = await self.bot.db.get_world(guild.id)
            if SIGNATURE_STATE_KEY in mutable_world:
                mutable_world.pop(SIGNATURE_STATE_KEY, None)
                self.bot.db.mark_world_dirty(guild.id)

    async def reconcile_guild(self, guild: discord.Guild) -> None:
        config = await self._get_signature_config(guild.id)
        if not config.get(SIGNATURE_ENABLED_KEY, False):
            return
        configured_ids = {
            _safe_int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        }
        for channel_id in configured_ids:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel) or guild.me is None:
                continue
            permissions = channel.permissions_for(guild.me)
            if not (
                permissions.view_channel
                and permissions.read_message_history
                and permissions.send_messages
                and permissions.embed_links
            ):
                continue
            cards = []
            try:
                async for message in channel.history(limit=SIGNATURE_HISTORY_SCAN_LIMIT):
                    if self.bot.user is None or message.author.id != self.bot.user.id:
                        continue
                    if not message.embeds:
                        continue
                    if (message.embeds[0].footer.text or "") == SIGNATURE_MARKER:
                        cards.append(message)
            except discord.DiscordException:
                continue

            cards.sort(key=lambda message: message.id, reverse=True)
            keep = cards[0] if cards else None
            for duplicate in cards[1:]:
                try:
                    await duplicate.delete()
                except discord.DiscordException:
                    pass

            if keep is None:
                await self._clear_state(guild.id, channel.id)
                continue

            world = await self.bot.db.get_world(guild.id)
            raw_state = world.get(SIGNATURE_STATE_KEY)
            current = (
                raw_state.get(str(channel.id), {})
                if isinstance(raw_state, dict)
                else {}
            )
            await self._store_state(
                guild.id,
                channel.id,
                message_id=keep.id,
                user_id=_safe_int(current.get("user_id")),
                fingerprint=str(current.get("fingerprint") or ""),
                updated_at=float(current.get("updated_at", 0) or 0),
            )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._reconciled:
            return
        self._reconciled = True
        for guild in list(self.bot.guilds):
            try:
                await self.reconcile_guild(guild)
            except Exception:
                logger.exception(
                    "Could not reconcile profile signatures for guild %s",
                    guild.id,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileSignatures(bot))
