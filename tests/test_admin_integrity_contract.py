from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_mutations_validate_and_lock_value_changes():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "if amount < 0" in source
    assert "require_positive_amount(amount)" in source
    assert "require_positive_amount(level)" in source
    assert source.count("async with self.bot.db.lock:") >= 4


def test_wipe_confirmation_is_scoped_to_the_command_channel():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "message.channel == ctx.channel" in source


def test_admin_does_not_import_or_use_inventory_subtraction_for_spawning():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "inv_take" not in source
    assert "inv_add(profile, clean_name, quantity)" in source


def test_admin_uses_only_explicit_active_scope_profile_persistence():
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


def test_wipe_resets_only_the_targets_selected_profile():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert "profile.clear()" in source
    assert "profile.update(make_default_profile())" in source
    assert "scope.label" in source
