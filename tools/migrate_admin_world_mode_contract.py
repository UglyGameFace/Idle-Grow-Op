from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests/test_admin_integrity_contract.py"
source = path.read_text(encoding="utf-8")
old = '''def test_admin_uses_only_explicit_guild_profile_persistence():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "get_context_profile" in source
    assert "mark_context_profile_dirty" in source
    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.flush()" in source
    assert ".get_user(" not in source
    assert ".world_state" not in source
    assert ".db.data" not in source
    assert ".db.save(" not in source


'''
new = '''def test_admin_uses_only_explicit_active_scope_profile_persistence():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "scope.label" in source
    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.flush()" in source
    assert "get_context_profile" not in source
    assert "mark_context_profile_dirty" not in source
    assert ".get_user(" not in source
    assert ".world_state" not in source
    assert ".db.data" not in source
    assert ".db.save(" not in source


'''
if source.count(old) != 1:
    raise RuntimeError("admin persistence contract anchor changed")
source = source.replace(old, new, 1)
source = source.replace(
    'def test_wipe_resets_only_the_current_guild_profile():',
    'def test_wipe_resets_only_the_targets_selected_profile():',
    1,
)
source = source.replace(
    '    assert "in this server" in source\n',
    '    assert "scope.label" in source\n',
    1,
)
path.write_text(source, encoding="utf-8")
