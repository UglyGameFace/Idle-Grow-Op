from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"expected one anchor in {path!r}, found {source.count(old)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "scoped_database.py",
    '        "settings": {},\n        "profile_signature_config": {',
    '        "settings": {},\n'
    '        "world_mode_config": {\n'
    '            "policy": "solo",\n'
    '            "default_player_mode": "solo",\n'
    '            "switch_cooldown_seconds": 604800,\n'
    '            "configured": False,\n'
    '            "updated_at": 0,\n'
    '        },\n'
    '        "profile_signature_config": {',
)

replace_once(
    "main.py",
    '    "tasks",\n)',
    '    "tasks",\n    "world_modes",\n)',
)

replace_once(
    "tests/test_startup_contract.py",
    '    "tasks",\n}',
    '    "tasks",\n    "world_modes",\n}',
)

replace_once(
    "tests/test_command_surface_uniqueness.py",
    '    "tasks",\n)',
    '    "tasks",\n    "world_modes",\n)',
)
