from pathlib import Path


def test_game_cycle_uses_canonical_economy_auction_settlement():
    source = Path("tasks.py").read_text(encoding="utf-8")

    assert 'get_cog("Economy")' in source
    assert "await economy._settle_expired_auctions()" in source
    assert source.count("_settle_expired_auctions") == 1


def test_notification_flags_are_committed_only_after_delivery():
    source = Path("tasks.py").read_text(encoding="utf-8")

    send_position = source.index("await target.send")
    plant_flag_position = source.index('plant["notified"] = True')
    batch_flag_position = source.index('item["notified"] = True')

    assert send_position < plant_flag_position
    assert send_position < batch_flag_position
    assert "except discord.DiscordException:\n                continue" in source


def test_task_mutations_use_database_lock():
    source = Path("tasks.py").read_text(encoding="utf-8")

    assert source.count("async with self.bot.db.lock:") >= 3
    assert "await self.bot.db.save()" in source
