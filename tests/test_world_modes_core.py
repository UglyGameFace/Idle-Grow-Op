import asyncio

import pytest

from scoped_database import make_default_world
from world_modes import (
    DEFAULT_SWITCH_COOLDOWN_SECONDS,
    MODE_OPEN,
    MODE_SERVER,
    MODE_SOLO,
    OPEN_WORLD_SCOPE_ID,
    PLAYER_MODE_SELECTION_KEY,
    POLICY_CHOICE,
    POLICY_OPEN,
    POLICY_SERVER,
    POLICY_SOLO,
    SOLO_MARKET_MULTIPLIER_CAP,
    SOLO_POT_CAP,
    WorldModeDenied,
    WorldModeSwitchCooldown,
    choose_player_mode,
    effective_market_multiplier,
    effective_pot_capacity,
    legacy_world_mode_config,
    new_world_mode_config,
    normalize_world_mode_config,
    require_multiplayer,
    require_same_multiplayer_scope,
    resolve_game_scope,
)


class MemoryDatabase:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.worlds = {}
        self.profiles = {}
        self.dirty_worlds = set()
        self.dirty_profiles = set()

    async def get_world(self, scope_id):
        return self.worlds.setdefault(int(scope_id), {})

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))


def test_new_world_default_is_safe_solo_but_missing_legacy_config_stays_compatible():
    default = make_default_world()
    assert default["world_mode_config"] == new_world_mode_config()
    assert normalize_world_mode_config(default)["policy"] == POLICY_SOLO

    legacy = normalize_world_mode_config({})
    assert legacy == legacy_world_mode_config()
    assert legacy["policy"] == POLICY_SERVER
    assert legacy["legacy_compatibility"] is True


def test_fixed_policies_resolve_to_separate_persistence_scopes():
    async def scenario():
        database = MemoryDatabase()
        guild_id = 123456789012345678
        user_id = 99

        database.worlds[guild_id] = {
            "world_mode_config": {**new_world_mode_config(), "policy": POLICY_SOLO}
        }
        solo = await resolve_game_scope(database, guild_id, user_id)
        assert solo.mode == MODE_SOLO
        assert solo.scope_id == guild_id
        assert solo.multiplayer is False

        database.worlds[guild_id]["world_mode_config"]["policy"] = POLICY_OPEN
        opened = await resolve_game_scope(database, guild_id, user_id)
        assert opened.mode == MODE_OPEN
        assert opened.scope_id == OPEN_WORLD_SCOPE_ID
        assert opened.multiplayer is True
        assert opened.cross_server is True

        database.worlds[guild_id]["world_mode_config"]["policy"] = POLICY_SERVER
        server = await resolve_game_scope(database, guild_id, user_id)
        assert server.mode == MODE_SERVER
        assert server.scope_id == guild_id
        assert server.multiplayer is True

    asyncio.run(scenario())


def test_player_choice_defaults_to_solo_and_never_merges_saves():
    async def scenario():
        database = MemoryDatabase()
        guild_id = 222222222222222222
        user_id = 7
        database.worlds[guild_id] = {
            "world_mode_config": {
                **new_world_mode_config(),
                "policy": POLICY_CHOICE,
                "configured": True,
            }
        }
        database.profiles[(guild_id, user_id)] = {"grams": 500}
        database.profiles[(OPEN_WORLD_SCOPE_ID, user_id)] = {"grams": 9_999}

        default_scope = await resolve_game_scope(database, guild_id, user_id)
        assert default_scope.mode == MODE_SOLO
        assert default_scope.selection_explicit is False
        assert database.profiles[(guild_id, user_id)]["grams"] == 500
        assert database.profiles[(OPEN_WORLD_SCOPE_ID, user_id)]["grams"] == 9_999

        selected = await choose_player_mode(database, guild_id, user_id, MODE_OPEN, now=1_000)
        assert selected.mode == MODE_OPEN
        open_scope = await resolve_game_scope(database, guild_id, user_id)
        assert open_scope.scope_id == OPEN_WORLD_SCOPE_ID
        assert database.profiles[(guild_id, user_id)]["grams"] == 500
        assert database.profiles[(OPEN_WORLD_SCOPE_ID, user_id)]["grams"] == 9_999
        assert database.profiles[(guild_id, user_id)][PLAYER_MODE_SELECTION_KEY]["mode"] == MODE_OPEN

    asyncio.run(scenario())


