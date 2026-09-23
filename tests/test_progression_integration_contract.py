from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_legacy_progression_implementation_is_removed_from_utils():
    text = source("utils.py")
    for token in (
        "QUEST_TEMPLATES",
        "ACHIEVEMENTS =",
        "def _xp_needed_for_level",
        "async def add_xp",
        "def add_quest_progress",
        "def add__progress",
        "async def check_achievements",
    ):
        assert token not in text


def test_live_gameplay_routes_progress_through_progression_core():
    expected = {
        "farming.py": ('"plant"', '"harvest"'),
        "economy.py": ('"buy"', "check_achievements(user)"),
        "lab.py": ('"collect_dabs"',),
        "crime.py": ('"heist"', '"steal"', '"raid"', '"launder"'),
        "gambling.py": ('"casino_play"', '"gamble_win"'),
        "social.py": ('"crew_deposit_cash"',),
    }
    for filename, tokens in expected.items():
        text = source(filename)
        assert "progression_core import" in text
        for token in tokens:
            assert token in text, f"{filename} is missing progression hook {token}"


def test_xp_consumers_share_the_canonical_threshold_and_credit_helpers():
    assert "xp_needed_for_level(level)" in source("progression.py")
    assert "xp_needed_for_level(level)" in source("social.py")
    assert "xp_needed_for_level(level)" in source("profile_signatures.py")
    assert "credit_xp(" in source("farming.py")
    assert "credit_xp(" in source("lab.py")
    assert "credit_xp(" in source("crime.py")
    assert "credit_xp(" in source("sesh.py")


def test_ai_does_not_recommend_removed_tasks_command():
    text = source("ai.py")
    assert "`/tasks`" not in text
    assert "`/game`" in text
    assert "normal all-in-one" in text
    assert "optional shortcuts" in text
