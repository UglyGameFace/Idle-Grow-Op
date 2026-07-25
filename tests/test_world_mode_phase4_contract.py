from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_economy_routes_value_and_world_state_through_active_scope():
    text = source("economy.py")
    assert "resolve_game_scope" in text
    assert "require_same_multiplayer_scope" in text
    assert "require_multiplayer" in text
    assert "effective_market_multiplier" in text
    assert "scope.scope_id" in text
    assert "list_guild_leaderboard(scope.scope_id" in text
    assert "_settle_expired_auctions(scope.scope_id" in text
    assert '"transfer"' in text
    assert '"auction"' in text
    assert '"leaderboard"' in text
    assert "mark_profile_dirty(guild_id" not in text
    assert ".get_user(" not in text
    assert "cached_user" not in text


def test_social_routes_crews_districts_and_support_rewards_to_active_scope():
    text = source("social.py")
    assert "resolve_game_scope" in text
    assert "require_multiplayer" in text
    assert "scope.scope_id" in text
    assert 'require_multiplayer(scope, "crew")' in text
    assert 'require_multiplayer(scope, "district")' in text
    assert "reward_scope.scope_id" in text
    assert "await self.bot.db.get_profile(guild_id" not in text
    assert "mark_profile_dirty(guild_id" not in text
    assert ".get_user(" not in text
    assert "cached_owner" not in text


def test_crime_keeps_solo_jobs_but_gates_shared_crime_to_matching_scopes():
    text = source("crime.py")
    assert "resolve_game_scope" in text
    assert "require_multiplayer" in text
    assert "require_same_multiplayer_scope" in text
    assert 'require_multiplayer(scope, "crew_heist")' in text
    assert 'require_multiplayer(scope, "raid")' in text
    assert 'require_same_multiplayer_scope(scope, target_scope, "theft")' in text
    assert "_session_key(scope.scope_id" in text
    assert "list_guild_heist_leaderboard(scope.scope_id" in text
    assert "mark_profile_dirty(guild_id" not in text
    assert ".get_user(" not in text
    assert "cached_user" not in text


def test_server_only_heist_channel_configuration_remains_on_the_real_guild():
    text = source("crime.py")
    heistset = text.split('name="heistset"', 1)[1]
    assert "guild_id = require_guild_id(ctx)" in heistset
    assert "await self.bot.db.get_world(guild_id)" in heistset
    assert "self.bot.db.mark_world_dirty(guild_id)" in heistset