def test_first_player_choice_is_free_then_switching_has_a_seven_day_cooldown():
    async def scenario():
        database = MemoryDatabase()
        guild_id = 333333333333333333
        user_id = 8
        database.worlds[guild_id] = {
            "world_mode_config": {
                **new_world_mode_config(),
                "policy": POLICY_CHOICE,
                "configured": True,
            }
        }

        first = await choose_player_mode(database, guild_id, user_id, MODE_OPEN, now=10_000)
        assert first.switch_available_at == 10_000 + DEFAULT_SWITCH_COOLDOWN_SECONDS

        with pytest.raises(WorldModeSwitchCooldown) as caught:
            await choose_player_mode(database, guild_id, user_id, MODE_SOLO, now=10_001)
        assert caught.value.remaining_seconds == DEFAULT_SWITCH_COOLDOWN_SECONDS - 1

        switched = await choose_player_mode(
            database,
            guild_id,
            user_id,
            MODE_SOLO,
            now=10_000 + DEFAULT_SWITCH_COOLDOWN_SECONDS,
        )
        assert switched.mode == MODE_SOLO

    asyncio.run(scenario())


def test_player_choice_rejects_selection_when_the_server_policy_is_fixed():
    async def scenario():
        database = MemoryDatabase()
        guild_id = 444444444444444444
        database.worlds[guild_id] = {
            "world_mode_config": {**new_world_mode_config(), "policy": POLICY_SOLO}
        }
        with pytest.raises(WorldModeDenied):
            await choose_player_mode(database, guild_id, 1, MODE_OPEN, now=1)

    asyncio.run(scenario())


def test_multiplayer_gates_require_matching_eligible_scopes():
    async def scenario():
        database = MemoryDatabase()
        guild_a = 555555555555555555
        guild_b = 666666666666666666
        database.worlds[guild_a] = {
            "world_mode_config": {**new_world_mode_config(), "policy": POLICY_OPEN}
        }
        database.worlds[guild_b] = {
            "world_mode_config": {**new_world_mode_config(), "policy": POLICY_OPEN}
        }
        actor = await resolve_game_scope(database, guild_a, 1)
        target = await resolve_game_scope(database, guild_b, 2)
        require_same_multiplayer_scope(actor, target, "transfer")

        database.worlds[guild_b]["world_mode_config"]["policy"] = POLICY_SOLO
        solo_target = await resolve_game_scope(database, guild_b, 2)
        with pytest.raises(WorldModeDenied):
            require_same_multiplayer_scope(actor, solo_target, "transfer")
        with pytest.raises(WorldModeDenied):
            require_multiplayer(solo_target, "auction")

    asyncio.run(scenario())


def test_solo_limits_are_effective_caps_without_destroying_stored_upgrades():
    async def scenario():
        database = MemoryDatabase()
        guild_id = 777777777777777777
        database.worlds[guild_id] = {
            "world_mode_config": {**new_world_mode_config(), "policy": POLICY_SOLO}
        }
        scope = await resolve_game_scope(database, guild_id, 1)
        profile = {"max_pots": 10}
        world = {"market_multiplier": 2.5}
        assert effective_pot_capacity(profile, scope) == SOLO_POT_CAP
        assert profile["max_pots"] == 10
        assert effective_market_multiplier(world, scope) == SOLO_MARKET_MULTIPLIER_CAP
        assert world["market_multiplier"] == 2.5

    asyncio.run(scenario())
