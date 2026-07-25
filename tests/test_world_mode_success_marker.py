from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_world_mode_source_contracts_are_present_without_runtime_markers():
    tasks = (ROOT / "tasks.py").read_text(encoding="utf-8")
    economy = (ROOT / "economy.py").read_text(encoding="utf-8")
    crime = (ROOT / "crime.py").read_text(encoding="utf-8")
    assert "class _WorldGuildProxy" in tasks
    assert "policy_allows_open_world" in tasks
    assert "require_same_multiplayer_scope" in economy
    assert "require_same_multiplayer_scope" in crime
    assert not (ROOT / "WORLD_MODE_SOURCE_VALIDATED").exists()
