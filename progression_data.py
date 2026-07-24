"""Enterprise progression definitions.

This module is intentionally storage-agnostic. It is imported by the scoped
progression service and contains no Discord or persistence ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def _iget(obj: dict, *path, default: int = 0) -> int:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    try:
        return int(cur or 0)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    desc: str
    reward_cash: int
    reward_xp: int
    progress: Callable[[dict], tuple[int, int]]
    earned: Callable[[dict], bool]


@dataclass(frozen=True)
class DailyQuestTemplate:
    id: str
    name: str
    desc: str
    event: str
    target_min: int
    target_max: int
    min_level: int = 1


def _threshold(path: tuple[str, ...], target: int):
    def progress(user: dict) -> tuple[int, int]:
        return _iget(user, *path), target

    def earned(user: dict) -> bool:
        current, required = progress(user)
        return current >= required

    return progress, earned


def _achievement(
    achievement_id: str,
    name: str,
    desc: str,
    reward_cash: int,
    reward_xp: int,
    path: tuple[str, ...],
    target: int,
) -> Achievement:
    progress, earned = _threshold(path, target)
    return Achievement(
        achievement_id,
        name,
        desc,
        reward_cash,
        reward_xp,
        progress,
        earned,
    )


_ACHIEVEMENTS = [
    _achievement("first_grow", "🌱 First Harvest", "Harvest your first plant.", 500, 250, ("stats", "harvested"), 1),
    _achievement("green_thumb", "🌿 Green Thumb", "Harvest 100 plants.", 5_000, 1_500, ("stats", "harvested"), 100),
    _achievement("master_grower", "🏡 Master Grower", "Harvest 500 plants.", 15_000, 5_000, ("stats", "harvested"), 500),
    _achievement("weed_baron", "💰 Weed Baron", "Earn $1,000,000 total.", 50_000, 8_000, ("stats", "total_earned"), 1_000_000),
    _achievement("mogul", "🏦 Mogul", "Earn $10,000,000 total.", 250_000, 20_000, ("stats", "total_earned"), 10_000_000),
    _achievement("dab_king", "🍯 Dab King", "Process 100g concentrates.", 10_000, 4_000, ("stats", "concentrate_made"), 100),
    _achievement("first_heist", "🏦 First Heist", "Attempt your first heist.", 1_500, 600, ("stats", "heists_run"), 1),
    _achievement("heist_winner", "💼 Clean Getaway", "Win your first heist.", 3_000, 1_200, ("stats", "heists_won"), 1),
    _achievement("heist_vet", "🧠 Mastermind", "Win 25 heists.", 25_000, 8_000, ("stats", "heists_won"), 25),
    _achievement("stickup_kid", "🔫 Stickup Kid", "Successfully rob 10 times.", 5_000, 2_500, ("stats", "steals"), 10),
    _achievement("first_raid", "⚔️ First Raid", "Attempt your first raid.", 2_500, 1_200, ("stats", "raids_run"), 1),
    _achievement("raid_winner", "🛡️ Raid Winner", "Win 10 raids.", 20_000, 7_000, ("stats", "raids_won"), 10),
    _achievement("launderer", "🧼 Launderer", "Launder $100,000 dirty cash.", 15_000, 5_000, ("stats", "laundered"), 100_000),
    _achievement("iron_lungs", "😮‍💨 Iron Lungs", "Reach Level 50.", 25_000, 5_000, ("level",), 50),
    _achievement("high_tolerance", "🫁 High Tolerance", "Reach Level 100.", 100_000, 15_000, ("level",), 100),
    _achievement("loyalist", "📅 Loyalist", "Reach a 30-day daily streak.", 50_000, 10_000, ("daily_streak",), 30),
]


def _casino_wagered(user: dict) -> int:
    stats = user.get("stats")
    if isinstance(stats, dict):
        for key in ("casino_total_wagered", "wagered", "total_wagered"):
            if key in stats:
                return _iget(stats, key)
    return _iget(user, "casino_total_wagered")


def _casino_achievement(
    achievement_id: str,
    name: str,
    desc: str,
    reward_cash: int,
    reward_xp: int,
    target: int,
) -> Achievement:
    def progress(user: dict) -> tuple[int, int]:
        return _casino_wagered(user), target

    def earned(user: dict) -> bool:
        current, required = progress(user)
        return current >= required

    return Achievement(achievement_id, name, desc, reward_cash, reward_xp, progress, earned)


_ACHIEVEMENTS.extend(
    [
        _casino_achievement("casino_regular", "🎲 Casino Regular", "Wager $25,000 total.", 10_000, 4_000, 25_000),
        _casino_achievement("casino_whale", "🐋 Casino Whale", "Wager $250,000 total.", 50_000, 12_000, 250_000),
        _casino_achievement("casino_vip", "💎 Casino VIP", "Wager $1,000,000 total.", 200_000, 25_000, 1_000_000),
    ]
)

ACHIEVEMENTS: dict[str, Achievement] = {item.id: item for item in _ACHIEVEMENTS}

DAILY_QUEST_TEMPLATES = [
    DailyQuestTemplate("dq_plant", "🌰 Plant Seeds", "Plant some seeds.", "plant", 2, 5),
    DailyQuestTemplate("dq_water", "💧 Water Plants", "Keep your garden alive.", "water", 2, 6),
    DailyQuestTemplate("dq_harvest", "✂️ Harvest", "Harvest ready plants.", "harvest", 1, 4),
    DailyQuestTemplate("dq_collect", "📦 Collect Lab Output", "Collect finished lab batches.", "collect_dabs", 10, 60, 5),
    DailyQuestTemplate("dq_breed", "🧬 Breed Seeds", "Run breeding experiments.", "breed", 1, 3, 12),
    DailyQuestTemplate("dq_steal", "🔫 Rob Players", "Attempt robberies.", "steal", 1, 4, 3),
    DailyQuestTemplate("dq_heist", "🏦 Run Heists", "Pull bigger jobs.", "heist", 1, 3, 5),
    DailyQuestTemplate("dq_raid", "⚔️ Raid Farms", "Attack other farms.", "raid", 1, 2, 8),
    DailyQuestTemplate("dq_launder", "🧼 Launder Money", "Clean dirty cash.", "launder", 1, 3, 5),
    DailyQuestTemplate("dq_casino_play", "🎲 Hit the Casino", "Play casino games.", "casino_play", 3, 8),
    DailyQuestTemplate("dq_casino_win", "🏁 Win a Casino Game", "Win one casino game.", "gamble_win", 1, 1),
    DailyQuestTemplate("dq_crew_bank", "🏛️ Crew Contribution", "Deposit into your crew bank.", "crew_deposit_cash", 5_000, 25_000, 5),
    DailyQuestTemplate("dq_contract", "📜 Complete a Contract", "Finish and claim a market contract.", "contract_complete", 1, 1, 3),
    DailyQuestTemplate("dq_shop", "🛒 Stock Up", "Buy something from the shop.", "buy", 1, 2),
]
