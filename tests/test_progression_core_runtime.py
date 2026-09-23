import progression_core as progression
from progression_data import DAILY_QUEST_TEMPLATES


def test_legacy_xp_overflow_reconciles_into_real_level_progress():
    profile = {"level": 20, "xp": 9_802}

    reached = progression.reconcile_level_xp(profile)

    assert reached == [21]
    assert profile == {"level": 21, "xp": 858}
    assert progression.reconcile_level_xp(profile) == []
    assert profile == {"level": 21, "xp": 858}


def test_credit_xp_applies_every_crossed_level_with_one_canonical_formula():
    profile = {"level": 1, "xp": 90}

    reached = progression.credit_xp(profile, 1_000)

    assert reached == [2, 3, 4]
    assert profile["level"] == 4
    assert profile["xp"] == 189
    assert progression.xp_needed_for_level(4) == 800


def test_current_daily_quest_schema_progresses_and_rewards(monkeypatch):
    monkeypatch.setattr(progression, "_today", lambda now=None: "2026-09-22")
    profile = {
        "level": 1,
        "xp": 0,
        "grams": 0,
        "daily_quest_date": "2026-09-22",
        "daily_quests_bonus_claimed": False,
        "daily_quests": [
            {
                "id": "dq_plant",
                "name": "Plant",
                "desc": "Plant",
                "event": "plant",
                "target": 1,
                "progress": 0,
                "reward_cash": 100,
                "reward_xp": 20,
                "completed": False,
            },
            {
                "id": "dq_harvest",
                "name": "Harvest",
                "desc": "Harvest",
                "event": "harvest",
                "target": 99,
                "progress": 0,
                "reward_cash": 0,
                "reward_xp": 0,
                "completed": False,
            },
        ],
    }

    result = progression.add_progress(profile, "plant", 1, user_id=7)

    assert result["completed"][0]["id"] == "dq_plant"
    assert profile["daily_quests"][0]["completed"] is True
    assert profile["grams"] == 100
    assert profile["xp"] == 20


def test_achievement_rewards_use_the_same_level_transition_path():
    profile = {
        "level": 1,
        "xp": 90,
        "grams": 0,
        "stats": {"harvested": 1},
        "achievements": [],
    }

    unlocked = progression.check_achievements(profile)

    assert [item["id"] for item in unlocked] == ["first_grow"]
    assert profile["level"] == 2
    assert profile["xp"] == 240
    assert profile["grams"] == 500


def test_daily_quest_pool_contains_only_implemented_event_types():
    events = {template.event for template in DAILY_QUEST_TEMPLATES}

    assert "breed" not in events
    assert "contract_complete" not in events
    assert "water" not in events
    assert {
        "plant",
        "harvest",
        "collect_dabs",
        "steal",
        "heist",
        "raid",
        "launder",
        "casino_play",
        "gamble_win",
        "crew_deposit_cash",
        "buy",
    } <= events
