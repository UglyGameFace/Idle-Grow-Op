from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_ownerless_legacy_game_constants_are_gone():
    text = source("utils.py")
    for token in (
        "GAME_VERSION_DISPLAY",
        "STREAK_BONUSES",
        "SKILLS_CONFIG",
        "SESH_MESSAGES",
        "SESH_COLORS",
        "SESSION_MEDIA",
        "JAIL_ACTION_BLOCK",
        "STONER_ROLE_ID",
        "STONER_ROLE_NAME",
        "def _env(",
        "def _env_int(",
        "def _env_str(",
    ):
        assert token not in text


def test_unreachable_skill_bonus_no_longer_affects_sales_or_defaults():
    assert '"skills": {}' not in source("scoped_database.py")
    economy = source("economy.py")
    assert 'user.get("skills"' not in economy
    assert "skill_multiplier" not in economy
