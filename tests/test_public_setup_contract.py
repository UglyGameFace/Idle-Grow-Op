from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SOURCE = (ROOT / "setup.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


def test_setup_is_public_manage_server_ui_without_channel_ids():
    assert '@commands.hybrid_command(name="setup"' in SETUP_SOURCE
    assert "@app_commands.default_permissions(manage_guild=True)" in SETUP_SOURCE
    assert "Manage Server" in SETUP_SOURCE
    assert "discord.ui.ChannelSelect" in SETUP_SOURCE
    assert "discord.ChannelType.text" in SETUP_SOURCE
    assert "discord.ChannelType.news" in SETUP_SOURCE
    assert "channel_id:" not in SETUP_SOURCE.split("async def setup_command", 1)[1]


def test_error_log_configuration_is_guild_world_scoped():
    assert 'ERROR_LOG_CHANNEL_KEY = "error_log_channel_id"' in SETUP_SOURCE
    assert "await self.bot.db.get_world(int(guild_id))" in SETUP_SOURCE
    assert "world.setdefault(SETTINGS_KEY, {})" in SETUP_SOURCE
    assert "self.bot.db.mark_world_dirty(int(guild_id))" in SETUP_SOURCE
    assert "settings.pop(ERROR_LOG_CHANNEL_KEY, None)" in SETUP_SOURCE


def test_setup_has_easy_selection_and_recovery_actions():
    assert 'label="Use This Channel"' in SETUP_SOURCE
    assert 'label="Create Log Channel"' in SETUP_SOURCE
    assert 'label="Send Test"' in SETUP_SOURCE
    assert 'label="Disable Logging"' in SETUP_SOURCE
    assert '"idle-grow-logs"' in SETUP_SOURCE
    assert "guild.create_text_channel" in SETUP_SOURCE


def test_setup_only_accepts_channels_that_can_receive_normal_embeds():
    assert "isinstance(resolved, discord.TextChannel)" in SETUP_SOURCE
    assert "isinstance(channel, discord.TextChannel)" in SETUP_SOURCE
    assert "discord.ForumChannel" not in SETUP_SOURCE


def test_auto_created_log_channel_is_private_but_visible_to_setup_manager():
    assert "guild.default_role: discord.PermissionOverwrite(view_channel=False)" in SETUP_SOURCE
    assert "overwrites[interaction.user]" in SETUP_SOURCE
    assert "view_channel=True" in SETUP_SOURCE
    assert "read_message_history=True" in SETUP_SOURCE


def test_setup_validates_channel_health_before_saving():
    for permission in (
        '"view_channel"',
        '"send_messages"',
        '"embed_links"',
        '"read_message_history"',
    ):
        assert permission in SETUP_SOURCE
    assert "_permission_health(channel, guild.me)" in SETUP_SOURCE
    assert "Missing:" in SETUP_SOURCE


def test_deleted_saved_channel_is_reported_as_unhealthy_not_disabled():
    assert "channel_id = await self.get_error_log_channel_id(guild.id)" in SETUP_SOURCE
    assert "The saved channel was deleted" in SETUP_SOURCE
    assert 'status = "🔴 **Disabled**' in SETUP_SOURCE
    assert 'status = (' in SETUP_SOURCE
    assert '"🟠 **Needs attention**' in SETUP_SOURCE


def test_error_reporting_uses_current_guild_configuration_only():
    assert "ERROR_LOG_CHANNEL_ID" not in MAIN_SOURCE
    assert "os.getenv(\"ERROR_LOG_CHANNEL_ID\"" not in MAIN_SOURCE
    assert "await bot.db.get_world(int(guild_id))" in MAIN_SOURCE
    assert 'world.get("settings", {}).get("error_log_channel_id")' in MAIN_SOURCE
    assert "guild.get_channel(int(channel_id))" in MAIN_SOURCE
    assert "guild_id=interaction.guild_id" in MAIN_SOURCE
    assert "guild_id=guild_id" in MAIN_SOURCE


def test_error_logging_always_keeps_host_log_fallback():
    assert 'logger.error("%s | %s", title, detail)' in MAIN_SOURCE
    assert "Configured error channel is unusable" in MAIN_SOURCE
    assert "Failed to send command error to guild" in MAIN_SOURCE
