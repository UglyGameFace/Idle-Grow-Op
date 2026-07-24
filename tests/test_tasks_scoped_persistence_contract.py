from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tasks_iterate_connected_guilds_without_global_state():
    source = (ROOT / "tasks.py").read_text(encoding="utf-8")

    assert "for guild in tuple(self.bot.guilds)" in source
    assert "await self.bot.db.get_world(guild_id)" in source
    assert "economy._settle_expired_auctions(guild_id, world)" in source
    assert "self.bot.db.mark_world_dirty(guild_id)" in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "self.bot.db.get_user" not in source
    assert "await self.bot.db.save()" not in source


def test_notifications_use_indexed_candidates_and_commit_after_delivery():
    source = (ROOT / "tasks.py").read_text(encoding="utf-8")

    assert "list_guild_notification_candidates(" in source
    assert "await target.send(" in source
    assert "await self._commit_notification_flags(" in source
    assert source.index("await target.send(") < source.index(
        "await self._commit_notification_flags("
    )
    assert "self.bot.db.mark_profile_dirty(guild_id, user_id)" in source


def test_supabase_indexes_only_profiles_with_notification_work():
    migration = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(
        encoding="utf-8"
    )
    backend = (ROOT / "supabase_scoped_backend.py").read_text(encoding="utf-8")

    assert "has_notification_work boolean generated always as" in migration
    assert "guild_profiles_notification_work_idx" in migration
    assert "where has_notification_work" in migration
    assert '.eq("has_notification_work", True)' in backend
    assert '.select("user_id")' in backend


def test_global_presence_does_not_read_a_single_guild_world():
    source = (ROOT / "tasks.py").read_text(encoding="utf-8")
    status_body = source.split("async def status_cycle", 1)[1]

    assert "len(self.bot.guilds)" in status_body
    assert "get_world(" not in status_body.split("@status_cycle.before_loop", 1)[0]
