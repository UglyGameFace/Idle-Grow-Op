from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests/test_farming_scoped_persistence_contract.py"
source = path.read_text(encoding="utf-8")
source = source.replace(
    "def test_farming_uses_only_guild_scoped_profiles_and_worlds():",
    "def test_farming_uses_only_explicit_active_scope_profiles_and_worlds():",
    1,
)
source = source.replace(
    '    assert "await self.bot.db.get_profile(guild_id, ctx.author.id)" in source\n'
    '    assert "await self.bot.db.get_world(guild_id)" in source\n',
    '    assert "resolve_game_scope" in source\n'
    '    assert "await self.bot.db.get_profile(scope.scope_id, ctx.author.id)" in source\n'
    '    assert "await self.bot.db.get_world(scope.scope_id)" in source\n',
    1,
)
source = source.replace(
    "def test_farming_marks_only_the_current_guild_profile_dirty():",
    "def test_farming_marks_only_the_active_scope_profile_dirty():",
    1,
)
source = source.replace(
    '    assert source.count("self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)") >= 3\n',
    '    assert source.count("self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)") >= 3\n',
    1,
)
source = source.replace(
    '    assert "calculate_harvest_outcome(" in source\n',
    '    assert "calculate_harvest_outcome(" in source\n'
    '    assert "effective_pot_capacity(user, scope)" in source\n',
    1,
)
path.write_text(source, encoding="utf-8")
