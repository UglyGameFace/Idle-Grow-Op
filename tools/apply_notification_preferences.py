from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise SystemExit(f"Missing patch anchor: {label}")
    return source.replace(old, new, 1)


ACTIVE_TASK = r'''# Active Task: Notification Preferences and Announcement Roles

## Scope
Add simple, active-save-aware player DM preferences and one optional server announcement ping role without creating another server setup path, pinging broad audiences, or breaking existing notification data.

## Root Cause and Confirmed Findings
- Ready-plant and completed-lab notifications are sent by `tasks.py` as one combined DM after active-save filtering.
- Existing profiles store `settings.notifications` as a boolean.
- Supabase's generated `has_notification_work` column casts `settings.notifications` directly to boolean, so replacing it with an object would break profile writes.
- The normalized notification-candidate query is already indexed by scope and does not require a database migration.
- Notification flags are committed only after a successful DM.
- World-event and major-market announcements already use `/setup` channel configuration with the game channel as a safe fallback.
- Open World copies one participating server's announcement route into the shared world so the shared tick runs and announces once.
- `/profile-settings` is dedicated to public profile identity/privacy and must not become a mixed general-settings panel.

## Architecture Decision
- Add one canonical `notification_preferences.py` extension for preference normalization, private player UI, active-save persistence, and safe allowed-mention construction.
- Add `/notifications` as a private, guild-only player panel for the currently active save.
- Preserve `settings.notifications` as the master boolean for database compatibility.
- Store category choices in sibling `settings.notification_categories` with `plant_ready` and `lab_ready` booleans.
- Legacy `true` means both categories enabled; legacy `false` means both disabled.
- Keep notification flags unchanged for disabled categories. Re-enabling may alert for work that is still ready and has never been delivered.
- Store the optional server role as `settings.announcement_role_id` in the real guild world.
- Keep role selection inside `/setup → Announcements`; do not add a second server setup command.
- A configured role must be a real non-`@everyone` role and mentionable by the bot.
- Real announcement sends use strict `AllowedMentions`: only the selected role may be mentioned; user, broad, and replied-user mentions remain disabled.
- Send Test never pings the announcement role.
- Open World routing synchronizes the selected server's announcement channel, game-channel fallback, and optional announcement role into the shared world once.

## Required Behavior
- Player controls:
  - Toggle all DM alerts.
  - Toggle plant-ready alerts.
  - Toggle lab-batch-ready alerts.
  - Clearly show the active save being configured.
  - All responses and controls remain private.
- Server controls:
  - Select or clear one optional announcement role in the existing Announcements panel.
  - Show missing, deleted, or unmentionable role health plainly.
  - Default to silent announcements when no role is configured.
  - Never ping `@everyone` or `@here`.
- Runtime:
  - Filter each notification category before composing the DM.
  - Do not mark disabled categories as notified.
  - Commit only categories actually delivered.
  - Preserve active-save and one-shared-Open-World behavior.
  - Ping the configured role only for real event or major-market announcements.

## Implementation Status
- Corrected persistence design established.
- Canonical player module and focused regression files added.
- Runtime, setup, extension-list, and CI integration are being applied.

## Validation Requirements
- Preference normalization and legacy-boolean compatibility tests.
- Active-save persistence and private `/notifications` UI contracts.
- Category-specific notification snapshot and commit runtime tests.
- Announcement role selection, clearing, health, and `@everyone` rejection tests.
- Strict allowed-mention tests proving no broad or user pings.
- Open World routing tests including the role ID.
- Python compilation, complete pytest, extension loading, command uniqueness, cleanup, and conflict inspection.

## Cleanup Requirements
- No temporary patch scripts or write-enabled workflows in the final diff.
- No duplicate notification preference or announcement-role config path.
- No database migration or destructive rewrite of existing profile settings.

## Blockers
- None.

## Backlog Locked Behind This Task
- Broader onboarding and first-run guidance.
'''


def patch_main() -> None:
    path = ROOT / "main.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '    "lab",\n    "progression",',
        '    "lab",\n    "notification_preferences",\n    "progression",',
        "main extension list",
    )
    path.write_text(source, encoding="utf-8")


def patch_startup_contract() -> None:
    path = ROOT / "tests/test_startup_contract.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '    "lab",\n    "progression",',
        '    "lab",\n    "notification_preferences",\n    "progression",',
        "startup expected extensions",
    )
    path.write_text(source, encoding="utf-8")


