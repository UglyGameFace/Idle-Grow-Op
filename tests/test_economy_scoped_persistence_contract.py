from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_economy_uses_explicit_active_scope_storage_paths():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_same_multiplayer_scope" in source
    assert "require_multiplayer" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_economy_uses_backend_leaderboard_queries_for_active_scope():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "list_guild_leaderboard(scope.scope_id, limit=10)" in source
    assert "for uid, data in self.bot.db.data.items()" not in source


def test_auction_state_and_settlement_use_explicit_multiplayer_scope():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "def _settle_expired_auctions(self, scope_id" in source
    assert "await self.bot.db.get_world(scope_id)" in source
    assert "await self._settle_expired_auctions(scope.scope_id, world)" in source
    assert 'require_multiplayer(scope, "auction")' in source
