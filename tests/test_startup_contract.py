import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EXTENSIONS = {
    "admin",
    "ai",
    "crime",
    "economy",
    "farming",
    "gambling",
    "lab",
    "progression",
    "quick",
    "profile_signatures",
    "sesh",
    "setup",
    "social",
    "tasks",
}


def _parse(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


def test_main_does_not_import_utils_before_event_loop_starts():
    tree = _parse("main.py")

    top_level_utils_imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "utils":
            top_level_utils_imports.append(node)
        if isinstance(node, ast.Import):
            top_level_utils_imports.extend(
                alias for alias in node.names if alias.name == "utils"
            )

    assert not top_level_utils_imports


def test_canonical_extensions_exist_and_are_loaded_from_root():
    tree = _parse("main.py")
    extension_names = set()

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "GAME_EXTENSIONS"
                for target in targets
            ):
                continue

            value = node.value
            assert isinstance(value, (ast.Tuple, ast.List))
            extension_names = {
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }

    assert extension_names == EXPECTED_EXTENSIONS
    assert all((ROOT / f"{name}.py").is_file() for name in extension_names)


def test_loader_fails_when_required_extension_fails():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "failures.append(extension_name)" in source
    assert "raise RuntimeError" in source


def test_supabase_runtime_dependency_is_declared():
    requirements = {
        line.strip().lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "supabase" in requirements


def test_admin_reload_uses_root_extension_names():
    source = (ROOT / "admin.py").read_text(encoding="utf-8")

    assert 'reload_extension(extension_name)' in source
    assert 'reload_extension(f"cogs.' not in source


def test_profile_does_not_reuse_the_plant_short_alias():
    source = (ROOT / "social.py").read_text(encoding="utf-8")

    assert 'name="profile", aliases=["me", "stats"]' in source
    assert 'name="profile", aliases=["p"' not in source


def test_background_loops_use_native_cog_lifecycle_without_startup_guards():
    source = (ROOT / "tasks.py").read_text(encoding="utf-8")
    init_block = source.split("def __init__", 1)[1].split("async def cog_load", 1)[0]
    cog_load_block = source.split("async def cog_load", 1)[1].split("def cog_unload", 1)[0]

    assert ".start()" not in init_block
    assert "self.game_cycle.start()" in cog_load_block
    assert "self.notification_check.start()" in cog_load_block
    assert "self.status_cycle.start()" in cog_load_block
    assert "async def on_ready" not in source
    assert ".is_running()" not in source
    assert "await self.bot.wait_until_ready()" in source
