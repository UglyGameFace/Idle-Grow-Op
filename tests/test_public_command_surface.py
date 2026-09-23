import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GAMEPLAY_MODULES = (
    "ai.py",
    "crime.py",
    "economy.py",
    "farming.py",
    "gambling.py",
    "lab.py",
    "notification_preferences.py",
    "onboarding.py",
    "progression.py",
    "quick.py",
    "profile_signatures.py",
    "sesh.py",
    "setup.py",
    "social.py",
    "world_modes.py",
)


def test_public_gameplay_has_no_prefix_only_top_level_commands():
    violations = []
    for filename in PUBLIC_GAMEPLAY_MODULES:
        path = ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "commands"
                    and func.attr in {"command", "group"}
                ):
                    violations.append(f"{filename}:{node.name}:{func.attr}")
    assert not violations, "prefix-only gameplay commands remain: " + ", ".join(violations)


def test_public_gameplay_does_not_teach_stale_prefix_syntax():
    violations = []
    stale = re.compile(r"[\x60\"']![A-Za-z]")
    for filename in PUBLIC_GAMEPLAY_MODULES:
        path = ROOT / filename
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if stale.search(line):
                violations.append(f"{filename}:{line_number}:{line.strip()}")
    assert not violations, "stale prefix guidance remains: " + " | ".join(violations)
