"""Storage-agnostic Enterprise progression logic.

Every function mutates one supplied guild-profile dictionary. This module owns
no Discord client, database manager, cache, task, or environment configuration.
"""

from __future__ import annotations

import datetime as dt
import random
import time
from typing import Any
from zoneinfo import ZoneInfo

from progression_data import ACHIEVEMENTS, DAILY_QUEST_TEMPLATES

NY_TZ = ZoneInfo("America/New_York")


def _today(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(NY_TZ)).date().isoformat()


def _yesterday(now: dt.datetime | None = None) -> str:
    return ((now or dt.datetime.now(NY_TZ)).date() - dt.timedelta(days=1)).isoformat()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def ensure_progression(profile: dict) -> None:
    profile.setdefault("stats", {})
    if not isinstance(profile["stats"], dict):
        profile["stats"] = {}
    if not isinstance(profile.get("achievements"), list):
        profile["achievements"] = []
    if not isinstance(profile.get("achievement_ts"), dict):
        profile["achievement_ts"] = {}
    if not isinstance(profile.get("daily_quests"), list):
        profile["daily_quests"] = []
    profile.setdefault("daily_quest_date", "")
    profile.setdefault("daily_quests_bonus_claimed", False)
    profile.setdefault("daily_streak", 0)
    profile.setdefault("last_daily_claim", "")


def _eligible_templates(profile: dict) -> list:
    level = max(1, _integer(profile.get("level"), 1))
    templates = [item for item in DAILY_QUEST_TEMPLATES if item.min_level <= level]
    if not profile.get("crew_id"):
        templates = [item for item in templates if item.event != "crew_deposit_cash"]
    return templates or list(DAILY_QUEST_TEMPLATES)


def ensure_daily_quests(profile: dict, *, user_id: int | None = None) -> bool:
    ensure_progression(profile)
    today = _today()
    existing = profile.get("daily_quests") or []
    if profile.get("daily_quest_date") == today and existing:
        return False

    templates = _eligible_templates(profile)
    rng = random.Random(f"{today}:{user_id or 0}:{profile.get('level', 1)}")
    rng.shuffle(templates)
    selected = templates[:3]
    quests = []
    for item in selected:
        target = rng.randint(item.target_min, item.target_max)
        difficulty = max(1.0, target / 3.0)
        level = max(1, _integer(profile.get("level"), 1))
        quests.append(
            {
                "id": item.id,
                "name": item.name,
                "desc": item.desc,
                "event": item.event,
                "target": max(1, target),
                "progress": 0,
                "reward_cash": int((300 + level * 35) * difficulty),
                "reward_xp": int((40 + level * 6) * difficulty),
                "completed": False,
            }
        )
    profile["daily_quests"] = quests
    profile["daily_quest_date"] = today
    profile["daily_quests_bonus_claimed"] = False
    return True


def _completion_bonus(profile: dict) -> dict | None:
    quests = profile.get("daily_quests") or []
    if not quests or profile.get("daily_quests_bonus_claimed"):
        return None
    if not all(bool(item.get("completed")) for item in quests if isinstance(item, dict)):
        return None
    total_cash = sum(_integer(item.get("reward_cash")) for item in quests)
    total_xp = sum(_integer(item.get("reward_xp")) for item in quests)
    bonus = {
        "bonus_cash": max(250, int(total_cash * 0.25)),
        "bonus_xp": max(150, int(total_xp * 0.25)),
    }
    profile["grams"] = _integer(profile.get("grams")) + bonus["bonus_cash"]
    profile["xp"] = _integer(profile.get("xp")) + bonus["bonus_xp"]
    profile["daily_quests_bonus_claimed"] = True
    return bonus


def add_progress(
    profile: dict,
    event: str,
    amount: int = 1,
    *,
    user_id: int | None = None,
) -> dict:
    refreshed = ensure_daily_quests(profile, user_id=user_id)
    normalized_event = str(event or "").strip().lower()
    amount = _integer(amount, 1)
    if not normalized_event or amount <= 0:
        return {"refreshed": refreshed, "completed": [], "bonus": None}

    completed = []
    for quest in profile.get("daily_quests") or []:
        if not isinstance(quest, dict):
            continue
        if str(quest.get("event") or "").lower() != normalized_event:
            continue
        if quest.get("completed"):
            continue
        target = max(1, _integer(quest.get("target"), 1))
        quest["progress"] = min(target, _integer(quest.get("progress")) + amount)
        if quest["progress"] >= target:
            quest["completed"] = True
            cash = max(0, _integer(quest.get("reward_cash")))
            xp = max(0, _integer(quest.get("reward_xp")))
            profile["grams"] = _integer(profile.get("grams")) + cash
            profile["xp"] = _integer(profile.get("xp")) + xp
            completed.append(
                {
                    "id": quest.get("id"),
                    "name": quest.get("name"),
                    "reward_cash": cash,
                    "reward_xp": xp,
                }
            )
    return {
        "refreshed": refreshed,
        "completed": completed,
        "bonus": _completion_bonus(profile),
    }


def check_achievements(profile: dict) -> list[dict]:
    ensure_progression(profile)
    owned = set(profile.get("achievements") or [])
    timestamps = profile.get("achievement_ts") or {}
    unlocked = []
    for achievement_id, achievement in ACHIEVEMENTS.items():
        if achievement_id in owned:
            continue
        try:
            earned = achievement.earned(profile)
        except Exception:
            earned = False
        if not earned:
            continue
        profile["achievements"].append(achievement_id)
        timestamps[achievement_id] = time.time()
        profile["grams"] = _integer(profile.get("grams")) + achievement.reward_cash
        profile["xp"] = _integer(profile.get("xp")) + achievement.reward_xp
        unlocked.append(
            {
                "id": achievement_id,
                "name": achievement.name,
                "reward_cash": achievement.reward_cash,
                "reward_xp": achievement.reward_xp,
            }
        )
    profile["achievement_ts"] = timestamps
    return unlocked


def claim_daily(profile: dict, *, user_id: int | None = None) -> dict:
    ensure_progression(profile)
    today = _today()
    if profile.get("last_daily_claim") == today:
        return {
            "ok": False,
            "already": True,
            "streak": _integer(profile.get("daily_streak")),
            "cash": 0,
            "xp": 0,
            "msg": "Already claimed today.",
        }

    if profile.get("last_daily_claim") == _yesterday():
        profile["daily_streak"] = _integer(profile.get("daily_streak")) + 1
    else:
        profile["daily_streak"] = 1
    profile["last_daily_claim"] = today

    level = max(1, _integer(profile.get("level"), 1))
    streak = max(1, _integer(profile.get("daily_streak"), 1))
    multiplier = 1.0 + min(1.0, streak / 30.0) * 0.60
    cash = int((400 + level * 45) * multiplier)
    xp = int((80 + level * 8) * multiplier)
    profile["grams"] = _integer(profile.get("grams")) + cash
    profile["xp"] = _integer(profile.get("xp")) + xp
    stats = profile.setdefault("stats", {})
    stats["daily_claims"] = _integer(stats.get("daily_claims")) + 1
    ensure_daily_quests(profile, user_id=user_id)
    return {
        "ok": True,
        "already": False,
        "streak": streak,
        "cash": cash,
        "xp": xp,
        "msg": "Claimed daily reward.",
    }
