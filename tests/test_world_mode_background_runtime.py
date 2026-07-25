import asyncio

from tasks import Tasks, _WorldGuildProxy
from world_modes import (
    MODE_OPEN,
    OPEN_WORLD_SCOPE_ID,
    PLAYER_MODE_SELECTION_KEY,
    POLICY_CHOICE,
    POLICY_OPEN,
    POLICY_SERVER,
    POLICY_SOLO,
    new_world_mode_config,
)


class FakeGuild:
    def __init__(self, guild_id, members=()):
        self.id = int(guild_id)
        self.name = f"Guild {guild_id}"
        self._members = {int(user_id): object() for user_id in members}

    def get_member(self, user_id):
        return self._members.get(int(user_id))

    def get_channel(self, _channel_id):
        return None


class FakeDatabase:
    def __init__(self):
        self.worlds = {}
        self.profiles = {}
        self.lock = asyncio.Lock()
        self.dirty_worlds = set()

    async def get_world(self, scope_id):
        return self.worlds.setdefault(int(scope_id), {})

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))


class FakeBot:
    def __init__(self, database, guilds):
        self.db = database
        self.guilds = list(guilds)


def configured_world(policy):
    return {
        "world_mode_config": {
            **new_world_mode_config(),
            "policy": policy,
            "configured": True,
        }
    }


def test_active_cycle_guilds_separates_local_and_shared_policies():
    async def scenario():
        database = FakeDatabase()
        guilds = [
            FakeGuild(101),
            FakeGuild(102),
            FakeGuild(103),
            FakeGuild(104),
        ]
        database.worlds[101] = configured_world(POLICY_SOLO)
        database.worlds[102] = configured_world(POLICY_OPEN)
        database.worlds[103] = configured_world(POLICY_CHOICE)
        database.worlds[104] = configured_world(POLICY_SERVER)

        cog = Tasks(FakeBot(database, guilds))
        local, opened = await cog._active_cycle_guilds()

        assert [guild.id for guild in local] == [101, 103, 104]
        assert [guild.id for guild in opened] == [102, 103]

    asyncio.run(scenario())


def test_open_world_proxy_resolves_only_an_actively_open_player_save():
    async def scenario():
        database = FakeDatabase()
        choice_guild = FakeGuild(201, members=(7, 8))
        database.worlds[201] = configured_world(POLICY_CHOICE)
        database.profiles[(201, 7)] = {
            PLAYER_MODE_SELECTION_KEY: {
                "mode": MODE_OPEN,
                "selected_at": 1,
                "switch_available_at": 2,
                "explicit": True,
            }
        }
        database.profiles[(201, 8)] = {
            PLAYER_MODE_SELECTION_KEY: {
                "mode": "solo",
                "selected_at": 1,
                "switch_available_at": 2,
                "explicit": True,
            }
        }

        proxy = _WorldGuildProxy(choice_guild, OPEN_WORLD_SCOPE_ID, [choice_guild])
        open_scope = await proxy.resolve_player_scope(database, 7)
        solo_scope = await proxy.resolve_player_scope(database, 8)

        assert open_scope is not None
        assert open_scope.scope_id == OPEN_WORLD_SCOPE_ID
        assert open_scope.mode == MODE_OPEN
        assert solo_scope is None

    asyncio.run(scenario())


def test_open_world_routing_copies_only_the_selected_guild_channel_settings():
    async def scenario():
        database = FakeDatabase()
        guild = FakeGuild(301)
        database.worlds[301] = {
            **configured_world(POLICY_OPEN),
            "settings": {
                "announcement_channel_id": 123,
                "game_channel_id": 456,
            },
        }
        database.worlds[OPEN_WORLD_SCOPE_ID] = {
            "settings": {
                "announcement_channel_id": 999,
                "unrelated": True,
            }
        }

        cog = Tasks(FakeBot(database, [guild]))
        await cog._sync_open_world_routing(guild)
        settings = database.worlds[OPEN_WORLD_SCOPE_ID]["settings"]

        assert settings["announcement_channel_id"] == 123
        assert settings["game_channel_id"] == 456
        assert settings["unrelated"] is True
        assert OPEN_WORLD_SCOPE_ID in database.dirty_worlds

    asyncio.run(scenario())
