from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_economy_uses_only_guild_scoped_persistence():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")

    assert "get_profile(" in source
    assert "get_world(" in source
    assert "list_guild_leaderboard(" in source
    assert "mark_profile_dirty(" in source
    assert "mark_world_dirty(" in source

    assert ".get_user(" not in source
    assert ".world_state" not in source
    assert ".db.data" not in source
    assert ".db.save(" not in source
    assert "Global Leaderboard" not in source
    assert "Server Leaderboard" in source


def test_auction_settlement_requires_explicit_guild_scope():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")

    assert "async def _settle_expired_auctions(self, guild_id: int" in source
    assert "get_profile(guild_id, seller_id)" in source
    assert "get_profile(guild_id, buyer_id)" in source
    assert "mark_world_dirty(guild_id)" in source


def test_economy_rejects_dm_gameplay_instead_of_falling_back():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "GuildContextRequired" in source
