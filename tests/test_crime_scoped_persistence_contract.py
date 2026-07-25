from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crime_routes_gameplay_through_explicit_active_scopes():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_multiplayer" in source
    assert "require_same_multiplayer_scope" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_crime_sessions_and_rankings_are_active_scope_isolated():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    assert 'return f"scope:{scope_id}:{kind}:{identifier}"' in source
    assert "list_guild_heist_leaderboard(scope.scope_id, limit=10)" in source
    assert "for user_id, data in self.bot.db.data.items()" not in source


def test_heist_channel_configuration_remains_real_guild_scoped():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    block = source.split('name="heistset"', 1)[1]
    assert "await self.bot.db.get_world(guild_id)" in block
    assert "self.bot.db.mark_world_dirty(guild_id)" in block


def test_supabase_has_indexed_heist_win_projection():
    migration = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(encoding="utf-8")
    backend = (ROOT / "supabase_scoped_backend.py").read_text(encoding="utf-8")
    assert "heist_wins bigint generated always as" in migration
    assert "guild_profiles_guild_heist_wins_idx" in migration
    assert "(guild_id, heist_wins desc, user_id)" in migration
    assert 'metric="heist_wins"' in backend
    assert '.eq("guild_id", guild_id)' in backend
    assert '.order(metric, desc=True)' in backend
