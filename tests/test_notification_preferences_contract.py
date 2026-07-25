from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
MODULE = (ROOT / "notification_preferences.py").read_text(encoding="utf-8")
SETUP = (ROOT / "setup.py").read_text(encoding="utf-8")
TASKS = (ROOT / "tasks.py").read_text(encoding="utf-8")
MIGRATION = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(
    encoding="utf-8"
)


def test_notification_extension_is_canonical_and_private():
    assert '"notification_preferences"' in MAIN
    assert 'name="notifications"' in MODULE
    assert "@app_commands.guild_only()" in MODULE
    assert "ephemeral=True" in MODULE
    assert "resolve_game_scope" in MODULE
    assert "scope.scope_id" in MODULE


def test_database_boolean_contract_is_preserved_without_a_migration():
    assert 'settings["notifications"] = bool(updated.enabled)' in MODULE
    assert 'NOTIFICATION_CATEGORIES_KEY = "notification_categories"' in MODULE
    assert "settings[NOTIFICATION_CATEGORIES_KEY]" in MODULE
    assert "(data #>> '{settings,notifications}')::boolean" in MIGRATION
    assert "notification_categories" not in MIGRATION


def test_runtime_filters_categories_before_delivery_and_flags_after_send():
    assert "normalize_notification_preferences(" in TASKS
    assert "if preferences.plant_ready:" in TASKS
    assert "if preferences.lab_ready:" in TASKS
    assert TASKS.index("await target.send(") < TASKS.index(
        "await self._commit_notification_flags("
    )


def test_announcement_role_lives_inside_existing_announcement_setup():
    assert "class AnnouncementRoleSelect" in SETUP
    assert "ClearAnnouncementRoleButton" in SETUP
    assert "role.is_default()" in SETUP
    assert "role_is_mentionable_by_bot" in SETUP
    assert "Optional announcement ping" in SETUP
    assert "Test messages never ping" in SETUP
    assert 'label="Announcements"' in SETUP


def test_real_announcements_use_strict_allowed_mentions_and_tests_do_not_ping():
    assert "build_announcement_delivery(" in TASKS
    assert "allowed_mentions=allowed_mentions" in TASKS
    assert "discord.AllowedMentions.none()" in SETUP
    assert "everyone=False" in MODULE
    assert "users=False" in MODULE
    assert "replied_user=False" in MODULE
    assert "@here" not in MODULE
    assert "@everyone" not in TASKS


def test_open_world_routing_copies_the_optional_role_once():
    assert (
        "ANNOUNCEMENT_CHANNEL_KEY, GAME_CHANNEL_KEY, ANNOUNCEMENT_ROLE_KEY"
        in TASKS
    )
