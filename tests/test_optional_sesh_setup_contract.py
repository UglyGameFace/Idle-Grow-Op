from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SOURCE = (ROOT / "setup.py").read_text(encoding="utf-8")
SESH_SOURCE = (ROOT / "sesh.py").read_text(encoding="utf-8")


def test_sesh_is_optional_and_disabled_by_default():
    assert 'SESH_ENABLED_KEY = "enabled"' in SETUP_SOURCE
    assert 'config.get(SESH_ENABLED_KEY, False)' in SETUP_SOURCE
    assert 'Optional and disabled' in SETUP_SOURCE
    assert 'if not bool(config.get(SESH_ENABLED_KEY, False)):' in SESH_SOURCE
    assert 'Sesh is an optional Idle Grow community feature' in SESH_SOURCE
    assert 'disabled for this server' in SESH_SOURCE


def test_setup_requires_explicit_voice_room_scope_before_enabling():
    assert 'label="Optional Sesh"' in SETUP_SOURCE
    assert 'class SeshVoiceSelect' in SETUP_SOURCE
    assert 'label="Allow All Voice Rooms"' in SETUP_SOURCE
    assert 'Choose specific voice rooms or press **Allow All Voice Rooms** first.' in SETUP_SOURCE
    assert 'SESH_ALLOW_ALL_KEY: False' in SETUP_SOURCE
    assert 'SESH_ALLOW_ALL_KEY: True' in SETUP_SOURCE
    assert 'SESH_VOICE_CHANNELS_KEY: []' in SETUP_SOURCE
    assert 'or list(ctx.guild.voice_channels)' not in SESH_SOURCE


def test_ping_role_and_private_category_are_optional_without_here_fallback():
    assert 'class SeshRoleSelect' in SETUP_SOURCE
    assert 'class SeshCategorySelect' in SETUP_SOURCE
    assert 'Clear Ping Role' in SETUP_SOURCE
    assert 'Disable Private Rooms' in SETUP_SOURCE
    assert 'No ping role — starts silently' in SETUP_SOURCE
    assert 'Disabled — no temporary private rooms' in SETUP_SOURCE
    assert '"@here"' not in SESH_SOURCE
    assert 'AllowedMentions' in SESH_SOURCE
    assert 'everyone=False' in SESH_SOURCE


def test_disabling_sesh_ends_all_guild_sessions_and_cleans_temp_rooms():
    assert 'label="Disable Sesh"' in SETUP_SOURCE
    assert 'end_guild_sessions' in SETUP_SOURCE
    assert 'reason="disabled_by_server_manager"' in SETUP_SOURCE
    assert 'async def end_guild_sessions' in SESH_SOURCE
    assert '_evacuate_and_delete_temp_channel' in SESH_SOURCE
    assert 'private_room_expired' in SESH_SOURCE
    assert 'stale restart cleanup' in SESH_SOURCE
    assert 'orphaned temporary Sesh cleanup' in SESH_SOURCE
    assert 'Temporary Sesh activation failed' in SESH_SOURCE


def test_cleanup_only_targets_bot_marked_temporary_rooms():
    assert 'TEMP_CHANNEL_MARKER = "idle-grow-temp-sesh"' in SESH_SOURCE
    assert 'channel.name.startswith(TEMP_CHANNEL_MARKER)' in SESH_SOURCE
    assert 'Only temporary `idle-grow-temp-sesh-*` rooms are deleted.' in SETUP_SOURCE
    assert 'Permanent server channels, categories, roles, and permissions are never changed.' in SETUP_SOURCE
    assert 'guild.create_voice_channel' in SESH_SOURCE
    assert 'guild.create_category' not in SESH_SOURCE
    assert 'role.delete(' not in SESH_SOURCE


def test_sesh_config_is_guild_world_scoped_and_dirty_tracked():
    assert 'SESH_CONFIG_KEY = "sesh_config"' in SETUP_SOURCE
    assert 'world.setdefault(SESH_CONFIG_KEY, {})' in SETUP_SOURCE
    assert 'self.bot.db.mark_world_dirty(int(guild_id))' in SETUP_SOURCE
    assert 'await self.bot.db.get_world(int(guild_id))' in SETUP_SOURCE
    assert 'world.setdefault("sesh_config", {})' in SESH_SOURCE
