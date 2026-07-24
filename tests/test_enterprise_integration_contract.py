from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_EXTENSIONS = {
    "admin",
    "ai",
    "crime",
    "economy",
    "farming",
    "gambling",
    "lab",
    "progression",
    "quick",
    "sesh",
    "social",
    "tasks",
}
PRODUCTION_MODULES = [ROOT / f"{name}.py" for name in sorted(CANONICAL_EXTENSIONS)]


def test_all_enterprise_features_have_one_canonical_root_module():
    missing = [path.name for path in PRODUCTION_MODULES if not path.is_file()]
    assert not missing, f"missing canonical Enterprise modules: {missing}"
    assert not (ROOT / "cogs").exists(), "duplicate cogs/ tree must not survive integration"


def test_main_loads_exactly_the_canonical_enterprise_surface():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    for extension in CANONICAL_EXTENSIONS:
        assert f'"{extension}"' in source
    assert "cogs." not in source


def test_no_backup_runtime_or_secret_artifacts_are_committed():
    forbidden_names = {
        ".env",
        "database.json",
        "database.json.bak",
        "bot.log",
        "last_startup_fingerprint.json",
    }
    found = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.name in forbidden_names or "__pycache__" in path.parts:
            found.append(str(path.relative_to(ROOT)))
    assert not found, f"forbidden runtime/secret artifacts committed: {found}"


def test_enterprise_modules_use_only_scoped_persistence():
    forbidden = (
        "db_manager",
        ".get_user(",
        ".world_state",
        "bot.db.data",
        "self.bot.db.data",
        "await self.bot.db.save()",
        "await db_manager.save()",
        "Local JSON",
        "memory-only fallback",
        "IDLE_SUPABASE_KEY",
    )
    violations = []
    for path in PRODUCTION_MODULES:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                violations.append(f"{path.name}: {token}")
    assert not violations, "legacy persistence survived integration: " + ", ".join(violations)
