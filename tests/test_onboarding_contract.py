from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "onboarding.py").read_text(encoding="utf-8")
FARMING = (ROOT / "farming.py").read_text(encoding="utf-8")
LAB = (ROOT / "lab.py").read_text(encoding="utf-8")
QUICK = (ROOT / "quick.py").read_text(encoding="utf-8")
SETUP = (ROOT / "setup.py").read_text(encoding="utf-8")
TASKS = (ROOT / "tasks.py").read_text(encoding="utf-8")


def test_onboarding_extension_replaces_the_missing_help_surface():
    assert '"onboarding"' in MAIN
    assert "help_command=None" in MAIN
    assert 'name="help"' in ONBOARDING
    assert 'name="start"' in ONBOARDING
    assert "@app_commands.guild_only()" in ONBOARDING
    assert "ephemeral=ctx.interaction is not None" in ONBOARDING


def test_onboarding_is_read_only_and_has_no_automatic_spam_listener():
    assert "mark_profile_dirty" not in ONBOARDING
    assert "mark_world_dirty" not in ONBOARDING
    assert "on_member_join" not in ONBOARDING
    assert "on_guild_join" not in ONBOARDING
    assert "send_message" in ONBOARDING
    assert "interaction_check" in ONBOARDING


def test_start_guide_uses_the_real_starter_economy_and_active_save():
    assert 'STARTER_SEED = "schwag seed"' in ONBOARDING
    assert 'STARTER_STRAIN = "schwag"' in ONBOARDING
    assert 'SHOP_ITEMS[STARTER_SEED]["cost"]' in ONBOARDING
    assert "resolve_game_scope" in ONBOARDING
    assert "scope.emoji" in ONBOARDING
    assert "scope.label" in ONBOARDING
    assert "/buy item_name:{STARTER_SEED}" in ONBOARDING
    assert "/plant strain_name:{STARTER_STRAIN}" in ONBOARDING
    assert "/sell amount:all" in ONBOARDING


def test_help_is_compact_and_labels_mode_dependent_systems():
    assert "Core grow loop" in ONBOARDING
    assert "Wallet and inventory" in ONBOARDING
    assert "Progression" in ONBOARDING
    assert "Lab and expansion" in ONBOARDING
    assert "Modes and multiplayer" in ONBOARDING
    assert "require a multiplayer mode" in ONBOARDING
    assert "`/setup`" in ONBOARDING


def test_high_traffic_starter_messages_use_real_slash_guidance():
    assert "Try `/help` for usage." in MAIN
    assert 'name="/help • /start • Growing 🌿"' in MAIN
    assert "`!plant" not in FARMING
    assert "`!shop" not in FARMING
    assert "`!strains" not in FARMING
    assert "`!status" not in FARMING
    assert "Type !harvest" not in FARMING
    assert "Use: !process" not in LAB
    assert "Use !collect" not in LAB
    assert "Use `!process`" not in LAB
    assert "`!q`" not in QUICK
    assert '"/help • /start • Build your empire"' in TASKS


def test_existing_setup_points_managers_to_the_new_player_launch_commands():
    assert 'name="Player Launch"' in SETUP
    assert "`/start`" in SETUP
    assert "`/help`" in SETUP
    assert 'name="Coming next"' not in SETUP
