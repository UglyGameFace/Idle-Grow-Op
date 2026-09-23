from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_farming_uses_only_explicit_active_scope_profiles_and_worlds():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "resolve_game_scope" in source
    assert "await self.bot.db.get_profile(scope.scope_id, ctx.author.id)" in source
    assert "await self.bot.db.get_world(scope.scope_id)" in source
    assert "self.bot.db.get_user(" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_farming_marks_only_real_mutations_dirty_in_the_active_scope():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")
    plant = source.split("async def plant", 1)[1].split("async def harvest", 1)[0]
    harvest = source.split("async def harvest", 1)[1].split("async def status", 1)[0]

    dirty = "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)"
    assert dirty in plant
    assert dirty in harvest
    assert "mark_world_dirty" not in source
    assert "async def water" not in source


def test_farming_mutations_run_under_the_database_lock():
    source = (ROOT / "farming.py").read_text(encoding="utf-8")
    plant = source.split("async def plant", 1)[1].split("async def harvest", 1)[0]
    harvest = source.split("async def harvest", 1)[1].split("async def status", 1)[0]

    assert "async with self.bot.db.lock:" in plant
    assert "async with self.bot.db.lock:" in harvest
    assert "inv_take(user, seed_item_name, 1)" in plant
    assert "calculate_harvest_outcome(" in harvest
    assert "effective_pot_capacity(user, scope)" in plant
