import asyncio

import discord

from notification_preferences import (
    LAB_READY_KEY,
    NOTIFICATION_CATEGORIES_KEY,
    PLANT_READY_KEY,
    NotificationPreferences,
    NotificationPreferencesCog,
    build_announcement_delivery,
    normalize_notification_preferences,
    toggle_notification_preference,
)
from tasks import Tasks
from world_modes import OPEN_WORLD_SCOPE_ID, POLICY_OPEN, new_world_mode_config


class FakeDatabase:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.worlds = {}
        self.profiles = {}
        self.dirty_profiles = set()
        self.dirty_worlds = set()

    async def get_world(self, scope_id):
        return self.worlds.setdefault(int(scope_id), {})

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))


class FakeBot:
    def __init__(self, database):
        self.db = database


def configured_open_world():
    return {
        "world_mode_config": {
            **new_world_mode_config(),
            "policy": POLICY_OPEN,
            "configured": True,
        }
    }


def test_legacy_boolean_preferences_remain_compatible():
    enabled = normalize_notification_preferences(True)
    disabled = normalize_notification_preferences(False)

    assert enabled == NotificationPreferences(True, True, True)
    assert disabled == NotificationPreferences(False, False, False)
    assert normalize_notification_preferences(None) == enabled


def test_category_toggles_keep_the_legacy_master_boolean_meaningful():
    start = NotificationPreferences(False, False, False)
    plants = toggle_notification_preference(start, PLANT_READY_KEY)
    assert plants == NotificationPreferences(True, True, False)

    lab = toggle_notification_preference(plants, LAB_READY_KEY)
    assert lab == NotificationPreferences(True, True, True)

    all_off = toggle_notification_preference(lab, "all")
    assert all_off == NotificationPreferences(False, False, False)


def test_player_preferences_write_to_the_active_open_world_save():
    async def scenario():
        database = FakeDatabase()
        database.worlds[500] = configured_open_world()
        database.profiles[(OPEN_WORLD_SCOPE_ID, 7)] = {
            "settings": {"notifications": False}
        }
        cog = NotificationPreferencesCog(FakeBot(database))

        scope, updated = await cog.toggle_preference(500, 7, PLANT_READY_KEY)

        assert scope.scope_id == OPEN_WORLD_SCOPE_ID
        assert updated == NotificationPreferences(True, True, False)
        settings = database.profiles[(OPEN_WORLD_SCOPE_ID, 7)]["settings"]
        assert settings["notifications"] is True
        assert settings[NOTIFICATION_CATEGORIES_KEY] == {
            PLANT_READY_KEY: True,
            LAB_READY_KEY: False,
        }
        assert (OPEN_WORLD_SCOPE_ID, 7) in database.dirty_profiles
        assert (500, 7) not in database.profiles

    asyncio.run(scenario())


def test_notification_snapshot_filters_categories_and_commits_only_delivered_work():
    async def scenario():
        database = FakeDatabase()
        profile = {
            "settings": {
                "notifications": True,
                NOTIFICATION_CATEGORIES_KEY: {
                    PLANT_READY_KEY: False,
                    LAB_READY_KEY: True,
                },
            },
            "plants": [
                {"strain": "schwag", "planted_at": 0, "notified": False}
            ],
            "processing_queue": [
                {"finish_time": 0, "notified": False}
            ],
        }
        database.profiles[(900, 11)] = profile
        cog = Tasks(FakeBot(database))

        pending = await cog._notification_snapshot(900, 11, {}, 1000)
        assert pending == ([], [0])

        await cog._commit_notification_flags(
            900,
            11,
            {},
            1000,
            *pending,
        )
        assert profile["plants"][0]["notified"] is False
        assert profile["processing_queue"][0]["notified"] is True
        assert (900, 11) in database.dirty_profiles

    asyncio.run(scenario())


def test_notification_snapshot_preserves_legacy_true_and_false_profiles():
    async def scenario():
        database = FakeDatabase()
        cog = Tasks(FakeBot(database))
        base = {
            "plants": [{"strain": "schwag", "planted_at": 0}],
            "processing_queue": [{"finish_time": 0}],
        }

        database.profiles[(901, 1)] = {
            **base,
            "settings": {"notifications": True},
        }
        database.profiles[(901, 2)] = {
            **base,
            "settings": {"notifications": False},
        }

        assert await cog._notification_snapshot(901, 1, {}, 1000) == ([0], [0])
        assert await cog._notification_snapshot(901, 2, {}, 1000) is None

    asyncio.run(scenario())


class FakePermissions:
    def __init__(self, mention_everyone=False):
        self.mention_everyone = mention_everyone


class FakeMember:
    def __init__(self, mention_everyone=False):
        self.guild_permissions = FakePermissions(mention_everyone)


class FakeRole:
    def __init__(self, role_id, *, mentionable=True, default=False):
        self.id = int(role_id)
        self.mentionable = mentionable
        self._default = default
        self.mention = f"<@&{self.id}>"

    def is_default(self):
        return self._default


class FakeGuild:
    def __init__(self, role=None, *, mention_everyone=False):
        self._role = role
        self.me = FakeMember(mention_everyone)

    def get_role(self, role_id):
        if self._role is not None and self._role.id == int(role_id):
            return self._role
        return None


def test_announcement_delivery_mentions_only_the_selected_role(monkeypatch):
    role = FakeRole(123, mentionable=True)
    guild = FakeGuild(role)

    monkeypatch.setattr(discord, "Role", FakeRole)
    content, allowed = build_announcement_delivery(guild, 123)

    assert content == "<@&123>"
    assert allowed.everyone is False
    assert allowed.users is False
    assert allowed.replied_user is False
    assert allowed.roles == [role]


def test_invalid_announcement_role_falls_back_to_silent_delivery(monkeypatch):
    role = FakeRole(456, mentionable=False)
    guild = FakeGuild(role, mention_everyone=False)

    monkeypatch.setattr(discord, "Role", FakeRole)
    content, allowed = build_announcement_delivery(guild, 456)

    assert content is None
    assert allowed.everyone is False
    assert allowed.users is False
    assert allowed.roles is False
