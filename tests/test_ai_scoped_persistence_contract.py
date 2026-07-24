from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_paid_generation_uses_guild_scoped_profile():
    source = (ROOT / "ai.py").read_text(encoding="utf-8")

    assert "require_guild_id(ctx)" in source
    assert "await self.bot.db.get_profile(guild_id, ctx.author.id)" in source
    assert "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)" in source
    assert "async with self.bot.db.lock:" in source


def test_ai_refunds_the_same_guild_profile_without_legacy_storage():
    source = (ROOT / "ai.py").read_text(encoding="utf-8")

    assert "await self._refund_image_cost(guild_id, ctx.author.id)" in source
    assert "await self.bot.db.get_profile(guild_id, user_id)" in source
    assert "self.bot.db.mark_profile_dirty(guild_id, user_id)" in source
    assert "db_manager" not in source
    assert ".get_user(" not in source
    assert "await self.bot.db.save()" not in source
