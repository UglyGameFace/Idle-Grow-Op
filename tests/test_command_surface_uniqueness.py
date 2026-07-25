import ast
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_EXTENSIONS = (
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
    "social",
    "tasks",
)
TOP_LEVEL_DECORATORS = {"command", "hybrid_command", "group", "hybrid_group"}


def _literal_strings(node: ast.AST | None) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return []
    return [
        item.value
        for item in node.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def _command_tokens(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "commands"
                and func.attr in TOP_LEVEL_DECORATORS
            ):
                continue

            command_name = node.name
            aliases: list[str] = []
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        command_name = keyword.value.value
                elif keyword.arg == "aliases":
                    aliases = _literal_strings(keyword.value)

            found.append((command_name.lower(), node.name))
            found.extend((alias.lower(), node.name) for alias in aliases)

    return found


def test_canonical_command_names_and_aliases_are_unique():
    owners: dict[str, list[str]] = defaultdict(list)
    for extension in CANONICAL_EXTENSIONS:
        path = ROOT / f"{extension}.py"
        assert path.is_file(), f"missing canonical extension: {path.name}"
        for token, function_name in _command_tokens(path):
            owners[token].append(f"{extension}.{function_name}")

    conflicts = {
        token: locations
        for token, locations in sorted(owners.items())
        if len(locations) > 1
    }
    assert not conflicts, "duplicate top-level command names/aliases: " + "; ".join(
        f"{token} -> {', '.join(locations)}" for token, locations in conflicts.items()
    )
