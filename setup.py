from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from profile_signatures import (
    ALL_PROFILE_FIELDS,
    DEFAULT_SERVER_ALLOWED_FIELDS,
    FIELD_LABELS,
    SIGNATURE_ALLOWED_FIELDS_KEY,
    SIGNATURE_CHANNELS_KEY,
    SIGNATURE_CONFIG_KEY,
    SIGNATURE_ENABLED_KEY,
)


SETTINGS_KEY = "settings"
SESH_CONFIG_KEY = "sesh_config"
AI_CONFIG_KEY = "ai_config"
AI_ENABLED_KEY = "enabled"
ERROR_LOG_CHANNEL_KEY = "error_log_channel_id"
GAME_CHANNEL_KEY = "game_channel_id"
ANNOUNCEMENT_CHANNEL_KEY = "announcement_channel_id"
SESH_ENABLED_KEY = "enabled"
SESH_ALLOW_ALL_KEY = "allow_all_voice_rooms"
SESH_VOICE_CHANNELS_KEY = "voice_channels"
SESH_PING_ROLE_KEY = "ping_role_id"
SESH_PRIVATE_CATEGORY_KEY = "private_category_id"
REQUIRED_CHANNEL_PERMISSIONS = (
    "view_channel",
    "send_messages",
    "embed_links",
    "read_message_history",
)


@dataclass(frozen=True)
class ChannelPurpose:
    key: str
    label: str
    emoji: str
    create_name: str
    description: str
    test_title: str
    test_description: str


GAME_CHANNEL = ChannelPurpose(
    key=GAME_CHANNEL_KEY,
    label="Main Game Channel",
    emoji="🌿",
    create_name="idle-grow",
    description=(
        "The recommended home for Idle Grow commands and community play. "
        "Commands remain usable elsewhere so nobody gets locked out."
    ),
    test_title="🌿 Idle Grow Game Hub Ready",
    test_description="This channel is configured as this server's main Idle Grow play hub.",
)
ANNOUNCEMENT_CHANNEL = ChannelPurpose(
    key=ANNOUNCEMENT_CHANNEL_KEY,
    label="Announcement Channel",
    emoji="📢",
    create_name="idle-grow-news",
    description=(
        "Receives special world-event and major market notices. If disabled, "
        "the configured game channel is used as a safe fallback."
    ),
    test_title="📢 Idle Grow Announcement Test",
    test_description="World events and major market notices can be delivered here.",
)


def _can_manage_guild(member: discord.Member) -> bool:
    return bool(member.guild_permissions.manage_guild or member.guild.owner_id == member.id)


def _permission_health(
    channel: discord.abc.GuildChannel,
    member: discord.Member,
) -> tuple[bool, list[str]]:
    permissions = channel.permissions_for(member)
    missing = [
        name.replace("_", " ").title()
        for name in REQUIRED_CHANNEL_PERMISSIONS
        if not getattr(permissions, name, False)
    ]
    return not missing, missing


class ErrorLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "SetupView") -> None:
        self.setup_view = view
        super().__init__(
            placeholder="Choose an error logging channel…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        resolved = interaction.guild.get_channel(selected.id) if interaction.guild else None
        if not isinstance(resolved, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Choose a text or announcement channel.", ephemeral=True
            )
            return
        await self.setup_view.save_error_channel(interaction, resolved)


class ConfiguredChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "ChannelConfigView") -> None:
        self.config_view = view
        super().__init__(
            placeholder=f"Choose the {view.purpose.label.lower()}…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        channel = interaction.guild.get_channel(selected.id) if interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Choose a text or announcement channel.", ephemeral=True
            )
            return
        await self.config_view.save(interaction, channel)


