from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_utils_is_constants_and_helpers_only():
    source = (ROOT / "utils.py").read_text(encoding="utf-8")

    forbidden = (
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "create_client",
        "class Database",
        "db_manager",
        "world_state",
        "local_cache",
        "_background_sync",
        "asyncio.create_task",
    )
    for token in forbidden:
        assert token not in source


def test_main_owns_verified_scoped_database_lifecycle():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "from persistence_bootstrap import build_scoped_database" in source
    assert "database = await build_scoped_database()" in source
    assert "bot.db = database" in source
    assert "finally:\n        await database.close()" in source
    assert "memory-only fallback" not in source
    assert "from utils import db_manager" not in source


def test_production_cogs_have_no_legacy_database_calls():
    paths = (
        "admin.py",
        "ai.py",
        "crime.py",
        "economy.py",
        "farming.py",
        "lab.py",
        "social.py",
        "tasks.py",
    )
    forbidden = (
        "db_manager",
        ".world_state",
        ".get_user(",
        "await self.bot.db.save()",
        "self.bot.db.data",
    )

    for path in paths:
        source = (ROOT / path).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path} still contains {token}"
