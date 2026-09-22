from pathlib import Path

from supabase_scoped_backend import ATOMIC_SAVE_RPC, REQUIRED_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "003_atomic_scoped_record_batch.sql"


def test_atomic_scoped_record_migration_matches_backend_contract():
    source = MIGRATION.read_text(encoding="utf-8")

    assert REQUIRED_SCHEMA_VERSION == "003_atomic_scoped_record_batch"
    assert ATOMIC_SAVE_RPC == "idle_grow_save_scoped_records"
    assert f"function public.{ATOMIC_SAVE_RPC}(" in source
    assert "insert into public.global_accounts" in source
    assert "insert into public.guild_profiles" in source
    assert "insert into public.guild_worlds" in source
    assert source.count("on conflict") >= 4
    assert "from public, anon, authenticated" in source
    assert "to service_role" in source
    assert f"values ('{REQUIRED_SCHEMA_VERSION}')" in source
    assert source.lstrip().startswith("begin;")
    assert source.rstrip().endswith("commit;")
