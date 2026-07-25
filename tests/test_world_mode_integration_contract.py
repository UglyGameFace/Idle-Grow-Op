from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_world_modes_are_loaded_and_visible_in_setup():
    main = source("main.py")
    setup = source("setup.py")
    assert '"world_modes"' in main
    assert "ServerWorldModeView" in setup
    assert "build_server_mode_embed" in setup
    assert "world_mode_status" in setup
    assert 'label="World Mode"' in setup
    assert 'name="🌍 World Mode"' in setup
    assert "Multiplayer • Notifications" not in setup


def test_solo_and_progression_modules_route_through_the_canonical_scope():
    for path in ("farming.py", "lab.py", "quick.py", "progression.py", "gambling.py"):
        text = source(path)
        assert "world_modes" in text, path
        assert "resolve_game_scope" in text or "get_game_records" in text, path
        assert "scope.scope_id" in text, path

    assert "effective_pot_capacity" in source("farming.py")
    assert "effective_pot_capacity" in source("quick.py")
    assert "processing_queue_limit" in source("lab.py")
    assert "effective_market_multiplier" in source("lab.py")


def test_every_player_value_exchange_has_a_multiplayer_scope_gate():
    economy = source("economy.py")
    social = source("social.py")
    crime = source("crime.py")

    assert "require_same_multiplayer_scope" in economy
    assert "require_multiplayer" in economy
    assert "require_multiplayer" in social
    assert "require_same_multiplayer_scope" in crime
    assert '"transfer"' in economy
    assert '"auction"' in economy
    assert '"crew"' in social
    assert '"district"' in social
    assert '"crew_heist"' in crime
    assert '"raid"' in crime
    assert '"theft"' in crime


def test_leaderboards_and_world_interactions_use_the_resolved_scope():
    economy = source("economy.py")
    gambling = source("gambling.py")
    crime = source("crime.py")
    assert "list_guild_leaderboard(scope.scope_id" in economy
    assert "list_guild_casino_leaderboard(scope.scope_id" in gambling
    assert "list_guild_heist_leaderboard(scope.scope_id" in crime


def test_profile_and_live_signatures_show_the_targets_active_save():
    signatures = source("profile_signatures.py")
    assert "resolve_game_scope" in signatures
    assert "game_scope.scope_id" in signatures
    assert "game_scope.mode" in signatures
    assert "MODE_LABELS" in signatures
    assert "_rank_for(game_scope.scope_id" in signatures


def test_sesh_rewards_follow_each_participants_active_save():
    sesh = source("sesh.py")
    assert "resolve_game_scope" in sesh
    assert "scope.scope_id" in sesh
    assert "mark_game_profile_dirty" in sesh


def test_background_jobs_process_open_world_once_and_filter_dormant_saves():
    tasks = source("tasks.py")
    assert "OPEN_WORLD_SCOPE_ID" in tasks
    assert "open_world_processed" in tasks
    assert "policy_allows_open_world" in tasks
    assert "policy_uses_local_world" in tasks
    assert "resolve_game_scope" in tasks
    assert "scope.scope_id != guild_id" in tasks
    assert "_open_world_notification_guild" in tasks


def test_admin_mutations_target_the_selected_save_not_always_the_guild_save():
    admin = source("admin.py")
    assert "resolve_game_scope" in admin
    assert "scope.scope_id" in admin
    assert "scope.label" in admin
    assert "get_context_profile" not in admin


def test_ai_and_help_copy_explain_that_saves_are_separate():
    ai = source("ai.py")
    assert "Solo Grow" in ai
    assert "Open World" in ai
    assert "never mix" in ai


def test_ci_guard_covers_the_new_canonical_module():
    ci = source(".github/workflows/ci.yml")
    assert "world_modes.py" in ci
