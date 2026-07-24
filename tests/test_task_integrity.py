from pathlib import Path


def test_game_cycle_uses_canonical_economy_auction_settlement():
    source = Path("tasks.py").read_text(encoding="utf-8")

    assert 'get_cog("Economy")' in source
    assert "await economy._settle_expired_auctions(guild_id, world)" in source
    assert source.count("_settle_expired_auctions") == 1


def test_notification_flags_are_committed_only_after_delivery():
    source = Path("tasks.py").read_text(encoding="utf-8")

    send_position = source.index("await target.send")
    plant_flag_position = source.index('plant["notified"] = True')
    batch_flag_position = source.index('item["notified"] = True')

    assert send_position < plant_flag_position
    assert send_position < batch_flag_position
    assert "except discord.DiscordException:\n                    continue" in source


def test_task_mutations_use_database_lock_and_exact_dirty_tracking():
    source = Path("tasks.py").read_text(encoding="utf-8")

    assert source.count("async with self.bot.db.lock:") >= 3
    assert "self.bot.db.mark_world_dirty(guild_id)" in source
    assert "self.bot.db.mark_profile_dirty(guild_id, user_id)" in source
    assert "await self.bot.db.save()" not in source
