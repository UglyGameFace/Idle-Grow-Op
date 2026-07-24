from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_social_uses_only_guild_scoped_storage_paths():
    source = (ROOT / "social.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.get_profile(guild_id" in source
    assert "await self.bot.db.get_world(guild_id)" in source
    assert "self.bot.db.mark_profile_dirty(guild_id" in source
    assert "self.bot.db.mark_world_dirty(guild_id)" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source
    assert "db_manager" not in source


def test_social_support_rewards_are_guild_scoped():
    source = (ROOT / "social.py").read_text(encoding="utf-8")

    assert "if message.guild is None" in source
    assert "guild_id = int(message.guild.id)" in source
    assert "await self.bot.db.get_profile(guild_id, rewarded_user.id)" in source
    assert "self.bot.db.mark_profile_dirty(guild_id, rewarded_user.id)" in source


def test_social_no_longer_owns_daily_or_sesh_interactions():
    source = (ROOT / "social.py").read_text(encoding="utf-8")

    assert '@commands.hybrid_command(name="daily")' not in source
    assert '@commands.hybrid_command(name="sesh")' not in source
    assert '@commands.hybrid_command(name="movie")' not in source
    assert "class SeshView" not in source
    assert "_ACTIVE_SESHES" not in source


def test_social_crew_and_district_state_live_in_the_guild_world():
    source = (ROOT / "social.py").read_text(encoding="utf-8")

    assert "def get_crews(world: dict)" in source
    assert 'district = world.setdefault("district", {})' in source
    assert "get_crews(world)" in source
