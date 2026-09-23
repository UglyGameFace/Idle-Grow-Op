from pathlib import Path

from supabase_scoped_backend import NOTIFICATION_BATCH_RPC, REQUIRED_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "004_batched_notification_candidates.sql"


def test_notification_batch_migration_matches_backend_contract():
    source = MIGRATION.read_text(encoding="utf-8")

    assert REQUIRED_SCHEMA_VERSION == "004_batched_notification_candidates"
    assert NOTIFICATION_BATCH_RPC == "idle_grow_list_notification_candidates"
    assert "idle_grow_has_pending_notification_work" in source
    assert "notification_categories,plant_ready" in source
    assert "notification_categories,lab_ready" in source
    assert "has_pending_notification_work boolean generated always as" in source
    assert "guild_profiles_pending_notification_work_idx" in source
    assert "where has_pending_notification_work" in source
    assert "p_guild_ids bigint[]" in source
    assert "profile.guild_id = any" in source
    assert f"function public.{NOTIFICATION_BATCH_RPC}(" in source
    assert "returns table" in source
    assert "from public, anon, authenticated" in source
    assert "to service_role" in source
    assert f"values ('{REQUIRED_SCHEMA_VERSION}')" in source
    assert source.lstrip().startswith("begin;")
    assert source.rstrip().endswith("commit;")
