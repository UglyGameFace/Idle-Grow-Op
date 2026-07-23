from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lab_uses_only_guild_scoped_profiles_and_worlds():
    source = (ROOT / "lab.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.get_profile(guild_id, ctx.author.id)" in source
    assert "await self.bot.db.get_world(guild_id)" in source
    assert "self.bot.db.get_user(" not in source
    assert "db_manager" not in source
    assert "self.bot.db.world_state" not in source
    assert "await self.bot.db.save()" not in source


def test_lab_market_value_requires_an_explicit_guild_world():
    source = (ROOT / "lab.py").read_text(encoding="utf-8")

    assert "def _lab_market_value(user, world, base_value):" in source
    assert "_lab_market_value(player, world, base_total)" in source


def test_lab_mutations_mark_only_the_current_profile_dirty():
    source = (ROOT / "lab.py").read_text(encoding="utf-8")

    assert source.count("self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)") >= 5
    assert "mark_world_dirty" not in source
    assert source.count("async with self.bot.db.lock:") >= 5
