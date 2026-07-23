from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_farming_uses_only_guild_scoped_profiles_and_worlds():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.get_profile(guild_id, ctx.author.id)" in source
    assert "await self.bot.db.get_world(guild_id)" in source
    assert "self.bot.db.get_user(" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_farming_marks_only_the_current_guild_profile_dirty():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")

    assert source.count("self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)") >= 3
    assert "mark_world_dirty" not in source


def test_farming_mutations_run_under_the_database_lock():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")

    assert source.count("async with self.bot.db.lock:") >= 3
    assert "inv_take(user, seed_item_name, 1)" in source
    assert "calculate_harvest_outcome(" in source
