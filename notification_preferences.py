from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from world_modes import GameScope, resolve_game_scope


NOTIFICATION_CATEGORIES_KEY = "notification_categories"
PLANT_READY_KEY = "plant_ready"
LAB_READY_KEY = "lab_ready"
ANNOUNCEMENT_ROLE_KEY = "announcement_role_id"


@dataclass(frozen=True, slots=True)
class NotificationPreferences:
    enabled: bool
    plant_ready: bool
    lab_ready: bool

    def category_record(self) -> dict[str, bool]:
        return {
            PLANT_READY_KEY: bool(self.plant_ready),
            LAB_READY_KEY: bool(self.lab_ready),
        }


def normalize_notification_preferences(
    notifications_enabled: Any = True,
    category_settings: Any = None,
) -> NotificationPreferences:
    enabled = notifications_enabled if isinstance(notifications_enabled, bool) else True
    if isinstance(category_settings, dict):
        plant_ready = bool(category_settings.get(PLANT_READY_KEY, enabled))
        lab_ready = bool(category_settings.get(LAB_READY_KEY, enabled))
    else:
        plant_ready = bool(enabled)
        lab_ready = bool(enabled)
    return NotificationPreferences(bool(enabled), plant_ready, lab_ready)


def toggle_notification_preference(
    preferences: NotificationPreferences,
    target: str,
) -> NotificationPreferences:
    if target == "all":
        enabled = not (
            preferences.enabled
            and preferences.plant_ready
            and preferences.lab_ready
        )
        return NotificationPreferences(enabled, enabled, enabled)

    plant_ready = preferences.plant_ready
    lab_ready = preferences.lab_ready
    if target == PLANT_READY_KEY:
        plant_ready = not plant_ready
    elif target == LAB_READY_KEY:
        lab_ready = not lab_ready
    else:
        raise ValueError(f"Unknown notification preference: {target}")

    enabled = bool(plant_ready or lab_ready)
    return NotificationPreferences(enabled, plant_ready, lab_ready)


def role_is_mentionable_by_bot(
    guild: discord.Guild,
    role: discord.Role,
) -> bool:
    if role.is_default():
        return False
    member = guild.me
    permissions = getattr(member, "guild_permissions", None)
    can_mention_all_roles = bool(
        permissions and getattr(permissions, "mention_everyone", False)
    )
    return bool(role.mentionable or can_mention_all_roles)


def resolve_announcement_role(
    guild: discord.Guild,
    role_id: Any,
) -> discord.Role | None:
    try:
        resolved_role_id = int(role_id)
    except (TypeError, ValueError):
        return None
    role = guild.get_role(resolved_role_id)
    if not isinstance(role, discord.Role):
        return None
    return role if role_is_mentionable_by_bot(guild, role) else None


def build_announcement_delivery(
    guild: discord.Guild,
    role_id: Any,
) -> tuple[str | None, discord.AllowedMentions]:
    role = resolve_announcement_role(guild, role_id)
    if role is None:
        return None, discord.AllowedMentions.none()
    return (
        role.mention,
        discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=[role],
            replied_user=False,
        ),
    )


class NotificationPreferencesView(discord.ui.View):
    def __init__(
        self,
        cog: "NotificationPreferencesCog",
        owner_id: int,
        guild_id: int,
        *,
        timeout: float = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the player who opened this panel can use it.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This notification panel belongs to another server.",
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

    async def refresh(self, interaction: discord.Interaction) -> None:
        scope, preferences = await self.cog.get_state(
            self.guild_id,
            self.owner_id,
        )
        view = NotificationPreferencesView(
            self.cog,
            self.owner_id,
            self.guild_id,
        )
        await interaction.response.edit_message(
            embed=self.cog.build_panel(scope, preferences),
            view=view,
        )
        view.message = self.message

    async def toggle(
        self,
        interaction: discord.Interaction,
        target: str,
    ) -> None:
        await self.cog.toggle_preference(
            self.guild_id,
            self.owner_id,
            target,
        )
        await self.refresh(interaction)

    @discord.ui.button(
        label="Toggle All Alerts",
        emoji="📟",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def toggle_all(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.toggle(interaction, "all")

    @discord.ui.button(
        label="Plant Alerts",
        emoji="🌿",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_plants(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.toggle(interaction, PLANT_READY_KEY)

    @discord.ui.button(
        label="Lab Alerts",
        emoji="⚗️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_lab(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.toggle(interaction, LAB_READY_KEY)


class NotificationPreferencesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_state(
        self,
        guild_id: int,
        user_id: int,
    ) -> tuple[GameScope, NotificationPreferences]:
        scope = await resolve_game_scope(self.bot.db, guild_id, user_id)
        profile = await self.bot.db.get_profile(scope.scope_id, int(user_id))
        settings = profile.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        preferences = normalize_notification_preferences(
            settings.get("notifications", True),
            settings.get(NOTIFICATION_CATEGORIES_KEY),
        )
        return scope, preferences

    async def toggle_preference(
        self,
        guild_id: int,
        user_id: int,
        target: str,
    ) -> tuple[GameScope, NotificationPreferences]:
        scope, current = await self.get_state(guild_id, user_id)
        updated = toggle_notification_preference(current, target)
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(scope.scope_id, int(user_id))
            settings = profile.get("settings")
            if not isinstance(settings, dict):
                settings = {}
                profile["settings"] = settings
            settings["notifications"] = bool(updated.enabled)
            settings[NOTIFICATION_CATEGORIES_KEY] = updated.category_record()
            self.bot.db.mark_profile_dirty(scope.scope_id, int(user_id))
        return scope, updated

    @staticmethod
    def build_panel(
        scope: GameScope,
        preferences: NotificationPreferences,
    ) -> discord.Embed:
        status = lambda enabled: "🟢 Enabled" if enabled else "⚪ Disabled"
        embed = discord.Embed(
            title="📟 Private Notification Preferences",
            description=(
                "Choose which ready-work alerts Idle Grow sends by DM. These settings "
                "belong only to the active save shown below."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Active save",
            value=f"{scope.emoji} **{scope.label}**",
            inline=False,
        )
        embed.add_field(
            name="All DM alerts",
            value=status(preferences.enabled),
            inline=True,
        )
        embed.add_field(
            name="Plants ready",
            value=status(preferences.enabled and preferences.plant_ready),
            inline=True,
        )
        embed.add_field(
            name="Lab batches ready",
            value=status(preferences.enabled and preferences.lab_ready),
            inline=True,
        )
        embed.add_field(
            name="Delivery rules",
            value=(
                "Disabled categories are not marked as notified. Re-enabling can alert you "
                "about work that is still ready and has never been delivered."
            ),
            inline=False,
        )
        embed.set_footer(
            text="This private panel expires after 5 minutes. Run /notifications anytime."
        )
        return embed

    @app_commands.command(
        name="notifications",
        description="Manage your private Idle Grow readiness alerts",
    )
    @app_commands.guild_only()
    async def notifications(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "❌ Notifications can only be configured inside a server.",
                ephemeral=True,
            )
            return
        scope, preferences = await self.get_state(guild_id, interaction.user.id)
        view = NotificationPreferencesView(
            self,
            interaction.user.id,
            guild_id,
        )
        await interaction.response.send_message(
            embed=self.build_panel(scope, preferences),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotificationPreferencesCog(bot))
