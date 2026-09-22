from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_shared_guild_setting_keys_have_one_definition():
    config = source("guild_config.py")
    setup = source("setup.py")
    tasks = source("tasks.py")
    main = source("main.py")

    for definition in (
        'WORLD_SETTINGS_KEY = "settings"',
        'ERROR_LOG_CHANNEL_KEY = "error_log_channel_id"',
        'GAME_CHANNEL_KEY = "game_channel_id"',
        'ANNOUNCEMENT_CHANNEL_KEY = "announcement_channel_id"',
    ):
        assert definition in config
        assert definition not in setup
        assert definition not in tasks
        assert definition not in main


def test_ai_and_sesh_own_their_subsystem_config_keys():
    ai = source("ai.py")
    sesh = source("sesh.py")
    setup = source("setup.py")

    assert 'AI_CONFIG_KEY = "ai_config"' in ai
    assert 'AI_ENABLED_KEY = "enabled"' in ai
    assert 'SESH_CONFIG_KEY = "sesh_config"' in sesh
    assert 'SESH_ENABLED_KEY = "enabled"' in sesh

    assert 'AI_CONFIG_KEY = "ai_config"' not in setup
    assert 'AI_ENABLED_KEY = "enabled"' not in setup
    assert 'SESH_CONFIG_KEY = "sesh_config"' not in setup
    assert 'SESH_ENABLED_KEY = "enabled"' not in setup