class OwnedSetupView(discord.ui.View):
    def __init__(self, owner_id: int, guild_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.message: (
            discord.InteractionMessage | discord.WebhookMessage | discord.Message | None
        ) = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the person who opened this setup panel can use it.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This setup panel belongs to another server.", ephemeral=True
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


class ChannelConfigView(OwnedSetupView):
    def __init__(
        self,
        cog: "Setup",
        owner_id: int,
        guild_id: int,
        purpose: ChannelPurpose,
    ) -> None:
        super().__init__(owner_id, guild_id)
        self.cog = cog
        self.purpose = purpose
        self.add_item(ConfiguredChannelSelect(self))

    async def save(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        healthy, missing = _permission_health(channel, guild.me)
        if not healthy:
            await interaction.response.send_message(
                "❌ I cannot use that channel yet. Missing: **"
                + ", ".join(missing)
                + "**.",
                ephemeral=True,
            )
            return
        await self.cog.set_channel_setting(guild.id, self.purpose.key, channel.id)
        await interaction.response.edit_message(
            embed=await self.cog.build_channel_panel(guild, self.purpose),
            view=self,
        )

    @discord.ui.button(
        label="Use This Channel",
        emoji="📍",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def use_current_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Open this panel in a server text or announcement channel.",
                ephemeral=True,
            )
            return
        await self.save(interaction, channel)

    @discord.ui.button(
        label="Create Channel",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def create_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        if not guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                f"❌ I need **Manage Channels** to create `{self.purpose.create_name}`.",
                ephemeral=True,
            )
            return
        channel = discord.utils.get(guild.text_channels, name=self.purpose.create_name)
        if channel is None:
            overwrites = {
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                )
            }
            try:
                channel = await guild.create_text_channel(
                    self.purpose.create_name,
                    overwrites=overwrites,
                    reason=f"Idle Grow setup by {interaction.user}",
                )
            except discord.HTTPException as exc:
                await interaction.response.send_message(
                    f"❌ I could not create the channel: {exc}", ephemeral=True
                )
                return
        await self.save(interaction, channel)

    @discord.ui.button(
        label="Send Test",
        emoji="🧪",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def send_test(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        channel = (
            await self.cog.get_configured_channel(guild, self.purpose.key)
            if guild is not None
            else None
        )
        if channel is None:
            await interaction.response.send_message(
                f"❌ Choose a healthy {self.purpose.label.lower()} first.",
                ephemeral=True,
            )
            return
        try:
            await channel.send(
                embed=discord.Embed(
                    title=self.purpose.test_title,
                    description=self.purpose.test_description,
                    color=discord.Color.green(),
                )
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"❌ The test failed: {exc}", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Test sent to {channel.mention}.", ephemeral=True
        )

    @discord.ui.button(
        label="Disable",
        emoji="🔕",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def disable(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.set_channel_setting(guild.id, self.purpose.key, None)
        await interaction.response.edit_message(
            embed=await self.cog.build_channel_panel(guild, self.purpose),
            view=self,
        )


class SeshVoiceSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "SeshSetupView") -> None:
        self.sesh_view = view
        super().__init__(
            placeholder="Choose specific Sesh voice rooms…",
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
            min_values=1,
            max_values=25,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        channel_ids = []
        for selected in self.values:
            channel = guild.get_channel(selected.id)
            if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                channel_ids.append(channel.id)
        if not channel_ids:
            await interaction.response.send_message(
                "❌ Choose at least one usable voice or stage channel.", ephemeral=True
            )
            return
        await self.sesh_view.cog.update_sesh_config(
            guild.id,
            **{
                SESH_VOICE_CHANNELS_KEY: channel_ids,
                SESH_ALLOW_ALL_KEY: False,
            },
        )
        await self.sesh_view.refresh(interaction)


class SeshRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view: "SeshSetupView") -> None:
        self.sesh_view = view
        super().__init__(
            placeholder="Optional role to ping when a Sesh starts…",
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        role = self.values[0]
        if guild is None or role.is_default():
            await interaction.response.send_message(
                "❌ Choose a normal server role, not @everyone.", ephemeral=True
            )
            return
        await self.sesh_view.cog.update_sesh_config(
            guild.id,
            **{SESH_PING_ROLE_KEY: role.id},
        )
        await self.sesh_view.refresh(interaction)


class SeshCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, view: "SeshSetupView") -> None:
        self.sesh_view = view
        super().__init__(
            placeholder="Optional category for temporary private rooms…",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        selected = self.values[0]
        category = guild.get_channel(selected.id) if guild else None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ Choose a server category.", ephemeral=True
            )
            return
        await self.sesh_view.cog.update_sesh_config(
            guild.id,
            **{SESH_PRIVATE_CATEGORY_KEY: category.id},
        )
        await self.sesh_view.refresh(interaction)


class SeshSetupView(OwnedSetupView):
    def __init__(self, cog: "Setup", owner_id: int, guild_id: int) -> None:
        super().__init__(owner_id, guild_id)
        self.cog = cog
        self.add_item(SeshVoiceSelect(self))
        self.add_item(SeshRoleSelect(self))
        self.add_item(SeshCategorySelect(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_sesh_panel(guild),
            view=self,
        )

    @discord.ui.button(
        label="Enable Sesh",
        emoji="🌿",
        style=discord.ButtonStyle.success,
        row=3,
    )
    async def enable_sesh(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        config = await self.cog.get_sesh_config(guild.id)
        if not config.get(SESH_ALLOW_ALL_KEY) and not config.get(SESH_VOICE_CHANNELS_KEY):
            await interaction.response.send_message(
                "❌ Choose specific voice rooms or press **Allow All Voice Rooms** first.",
                ephemeral=True,
            )
            return
        await self.cog.update_sesh_config(guild.id, **{SESH_ENABLED_KEY: True})
        await self.refresh(interaction)

    @discord.ui.button(
        label="Allow All Voice Rooms",
        emoji="🔊",
        style=discord.ButtonStyle.primary,
        row=3,
    )
    async def allow_all_voice_rooms(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.update_sesh_config(
            guild.id,
            **{
                SESH_ALLOW_ALL_KEY: True,
                SESH_VOICE_CHANNELS_KEY: [],
            },
        )
        await self.refresh(interaction)

    @discord.ui.button(
        label="Disable Sesh",
        emoji="🛑",
        style=discord.ButtonStyle.danger,
        row=3,
    )
    async def disable_sesh(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog.update_sesh_config(guild.id, **{SESH_ENABLED_KEY: False})
        sesh_cog = self.cog.bot.get_cog("Sesh")
        ended = 0
        if sesh_cog is not None and hasattr(sesh_cog, "end_guild_sessions"):
            ended = await sesh_cog.end_guild_sessions(
                guild.id,
                reason="disabled_by_server_manager",
            )
        await interaction.edit_original_response(
            embed=await self.cog.build_sesh_panel(guild),
            view=self,
        )
        await interaction.followup.send(
            f"✅ Sesh disabled. Cleaned up {ended} active session(s).",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Clear Ping Role",
        emoji="🔕",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def clear_ping_role(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.update_sesh_config(guild.id, **{SESH_PING_ROLE_KEY: None})
        await self.refresh(interaction)

    @discord.ui.button(
        label="Disable Private Rooms",
        emoji="🔓",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def clear_private_category(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.update_sesh_config(
            guild.id,
            **{SESH_PRIVATE_CATEGORY_KEY: None},
        )
        await self.refresh(interaction)


class AISetupView(OwnedSetupView):
    def __init__(self, cog: "Setup", owner_id: int, guild_id: int) -> None:
        super().__init__(owner_id, guild_id)
        self.cog = cog

    async def refresh(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_ai_panel(guild),
            view=self,
        )

    @discord.ui.button(
        label="Enable AI",
        emoji="🤖",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def enable_ai(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        ai_cog = self.cog.bot.get_cog("AI")
        if ai_cog is None or not hasattr(ai_cog, "service_health"):
            await interaction.response.send_message(
                "❌ Idle Grow AI is not loaded on the bot host.", ephemeral=True
            )
            return
        healthy, detail = ai_cog.service_health()
        if not healthy:
            await interaction.response.send_message(
                f"❌ Idle Grow AI cannot be enabled yet: **{detail}**.",
                ephemeral=True,
            )
            return
        await self.cog.update_ai_config(guild.id, **{AI_ENABLED_KEY: True})
        await self.refresh(interaction)

    @discord.ui.button(
        label="Test AI",
        emoji="🧪",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def test_ai(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        ai_cog = self.cog.bot.get_cog("AI")
        if ai_cog is None or not hasattr(ai_cog, "request_reply"):
            await interaction.response.send_message(
                "❌ Idle Grow AI is not loaded on the bot host.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await ai_cog.request_reply(
                guild.id,
                "Reply only with: Idle Grow AI is ready.",
                health_test=True,
            )
        except Exception as exc:
            public_message = getattr(
                exc,
                "public_message",
                "❌ Idle Grow AI test failed. Check the configured error log.",
            )
            await interaction.followup.send(public_message, ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Private health test passed. Provider reply: **{reply[:300]}**",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Disable AI",
        emoji="🔕",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def disable_ai(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.update_ai_config(guild.id, **{AI_ENABLED_KEY: False})
        await self.refresh(interaction)



class SignatureChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "SignatureSetupView") -> None:
        self.signature_view = view
        super().__init__(
            placeholder="Choose profile-signature channels…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=25,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        selected_ids: list[int] = []
        missing_by_channel: list[str] = []
        for selected in self.values:
            channel = guild.get_channel(selected.id)
            if not isinstance(channel, discord.TextChannel):
                continue
            healthy, missing = _permission_health(channel, guild.me)
            if healthy:
                selected_ids.append(channel.id)
            else:
                missing_by_channel.append(
                    f"{channel.mention}: {', '.join(missing)}"
                )
        if missing_by_channel:
            await interaction.response.send_message(
                "❌ Fix these channel permissions first:\n"
                + "\n".join(missing_by_channel[:10]),
                ephemeral=True,
            )
            return
        if not selected_ids:
            await interaction.response.send_message(
                "❌ Choose at least one usable text or announcement channel.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        await self.signature_view.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_CHANNELS_KEY: selected_ids},
        )
        signature_cog = self.signature_view.cog.bot.get_cog("ProfileSignatures")
        if signature_cog is not None and hasattr(
            signature_cog, "sync_guild_configuration"
        ):
            await signature_cog.sync_guild_configuration(guild)
        config = await self.signature_view.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.signature_view.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.edit_original_response(
            embed=await self.signature_view.cog.build_signature_panel(guild),
            view=view,
        )


class SignatureFieldSelect(discord.ui.Select):
    def __init__(self, view: "SignatureSetupView", selected: set[str]) -> None:
        self.signature_view = view
        options = [
            discord.SelectOption(
                label=FIELD_LABELS[key],
                value=key,
                default=key in selected,
            )
            for key in ALL_PROFILE_FIELDS
        ]
        super().__init__(
            placeholder="Choose fields permitted in signature cards…",
            options=options,
            min_values=1,
            max_values=len(options),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.signature_view.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_ALLOWED_FIELDS_KEY: list(self.values)},
        )
        await self.signature_view.refresh(interaction)


class SignatureSetupView(OwnedSetupView):
    def __init__(
        self,
        cog: "Setup",
        owner_id: int,
        guild_id: int,
        config: dict,
    ) -> None:
        super().__init__(owner_id, guild_id)
        self.cog = cog
        raw_allowed = config.get(
            SIGNATURE_ALLOWED_FIELDS_KEY,
            DEFAULT_SERVER_ALLOWED_FIELDS,
        )
        selected = {
            str(value)
            for value in raw_allowed
            if str(value) in FIELD_LABELS
        }
        if not selected:
            selected = set(DEFAULT_SERVER_ALLOWED_FIELDS)
        self.add_item(SignatureChannelSelect(self))
        self.add_item(SignatureFieldSelect(self, selected))

    async def refresh(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        config = await self.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.response.edit_message(
            embed=await self.cog.build_signature_panel(guild),
            view=view,
        )
        view.message = self.message

    @discord.ui.button(
        label="Enable Signatures",
        emoji="🪪",
        style=discord.ButtonStyle.success,
        row=2,
    )
    async def enable_signatures(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        healthy_channels = await self.cog.signature_channels(guild)
        if not healthy_channels:
            await interaction.response.send_message(
                "❌ Select at least one healthy signature channel first.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        await self.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_ENABLED_KEY: True},
        )
        signature_cog = self.cog.bot.get_cog("ProfileSignatures")
        if signature_cog is not None and hasattr(
            signature_cog, "sync_guild_configuration"
        ):
            await signature_cog.sync_guild_configuration(guild)
        config = await self.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.edit_original_response(
            embed=await self.cog.build_signature_panel(guild),
            view=view,
        )

    @discord.ui.button(
        label="Use This Channel",
        emoji="📍",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def use_this_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if (
            guild is None
            or guild.me is None
            or not isinstance(channel, discord.TextChannel)
        ):
            await interaction.response.send_message(
                "❌ Open this panel in a server text or announcement channel.",
                ephemeral=True,
            )
            return
        healthy, missing = _permission_health(channel, guild.me)
        if not healthy:
            await interaction.response.send_message(
                "❌ I cannot use this channel yet. Missing: **"
                + ", ".join(missing)
                + "**.",
                ephemeral=True,
            )
            return
        config = await self.cog.get_signature_config(guild.id)
        channel_ids = {
            int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if str(value).isdigit()
        }
        channel_ids.add(channel.id)
        await self.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_CHANNELS_KEY: sorted(channel_ids)},
        )
        await self.refresh(interaction)

    @discord.ui.button(
        label="Disable Signatures",
        emoji="🔕",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def disable_signatures(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_ENABLED_KEY: False},
        )
        signature_cog = self.cog.bot.get_cog("ProfileSignatures")
        if signature_cog is not None and hasattr(signature_cog, "disable_guild"):
            await signature_cog.disable_guild(guild)
        config = await self.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.edit_original_response(
            embed=await self.cog.build_signature_panel(guild),
            view=view,
        )
        await interaction.followup.send(
            "✅ Live profile signatures are disabled and existing bot cards were cleaned up.",
            ephemeral=True,
        )


class SetupView(OwnedSetupView):
    def __init__(self, cog: "Setup", owner_id: int, guild_id: int) -> None:
        super().__init__(owner_id, guild_id)
        self.cog = cog
        self.add_item(ErrorLogChannelSelect(self))

    async def save_error_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        healthy, missing = _permission_health(channel, guild.me)
        if not healthy:
            await interaction.response.send_message(
                "❌ I cannot use that channel yet. Missing: **"
                + ", ".join(missing)
                + "**.",
                ephemeral=True,
            )
            return
        await self.cog.set_channel_setting(guild.id, ERROR_LOG_CHANNEL_KEY, channel.id)
        await interaction.response.edit_message(
            embed=await self.cog.build_panel(guild),
            view=self,
        )

    @discord.ui.button(
        label="Use This Channel",
        emoji="📍",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def use_current_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Open `/setup` in a server text or announcement channel to use this option.",
                ephemeral=True,
            )
            return
        await self.save_error_channel(interaction, channel)

    @discord.ui.button(
        label="Create Log Channel",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def create_log_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        if not guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "❌ I need **Manage Channels** to create `idle-grow-logs`.",
                ephemeral=True,
            )
            return
        channel = discord.utils.get(guild.text_channels, name="idle-grow-logs")
        if channel is None:
            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                ),
            }
            if isinstance(interaction.user, discord.Member):
                overwrites[interaction.user] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                )
            try:
                channel = await guild.create_text_channel(
                    "idle-grow-logs",
                    overwrites=overwrites,
                    reason=f"Idle Grow setup by {interaction.user}",
                )
            except discord.HTTPException as exc:
                await interaction.response.send_message(
                    f"❌ I could not create the channel: {exc}", ephemeral=True
                )
                return
        await self.save_error_channel(interaction, channel)

    @discord.ui.button(
        label="Send Test",
        emoji="🧪",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def send_test(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        channel = (
            await self.cog.get_configured_channel(guild, ERROR_LOG_CHANNEL_KEY)
            if guild is not None
            else None
        )
        if channel is None:
            await interaction.response.send_message(
                "❌ Choose a healthy error logging channel first.", ephemeral=True
            )
            return
        try:
            await channel.send(
                embed=discord.Embed(
                    title="✅ Idle Grow Error Logging Test",
                    description="This server's error logging channel is configured correctly.",
                    color=discord.Color.green(),
                )
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"❌ The test failed: {exc}", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Test sent to {channel.mention}.", ephemeral=True
        )

    @discord.ui.button(
        label="Disable Logging",
        emoji="🔕",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def disable_logging(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        await self.cog.set_channel_setting(guild.id, ERROR_LOG_CHANNEL_KEY, None)
        await interaction.response.edit_message(
            embed=await self.cog.build_panel(guild),
            view=self,
        )

    async def open_channel_panel(
        self,
        interaction: discord.Interaction,
        purpose: ChannelPurpose,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        view = ChannelConfigView(self.cog, interaction.user.id, guild.id, purpose)
        await interaction.response.send_message(
            embed=await self.cog.build_channel_panel(guild, purpose),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    @discord.ui.button(
        label="Game Channel",
        emoji="🌿",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def game_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.open_channel_panel(interaction, GAME_CHANNEL)

    @discord.ui.button(
        label="Announcements",
        emoji="📢",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def announcement_channel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.open_channel_panel(interaction, ANNOUNCEMENT_CHANNEL)

    @discord.ui.button(
        label="Optional Sesh",
        emoji="🔥",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def sesh_setup(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        view = SeshSetupView(self.cog, interaction.user.id, guild.id)
        await interaction.response.send_message(
            embed=await self.cog.build_sesh_panel(guild),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    @discord.ui.button(
        label="Optional AI",
        emoji="🤖",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def ai_setup(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        view = AISetupView(self.cog, interaction.user.id, guild.id)
        await interaction.response.send_message(
            embed=await self.cog.build_ai_panel(guild),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()




    @discord.ui.button(
        label="Profile Signatures",
        emoji="🪪",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def profile_signatures_setup(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
            return
        config = await self.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.response.send_message(
            embed=await self.cog.build_signature_panel(guild),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def set_channel_setting(
        self,
        guild_id: int,
        key: str,
        channel_id: int | None,
    ) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            settings = world.setdefault(SETTINGS_KEY, {})
            if channel_id is None:
                settings.pop(key, None)
            else:
                settings[key] = int(channel_id)
            self.bot.db.mark_world_dirty(int(guild_id))

    async def get_channel_setting_id(self, guild_id: int, key: str) -> int | None:
        world = await self.bot.db.get_world(int(guild_id))
        channel_id = world.get(SETTINGS_KEY, {}).get(key)
        return int(channel_id) if channel_id else None

    async def get_configured_channel(
        self,
        guild: discord.Guild,
        key: str,
    ) -> discord.TextChannel | None:
        channel_id = await self.get_channel_setting_id(guild.id, key)
        if channel_id is None:
            return None
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel) or guild.me is None:
            return None
        healthy, _missing = _permission_health(channel, guild.me)
        return channel if healthy else None

    async def channel_status(self, guild: discord.Guild, key: str) -> str:
        channel_id = await self.get_channel_setting_id(guild.id, key)
        channel = guild.get_channel(channel_id) if channel_id is not None else None
        if channel_id is None:
            return "🔴 **Not configured**"
        if not isinstance(channel, discord.TextChannel):
            return "🟠 **Needs attention** — saved channel was deleted or is unusable"
        if guild.me is None:
            return f"🟡 {channel.mention} — unable to verify permissions"
        healthy, missing = _permission_health(channel, guild.me)
        if healthy:
            return f"🟢 **Healthy** — {channel.mention}"
        return f"🟠 **Needs attention** — {channel.mention}\nMissing: {', '.join(missing)}"

    async def update_sesh_config(self, guild_id: int, **changes: object) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            config = world.setdefault(SESH_CONFIG_KEY, {})
            for key, value in changes.items():
                if value is None:
                    config.pop(key, None)
                else:
                    config[key] = value
            self.bot.db.mark_world_dirty(int(guild_id))

    async def get_sesh_config(self, guild_id: int) -> dict:
        world = await self.bot.db.get_world(int(guild_id))
        return dict(world.get(SESH_CONFIG_KEY, {}))

    async def sesh_status(self, guild: discord.Guild) -> str:
        config = await self.get_sesh_config(guild.id)
        if not config.get(SESH_ENABLED_KEY, False):
            return "⚪ **Optional and disabled**"
        if config.get(SESH_ALLOW_ALL_KEY, False):
            room_status = "all voice rooms"
        else:
            valid_rooms = [
                guild.get_channel(int(channel_id))
                for channel_id in config.get(SESH_VOICE_CHANNELS_KEY, [])
                if str(channel_id).isdigit()
            ]
            valid_rooms = [
                channel
                for channel in valid_rooms
                if isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
            ]
            if not valid_rooms:
                return "🟠 **Needs attention** — enabled without usable voice rooms"
            room_status = f"{len(valid_rooms)} selected voice room(s)"
        return f"🟢 **Enabled** — {room_status}"

    async def build_sesh_panel(self, guild: discord.Guild) -> discord.Embed:
        config = await self.get_sesh_config(guild.id)
        role_id = config.get(SESH_PING_ROLE_KEY)
        role = guild.get_role(int(role_id)) if role_id else None
        role_status = role.mention if role else "No ping role — starts silently"

        category_id = config.get(SESH_PRIVATE_CATEGORY_KEY)
        category = guild.get_channel(int(category_id)) if category_id else None
        if category_id and not isinstance(category, discord.CategoryChannel):
            category_status = "🟠 Saved category was deleted"
        elif isinstance(category, discord.CategoryChannel):
            category_status = f"{category.name} — temporary rooms auto-delete"
        else:
            category_status = "Disabled — no temporary private rooms"

        if config.get(SESH_ALLOW_ALL_KEY, False):
            voice_status = "All server voice rooms"
        else:
            channels = [
                guild.get_channel(int(channel_id))
                for channel_id in config.get(SESH_VOICE_CHANNELS_KEY, [])
                if str(channel_id).isdigit()
            ]
            channels = [
                channel
                for channel in channels
                if isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
            ]
            voice_status = ", ".join(channel.mention for channel in channels[:10]) or "None selected"

        embed = discord.Embed(
            title="🔥 Optional Sesh Setup",
            description=(
                "Sesh is an optional Idle Grow community feature. Nothing is created or "
                "pinged unless a server manager deliberately configures it. Presence-based "
                "XP and Puff & Pass keep it connected to the game."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Status",
            value=await self.sesh_status(guild),
            inline=False,
        )
        embed.add_field(name="Allowed voice rooms", value=voice_status, inline=False)
        embed.add_field(name="Start ping", value=role_status, inline=False)
        embed.add_field(name="Private rooms", value=category_status, inline=False)
        embed.add_field(
            name="Automatic cleanup",
            value=(
                "Only temporary `idle-grow-temp-sesh-*` rooms are deleted. They are cleaned "
                "after ending, expiry, empty timeout, disable, failed activation, or restart. "
                "Permanent server channels, categories, roles, and permissions are never changed."
            ),
            inline=False,
        )
        embed.set_footer(
            text="Select rooms first, then enable. The ping role and private category are optional."
        )
        return embed


    async def update_ai_config(self, guild_id: int, **changes: object) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            config = world.setdefault(AI_CONFIG_KEY, {})
            for key, value in changes.items():
                if value is None:
                    config.pop(key, None)
                else:
                    config[key] = value
            self.bot.db.mark_world_dirty(int(guild_id))

    async def get_ai_config(self, guild_id: int) -> dict:
        world = await self.bot.db.get_world(int(guild_id))
        return dict(world.get(AI_CONFIG_KEY, {}))

    async def ai_status(self, guild: discord.Guild) -> str:
        config = await self.get_ai_config(guild.id)
        if not config.get(AI_ENABLED_KEY, False):
            return "⚪ **Optional and disabled**"
        ai_cog = self.bot.get_cog("AI")
        if ai_cog is None or not hasattr(ai_cog, "service_health"):
            return "🟠 **Needs attention** — AI extension is unavailable"
        healthy, detail = ai_cog.service_health()
        if healthy:
            return f"🟢 **Enabled and healthy** — {detail}"
        return f"🟠 **Needs attention** — {detail}"

    async def build_ai_panel(self, guild: discord.Guild) -> discord.Embed:
        ai_cog = self.bot.get_cog("AI")
        if ai_cog is None or not hasattr(ai_cog, "service_health"):
            service_status = "🔴 AI extension is not loaded"
        else:
            healthy, detail = ai_cog.service_health()
            service_status = ("🟢 " if healthy else "🟠 ") + detail

        embed = discord.Embed(
            title="🤖 Optional Idle Grow AI",
            description=(
                "AI game help is optional per server and disabled by default. The OpenRouter "
                "key and model configuration belong to the bot host; server owners never enter "
                "or see secrets. The assistant cannot grant items, currency, XP, or generate images."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Server status",
            value=await self.ai_status(guild),
            inline=False,
        )
        embed.add_field(name="Provider health", value=service_status, inline=False)
        embed.add_field(
            name="Private test",
            value=(
                "Test AI sends a tiny health prompt through the same request path as `/chat`. "
                "The result is visible only to the manager using this panel."
            ),
            inline=False,
        )
        embed.add_field(
            name="Privacy and errors",
            value=(
                "Provider failures can route to this server's configured error log, but prompts, "
                "responses, API keys, and provider secrets are never included."
            ),
            inline=False,
        )
        embed.set_footer(text="Test first, then enable. Run /setup anytime to disable it again.")
        return embed



    async def update_signature_config(
        self,
        guild_id: int,
        **changes: object,
    ) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            config = world.setdefault(SIGNATURE_CONFIG_KEY, {})
            for key, value in changes.items():
                if value is None:
                    config.pop(key, None)
                else:
                    config[key] = value
            self.bot.db.mark_world_dirty(int(guild_id))

    async def get_signature_config(self, guild_id: int) -> dict:
        world = await self.bot.db.get_world(int(guild_id))
        raw = world.get(SIGNATURE_CONFIG_KEY)
        return dict(raw) if isinstance(raw, dict) else {}

    async def signature_channels(
        self,
        guild: discord.Guild,
    ) -> list[discord.TextChannel]:
        config = await self.get_signature_config(guild.id)
        if guild.me is None:
            return []
        channels: list[discord.TextChannel] = []
        for raw_channel_id in config.get(SIGNATURE_CHANNELS_KEY, []):
            try:
                channel_id = int(raw_channel_id)
            except (TypeError, ValueError):
                continue
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            healthy, _missing = _permission_health(channel, guild.me)
            if healthy:
                channels.append(channel)
        return channels

    async def signature_status(self, guild: discord.Guild) -> str:
        config = await self.get_signature_config(guild.id)
        channel_ids = [
            value
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if str(value).isdigit()
        ]
        if not config.get(SIGNATURE_ENABLED_KEY, False):
            if channel_ids:
                return f"⚪ **Optional and disabled** — {len(channel_ids)} channel(s) selected"
            return "⚪ **Optional and disabled**"
        channels = await self.signature_channels(guild)
        if not channels:
            return "🟠 **Needs attention** — enabled without a usable channel"
        return f"🟢 **Enabled** — {len(channels)} channel(s), one card per channel"

    async def build_signature_panel(self, guild: discord.Guild) -> discord.Embed:
        config = await self.get_signature_config(guild.id)
        channels = await self.signature_channels(guild)
        configured_ids = {
            int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if str(value).isdigit()
        }
        missing_count = max(0, len(configured_ids) - len(channels))
        channel_text = (
            ", ".join(channel.mention for channel in channels[:15])
            or "None selected"
        )
        if missing_count:
            channel_text += f"\n🟠 {missing_count} saved channel(s) missing or unhealthy"

        raw_allowed = config.get(
            SIGNATURE_ALLOWED_FIELDS_KEY,
            DEFAULT_SERVER_ALLOWED_FIELDS,
        )
        allowed = [
            FIELD_LABELS[str(value)]
            for value in raw_allowed
            if str(value) in FIELD_LABELS
        ]
        embed = discord.Embed(
            title="🪪 Live Profile Signatures",
            description=(
                "Keeps one compact Idle Grow profile card for the latest eligible speaker "
                "in each selected channel. It does not alter, delete, or impersonate user messages."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Status",
            value=await self.signature_status(guild),
            inline=False,
        )
        embed.add_field(
            name="Channels",
            value=channel_text,
            inline=False,
        )
        embed.add_field(
            name="Fields this server permits",
            value=", ".join(allowed) or "None",
            inline=False,
        )
        embed.add_field(
            name="Anti-spam behavior",
            value=(
                "One active card per channel. Message bursts are debounced, repeated messages "
                "from the same person do not keep reposting the card, and channel/user cooldowns "
                "limit Discord API traffic."
            ),
            inline=False,
        )
        embed.add_field(
            name="User privacy always wins",
            value=(
                "Players can opt out or hide individual fields with `/profile-settings`. "
                "Platform accounts are private until the player explicitly shares them."
            ),
            inline=False,
        )
        embed.set_footer(
            text="Select channels and permitted fields, then enable. Disabled by default."
        )
        return embed


    async def build_channel_panel(
        self,
        guild: discord.Guild,
        purpose: ChannelPurpose,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{purpose.emoji} {purpose.label}",
            description=purpose.description,
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Current status",
            value=await self.channel_status(guild, purpose.key),
            inline=False,
        )
        embed.set_footer(
            text="Choose a channel, use this channel, create one, test, or disable."
        )
        return embed

    async def build_panel(self, guild: discord.Guild) -> discord.Embed:
        error_status = await self.channel_status(guild, ERROR_LOG_CHANNEL_KEY)
        game_status = await self.channel_status(guild, GAME_CHANNEL_KEY)
        announcement_status = await self.channel_status(guild, ANNOUNCEMENT_CHANNEL_KEY)
        if await self.get_channel_setting_id(guild.id, ANNOUNCEMENT_CHANNEL_KEY) is None:
            if await self.get_configured_channel(guild, GAME_CHANNEL_KEY) is not None:
                announcement_status += "\n↪ Uses the game channel as fallback"

        embed = discord.Embed(
            title="🌿 Idle Grow Server Setup",
            description=(
                "Configure Idle Grow without copying IDs or editing environment variables. "
                "Only server managers can open this panel."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="🌿 Main Game Channel", value=game_status, inline=False)
        embed.add_field(name="📢 Announcements", value=announcement_status, inline=False)
        embed.add_field(name="🚨 Error Logging", value=error_status, inline=False)
        embed.add_field(name="🔥 Optional Sesh", value=await self.sesh_status(guild), inline=False)
        embed.add_field(name="🤖 Optional AI", value=await self.ai_status(guild), inline=False)
        embed.add_field(
            name="🪪 Profile Signatures",
            value=await self.signature_status(guild),
            inline=False,
        )
        embed.add_field(
            name="Coming next",
            value="Multiplayer • Notifications",
            inline=False,
        )
        embed.set_footer(
            text="This private panel expires after 5 minutes. Run /setup anytime to reopen it."
        )
        return embed

    @commands.hybrid_command(name="setup", description="Configure Idle Grow for this server")
    @commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_command(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.author, discord.Member) or not _can_manage_guild(ctx.author):
            await ctx.send(
                "❌ You need **Manage Server** to configure Idle Grow.", ephemeral=True
            )
            return
        view = SetupView(self, ctx.author.id, ctx.guild.id)
        message = await ctx.send(
            embed=await self.build_panel(ctx.guild),
            view=view,
            ephemeral=True,
        )
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
