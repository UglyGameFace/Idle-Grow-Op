from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS = (ROOT / "tasks.py").read_text(encoding="utf-8")
MODES = (ROOT / "world_modes.py").read_text(encoding="utf-8")


def test_policy_helpers_define_when_local_and_open_worlds_are_active():
    assert "def policy_uses_local_world" in MODES
    assert "def policy_allows_open_world" in MODES
    assert "POLICY_SOLO" in MODES
    assert "POLICY_OPEN" in MODES
    assert "POLICY_CHOICE" in MODES
    assert "POLICY_SERVER" in MODES


def test_background_policy_detection_normalizes_the_complete_world_record():
    assert "config = normalize_world_mode_config(world)" in TASKS
    assert 'policy = config["policy"]' in TASKS
    assert 'normalize_world_mode_config(world.get("world_mode_config"))' not in TASKS


def test_background_cycles_build_one_deduplicated_scope_list():
    assert "class _WorldGuildProxy" in TASKS
    assert "OPEN_WORLD_SCOPE_ID" in TASKS
    assert "open_world_processed" in TASKS
    assert "policy_allows_open_world" in TASKS
    assert "policy_uses_local_world" in TASKS
    assert "_run_game_cycle_for" in TASKS
    assert "_run_notification_check_for" in TASKS


def test_open_world_uses_one_safe_notification_guild_and_shared_member_lookup():
    assert "_open_world_notification_guild" in TASKS
    assert "_sync_open_world_routing" in TASKS
    assert "resolve_player_scope" in TASKS
    assert "member_guilds" in TASKS
    assert "OPEN_WORLD_SCOPE_ID" in TASKS


def test_notification_candidates_are_filtered_before_snapshot_or_mutation():
    assert "resolve_game_scope" in TASKS
    assert "scope.scope_id != guild_id" in TASKS
    assert "scope.scope_id != guild.id" in TASKS
    loop = TASKS.split("async def _run_notification_check_for", 1)[1]
    filter_position = loop.index("scope.scope_id != guild_id")
    snapshot_position = loop.index("pending = await self._notification_snapshot")
    commit_position = loop.index("await self._commit_notification_flags")
    assert filter_position < snapshot_position < commit_position


def test_open_world_auction_and_world_processing_can_only_run_once_per_tick():
    game_cycle = TASKS.split("async def game_cycle", 1)[1].split("async def", 1)[0]
    assert "open_world_processed = False" in game_cycle
    assert "if not open_world_processed" in game_cycle
    assert "open_world_processed = True" in game_cycle
    assert "_WorldGuildProxy" in game_cycle
