from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_schema_has_indexed_generated_balance_for_guild_leaderboards():
    sql = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(
        encoding="utf-8"
    )

    assert "balance bigint generated always as" in sql
    assert "data ->> 'grams'" in sql
    assert "guild_profiles_guild_balance_idx" in sql
    assert "(guild_id, balance desc, user_id)" in sql


def test_supabase_leaderboard_is_filtered_sorted_and_limited_in_database():
    source = (ROOT / "supabase_scoped_backend.py").read_text(encoding="utf-8")

    assert 'metric="balance"' in source
    assert 'self.client.table("guild_profiles")' in source
    assert '.select(f"user_id,{metric}")' in source
    assert '.eq("guild_id", guild_id)' in source
    assert '.order(metric, desc=True)' in source
    assert '.limit(limit)' in source


def test_scoped_manager_delegates_leaderboard_without_scanning_cache():
    source = (ROOT / "scoped_database.py").read_text(encoding="utf-8")

    assert "async def list_guild_leaderboard" in source
    assert 'getattr(self.backend, "list_guild_leaderboard", None)' in source
    assert "self.store.cached_keys" not in source
