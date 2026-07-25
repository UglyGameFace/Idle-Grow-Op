from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_social_uses_explicit_active_scope_storage_paths():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_multiplayer" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source
    assert "db_manager" not in source


def test_social_support_rewards_follow_the_rewarded_users_active_save():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "if message.guild is None" in source
    assert "reward_scope = await resolve_game_scope" in source
    assert "reward_scope.scope_id" in source


def test_social_no_longer_owns_daily_or_sesh_interactions():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert '@commands.hybrid_command(name="daily")' not in source
    assert '@commands.hybrid_command(name="sesh")' not in source
    assert '@commands.hybrid_command(name="movie")' not in source
    assert "class SeshView" not in source
    assert "_ACTIVE_SESHES" not in source


def test_social_crew_and_district_state_use_the_active_multiplayer_world():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "def get_crews(world: dict)" in source
    assert 'district = world.setdefault("district", {})' in source
    assert 'require_multiplayer(scope, "crew")' in source
    assert 'require_multiplayer(scope, "district")' in source