def patch_tasks() -> None:
    path = ROOT / "tasks.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from discord.ext import commands, tasks\n\nfrom utils import",
        "from discord.ext import commands, tasks\n\n"
        "from notification_preferences import (\n"
        "    ANNOUNCEMENT_ROLE_KEY,\n"
        "    NOTIFICATION_CATEGORIES_KEY,\n"
        "    build_announcement_delivery,\n"
        "    normalize_notification_preferences,\n"
        ")\n"
        "from utils import",
        "tasks notification imports",
    )
    source = replace_once(
        source,
        "for key in (ANNOUNCEMENT_CHANNEL_KEY, GAME_CHANNEL_KEY):",
        "for key in (ANNOUNCEMENT_CHANNEL_KEY, GAME_CHANNEL_KEY, ANNOUNCEMENT_ROLE_KEY):",
        "open world routing keys",
    )
    source = replace_once(
        source,
        '''        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            print(f"❌ World announcement failed for scope {guild.id}: {exc}")
''',
        '''        role_id = None
        try:
            world = await self.bot.db.get_world(guild.id)
            role_id = world.get("settings", {}).get(ANNOUNCEMENT_ROLE_KEY)
        except Exception as exc:
            print(f"❌ Announcement role lookup failed for scope {guild.id}: {exc}")

        content, allowed_mentions = build_announcement_delivery(guild, role_id)
        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )
        except discord.HTTPException as exc:
            print(f"❌ World announcement failed for scope {guild.id}: {exc}")
''',
        "announcement role delivery",
    )
    source = replace_once(
        source,
        '''            profile = await self.bot.db.get_profile(scope_id, user_id)
            if not profile.get("settings", {}).get("notifications", True):
                return None

            plant_indexes = []
            for index, plant in enumerate(profile.get("plants", [])):
                if plant.get("notified"):
                    continue
                grow_time = get_plant_grow_time(profile, world, plant)
                if now - float(plant.get("planted_at", now)) >= grow_time:
                    plant_indexes.append(index)

            batch_indexes = []
            for index, item in enumerate(profile.get("processing_queue", [])):
                if item.get("notified"):
                    continue
                if now >= float(item.get("finish_time", now + 1)):
                    batch_indexes.append(index)
''',
        '''            profile = await self.bot.db.get_profile(scope_id, user_id)
            settings = profile.get("settings", {})
            if not isinstance(settings, dict):
                settings = {}
            preferences = normalize_notification_preferences(
                settings.get("notifications", True),
                settings.get(NOTIFICATION_CATEGORIES_KEY),
            )
            if not preferences.enabled:
                return None

            plant_indexes = []
            if preferences.plant_ready:
                for index, plant in enumerate(profile.get("plants", [])):
                    if plant.get("notified"):
                        continue
                    grow_time = get_plant_grow_time(profile, world, plant)
                    if now - float(plant.get("planted_at", now)) >= grow_time:
                        plant_indexes.append(index)

            batch_indexes = []
            if preferences.lab_ready:
                for index, item in enumerate(profile.get("processing_queue", [])):
                    if item.get("notified"):
                        continue
                    if now >= float(item.get("finish_time", now + 1)):
                        batch_indexes.append(index)
''',
        "category notification snapshot",
    )
    path.write_text(source, encoding="utf-8")


