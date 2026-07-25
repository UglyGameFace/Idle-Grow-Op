from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


SETTINGS_KEY = "settings"
ERROR_LOG_CHANNEL_KEY = "error_log_channel_id"
REQUIRED_ERROR_LOG_PERMISSIONS = (
    "view_channel",
    "send_messages",
    "embed_links",
    "read_message_history",
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
        for name in REQUIRED_ERROR_LOG_PERMISSIONS
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
        channel = self.values[0]
        resolved = interaction.guild.get_channel(channel.id) if interaction.guild else None
        if not isinstance(resolved, discord.TextChannel):
            return await interaction.response.send_message(
                "❌ Choose a text or announcement channel.", ephemeral=True
            )
        await self.setup_view.save_error_channel(interaction, resolved)


class SetupView(discord.ui.View):
    def __init__(self, cog: "Setup", owner_id: int, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.message: discord.InteractionMessage | discord.WebhookMessage | discord.Message | None = None
        self.add_item(ErrorLogChannelSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the person who opened this setup panel can use it.", ephemeral=True
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

    async def save_error_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            return await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )

        healthy, missing = _permission_health(channel, guild.me)
        if not healthy:
            return await interaction.response.send_message(
                "❌ I cannot use that channel yet. Missing: **" + ", ".join(missing) + "**.",
                ephemeral=True,
            )

        await self.cog.set_error_log_channel(guild.id, channel.id)
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
            return await interaction.response.send_message(
                "❌ Open `/setup` in a server text or announcement channel to use this option.",
                ephemeral=True,
            )
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
            return await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
        if not guild.me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                "❌ I need **Manage Channels** to create `idle-grow-logs`.",
                ephemeral=True,
            )

        existing = discord.utils.get(guild.text_channels, name="idle-grow-logs")
        channel = existing
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
                return await interaction.response.send_message(
                    f"❌ I could not create the channel: {exc}", ephemeral=True
                )
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
        channel = await self.cog.get_error_log_channel(guild) if guild else None
        if channel is None:
            return await interaction.response.send_message(
                "❌ Choose a healthy error logging channel first.", ephemeral=True
            )
        try:
            await channel.send(
                embed=discord.Embed(
                    title="✅ Idle Grow Error Logging Test",
                    description="This server's error logging channel is configured correctly.",
                    color=discord.Color.green(),
                )
            )
        except discord.HTTPException as exc:
            return await interaction.response.send_message(
                f"❌ The test failed: {exc}", ephemeral=True
            )
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
            return await interaction.response.send_message(
                "❌ Server context is unavailable.", ephemeral=True
            )
        await self.cog.set_error_log_channel(self.guild_id, None)
        await interaction.response.edit_message(
            embed=await self.cog.build_panel(guild),
            view=self,
        )


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def set_error_log_channel(self, guild_id: int, channel_id: int | None) -> None:
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(int(guild_id))
            settings = world.setdefault(SETTINGS_KEY, {})
            if channel_id is None:
                settings.pop(ERROR_LOG_CHANNEL_KEY, None)
            else:
                settings[ERROR_LOG_CHANNEL_KEY] = int(channel_id)
            self.bot.db.mark_world_dirty(int(guild_id))

    async def get_error_log_channel_id(self, guild_id: int) -> int | None:
        world = await self.bot.db.get_world(int(guild_id))
        channel_id = world.get(SETTINGS_KEY, {}).get(ERROR_LOG_CHANNEL_KEY)
        return int(channel_id) if channel_id else None

    async def get_error_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.get_error_log_channel_id(guild.id)
        if channel_id is None:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def build_panel(self, guild: discord.Guild) -> discord.Embed:
        channel_id = await self.get_error_log_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id is not None else None

        if channel_id is None:
            status = "🔴 **Disabled**\nChoose a channel, use this channel, or create one automatically."
        elif not isinstance(channel, discord.TextChannel):
            status = (
                "🟠 **Needs attention**\n"
                "The saved channel was deleted or is no longer a usable text channel. Choose another one."
            )
        elif guild.me is None:
            status = f"🟡 {channel.mention}\nUnable to verify permissions right now."
        else:
            healthy, missing = _permission_health(channel, guild.me)
            if healthy:
                status = f"🟢 **Healthy** — {channel.mention}"
            else:
                status = (
                    f"🟠 **Needs attention** — {channel.mention}\n"
                    f"Missing: {', '.join(missing)}"
                )

        embed = discord.Embed(
            title="🌿 Idle Grow Server Setup",
            description=(
                "Configure Idle Grow without copying IDs or editing environment variables. "
                "Only server managers can open this panel."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="🚨 Error Logging", value=status, inline=False)
        embed.add_field(
            name="Coming next",
            value="Game channel • Sesh rooms • Announcements • AI • Multiplayer • Notifications",
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
            return await ctx.send(
                "❌ You need **Manage Server** to configure Idle Grow.", ephemeral=True
            )

        view = SetupView(self, ctx.author.id, ctx.guild.id)
        message = await ctx.send(
            embed=await self.build_panel(ctx.guild),
            view=view,
            ephemeral=True,
        )
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
