from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_lab_routes_inventory_queue_and_values_to_the_active_save():
    text = source("lab.py")
    assert "resolve_game_scope" in text
    assert text.count("scope.scope_id") >= 8
    assert "processing_queue_limit(scope)" in text
    assert "effective_market_multiplier(world, scope)" in text
    assert "scope.multiplayer" in text


def test_every_casino_settlement_stays_in_the_starting_scope():
    text = source("gambling.py")
    assert "resolve_game_scope" in text
    assert "self.scope_id" in text
    assert "BlackjackView(self,ctx,scope.scope_id" in text
    assert "list_guild_casino_leaderboard(\n            scope.scope_id" in text
    assert "require_multiplayer(scope, \"leaderboard\")" in text
    assert "mark_profile_dirty(scope.scope_id" in text
    assert "mark_profile_dirty(guild_id" not in text


def test_sesh_configuration_stays_server_local_but_rewards_follow_each_player():
    text = source("sesh.py")
    assert "await self.bot.db.get_world(guild_id)" in text
    assert "resolve_game_scope" in text
    assert "scope.scope_id" in text
    assert "mark_game_profile_dirty(self.bot.db, scope" in text
    assert "mark_profile_dirty(\n                        session.guild_id" not in text


def test_profile_privacy_remains_server_local_while_game_data_uses_active_scope():
    text = source("profile_signatures.py")
    assert "privacy_profile = await self.bot.db.get_profile(guild.id, member.id)" in text
    assert "game_scope = await resolve_game_scope" in text
    assert "profile = await self.bot.db.get_profile(game_scope.scope_id" in text
    assert "world = await self.bot.db.get_world(game_scope.scope_id)" in text
    assert "_rank_for(game_scope.scope_id" in text
    assert "MODE_LABELS[game_scope.mode]" in text
    assert 'visible.discard("rank")' in text


def test_mode_changes_invalidate_stale_live_signature_cards():
    text = source("world_modes.py")
    assert "remove_user_cards(self.guild_id, self.owner_id)" in text
    assert "invalidate_guild_cards(interaction.guild)" in text