def patch_setup() -> None:
    path = ROOT / "setup.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from discord.ext import commands\n\nfrom profile_signatures import",
        "from discord.ext import commands\n\n"
        "from notification_preferences import (\n"
        "    ANNOUNCEMENT_ROLE_KEY,\n"
        "    role_is_mentionable_by_bot,\n"
        ")\n"
        "from profile_signatures import",
        "setup notification imports",
    )

    role_controls = r'''

class AnnouncementRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view: "ChannelConfigView") -> None:
        self.config_view = view
        super().__init__(
            placeholder="Optional role to ping for real announcements…",
            min_values=1,
            max_values=1,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        role = self.values[0]
        if guild is None or role.is_default():
            await interaction.response.send_message(
                "❌ Choose a normal server role, not @everyone.",
                ephemeral=True,
            )
            return
        if not role_is_mentionable_by_bot(guild, role):
            await interaction.response.send_message(
                "❌ I cannot mention that role. Make the role mentionable or update my "
                "server permissions, then try again.",
                ephemeral=True,
            )
            return
        await self.config_view.cog.set_channel_setting(
            guild.id,
            ANNOUNCEMENT_ROLE_KEY,
            role.id,
        )
        await interaction.response.edit_message(
            embed=await self.config_view.cog.build_channel_panel(
                guild,
                self.config_view.purpose,
            ),
            view=self.config_view,
        )


class ClearAnnouncementRoleButton(discord.ui.Button):
    def __init__(self, view: "ChannelConfigView") -> None:
        super().__init__(
            label="Clear Ping Role",
            emoji="🔕",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        self.config_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Server context is unavailable.",
                ephemeral=True,
            )
            return
        await self.config_view.cog.set_channel_setting(
            guild.id,
            ANNOUNCEMENT_ROLE_KEY,
            None,
        )
        await interaction.response.edit_message(
            embed=await self.config_view.cog.build_channel_panel(
                guild,
                self.config_view.purpose,
            ),
            view=self.config_view,
        )
'''
    source = replace_once(
        source,
        "\n\nclass ChannelConfigView(OwnedSetupView):",
        role_controls + "\n\nclass ChannelConfigView(OwnedSetupView):",
        "announcement role controls",
    )
    source = replace_once(
        source,
        '''        self.cog = cog
        self.purpose = purpose
        self.add_item(ConfiguredChannelSelect(self))
''',
        '''        self.cog = cog
        self.purpose = purpose
        self.add_item(ConfiguredChannelSelect(self))
        if self.purpose.key == ANNOUNCEMENT_CHANNEL_KEY:
            self.add_item(AnnouncementRoleSelect(self))
            self.add_item(ClearAnnouncementRoleButton(self))
''',
        "announcement controls in channel panel",
    )
    source = replace_once(
        source,
        '''            await channel.send(
                embed=discord.Embed(
                    title=self.purpose.test_title,
                    description=self.purpose.test_description,
                    color=discord.Color.green(),
                )
            )
''',
        '''            await channel.send(
                embed=discord.Embed(
                    title=self.purpose.test_title,
                    description=self.purpose.test_description,
                    color=discord.Color.green(),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
''',
        "test delivery never pings",
    )
    role_status = r'''
    async def announcement_role_status(self, guild: discord.Guild) -> str:
        role_id = await self.get_channel_setting_id(guild.id, ANNOUNCEMENT_ROLE_KEY)
        if role_id is None:
            return "🔕 **Silent** — no ping role selected"
        role = guild.get_role(role_id)
        if not isinstance(role, discord.Role):
            return "🟠 **Needs attention** — saved role was deleted"
        if role.is_default():
            return "🟠 **Needs attention** — @everyone cannot be used"
        if role_is_mentionable_by_bot(guild, role):
            return f"🟢 **Healthy** — {role.mention}"
        return (
            f"🟠 **Needs attention** — {role.mention} cannot be mentioned by the bot"
        )

'''
    source = replace_once(
        source,
        "    async def update_sesh_config(self, guild_id: int, **changes: object) -> None:",
        role_status
        + "    async def update_sesh_config(self, guild_id: int, **changes: object) -> None:",
        "announcement role status",
    )
    source = replace_once(
        source,
        '''        embed.add_field(
            name="Current status",
            value=await self.channel_status(guild, purpose.key),
            inline=False,
        )
        embed.set_footer(
            text="Choose a channel, use this channel, create one, test, or disable."
        )
''',
        '''        embed.add_field(
            name="Current status",
            value=await self.channel_status(guild, purpose.key),
            inline=False,
        )
        if purpose.key == ANNOUNCEMENT_CHANNEL_KEY:
            embed.add_field(
                name="Optional announcement ping",
                value=await self.announcement_role_status(guild),
                inline=False,
            )
            footer = (
                "Choose a channel and optional role. Test messages never ping the role."
            )
        else:
            footer = "Choose a channel, use this channel, create one, test, or disable."
        embed.set_footer(text=footer)
''',
        "announcement panel role health",
    )
    source = replace_once(
        source,
        '''        if await self.get_channel_setting_id(guild.id, ANNOUNCEMENT_CHANNEL_KEY) is None:
            if await self.get_configured_channel(guild, GAME_CHANNEL_KEY) is not None:
                announcement_status += "\n↪ Uses the game channel as fallback"
''',
        '''        if await self.get_channel_setting_id(guild.id, ANNOUNCEMENT_CHANNEL_KEY) is None:
            if await self.get_configured_channel(guild, GAME_CHANNEL_KEY) is not None:
                announcement_status += "\n↪ Uses the game channel as fallback"
        announcement_status += (
            "\n" + await self.announcement_role_status(guild)
        )
''',
        "main panel announcement role status",
    )
    source = replace_once(
        source,
        '''        embed.add_field(
            name="Coming next",
            value="Notifications",
            inline=False,
        )
''',
        '''        embed.add_field(
            name="📟 Player Notifications",
            value="Players manage private ready-work alerts with `/notifications`.",
            inline=False,
        )
        embed.add_field(
            name="Coming next",
            value="First-run onboarding",
            inline=False,
        )
''',
        "setup main notification guidance",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    (ROOT / "ACTIVE_TASK.md").write_text(ACTIVE_TASK, encoding="utf-8")
    patch_main()
    patch_startup_contract()
    patch_tasks()
    patch_setup()


if __name__ == "__main__":
    main()
