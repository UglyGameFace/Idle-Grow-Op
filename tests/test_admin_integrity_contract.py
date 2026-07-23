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
    assert "inv_add(user, clean_name, quantity)" in source
