from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SOURCE = (ROOT / "setup.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")
TASKS_SOURCE = (ROOT / "tasks.py").read_text(encoding="utf-8")


def test_setup_is_public_manage_server_ui_without_channel_ids():
    assert '@commands.hybrid_command(name="setup"' in SETUP_SOURCE
    assert "@app_commands.default_permissions(manage_guild=True)" in SETUP_SOURCE
    assert "Manage Server" in SETUP_SOURCE
    assert "discord.ui.ChannelSelect" in SETUP_SOURCE
    assert "discord.ChannelType.text" in SETUP_SOURCE
    assert "discord.ChannelType.news" in SETUP_SOURCE
    assert "channel_id:" not in SETUP_SOURCE.split("async def setup_command", 1)[1]


def test_all_channel_configuration_is_guild_world_scoped():
    for key in (
        'ERROR_LOG_CHANNEL_KEY = "error_log_channel_id"',
        'GAME_CHANNEL_KEY = "game_channel_id"',
        'ANNOUNCEMENT_CHANNEL_KEY = "announcement_channel_id"',
    ):
        assert key in SETUP_SOURCE
    assert "await self.bot.db.get_world(int(guild_id))" in SETUP_SOURCE
    assert "world.setdefault(SETTINGS_KEY, {})" in SETUP_SOURCE
    assert "self.bot.db.mark_world_dirty(int(guild_id))" in SETUP_SOURCE
    assert "settings.pop(key, None)" in SETUP_SOURCE
    assert "settings[key] = int(channel_id)" in SETUP_SOURCE


def test_setup_has_easy_selection_and_recovery_actions():
    assert 'label="Use This Channel"' in SETUP_SOURCE
    assert 'label="Create Log Channel"' in SETUP_SOURCE
    assert 'label="Create Channel"' in SETUP_SOURCE
    assert 'label="Send Test"' in SETUP_SOURCE
    assert 'label="Disable Logging"' in SETUP_SOURCE
    assert 'label="Disable"' in SETUP_SOURCE
    assert 'label="Game Channel"' in SETUP_SOURCE
    assert 'label="Announcements"' in SETUP_SOURCE
    assert '"idle-grow-logs"' in SETUP_SOURCE
    assert 'create_name="idle-grow"' in SETUP_SOURCE
    assert 'create_name="idle-grow-news"' in SETUP_SOURCE
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


def test_public_game_and_news_channels_do_not_hide_from_everyone():
    channel_config_block = SETUP_SOURCE.split("class ChannelConfigView", 1)[1].split(
        "class SetupView", 1
    )[0]
    assert "guild.default_role" not in channel_config_block
    assert "guild.me: discord.PermissionOverwrite" in channel_config_block


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


def test_deleted_saved_channels_are_reported_as_unhealthy():
    assert "channel_id = await self.get_channel_setting_id(guild.id, key)" in SETUP_SOURCE
    assert "saved channel was deleted or is unusable" in SETUP_SOURCE
    assert 'return "🔴 **Not configured**"' in SETUP_SOURCE
    assert 'return "🟠 **Needs attention**' in SETUP_SOURCE


def test_game_channel_is_recommended_not_a_command_lock():
    assert "Commands remain usable elsewhere" in SETUP_SOURCE
    assert "@bot.check" not in SETUP_SOURCE
    assert "ctx.channel.id" not in SETUP_SOURCE


def test_announcement_routing_uses_explicit_channel_then_game_fallback():
    assert 'ANNOUNCEMENT_CHANNEL_KEY = "announcement_channel_id"' in TASKS_SOURCE
    assert 'GAME_CHANNEL_KEY = "game_channel_id"' in TASKS_SOURCE
    assert "announcement_id = settings.get(ANNOUNCEMENT_CHANNEL_KEY)" in TASKS_SOURCE
    assert "channel_id = announcement_id or settings.get(GAME_CHANNEL_KEY)" in TASKS_SOURCE
    assert "guild.get_channel(int(channel_id))" in TASKS_SOURCE
    assert "permissions.view_channel" in TASKS_SOURCE
    assert "permissions.send_messages" in TASKS_SOURCE
    assert "permissions.embed_links" in TASKS_SOURCE


def test_world_announcements_are_major_events_not_every_weather_roll():
    assert "MAJOR_MARKET_CHANGE = 0.20" in TASKS_SOURCE
    assert "MARKET_CHANGE_EPSILON" in TASKS_SOURCE
    assert "if not previous_event and current_event:" in TASKS_SOURCE
    assert "if previous_event and not current_event:" in TASKS_SOURCE
    assert "if abs(delta) + MARKET_CHANGE_EPSILON < MAJOR_MARKET_CHANGE:" in TASKS_SOURCE
    assert "return None" in TASKS_SOURCE
    assert "await self._send_world_announcement(guild, announcement)" in TASKS_SOURCE


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
