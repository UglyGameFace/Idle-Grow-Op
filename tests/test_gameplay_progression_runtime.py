import asyncio
from types import SimpleNamespace

import progression_core
from crime import Crime
from economy import Economy
from farming import Farming
from gambling import Gambling
from lab import Lab
from social import Social
from world_modes import POLICY_SERVER, POLICY_SOLO, new_world_mode_config


class MemoryDatabase:
    def __init__(self, guild_id: int, user_id: int, *, policy: str = POLICY_SOLO):
        self.lock = asyncio.Lock()
        self.worlds = {
            guild_id: {
                "world_mode_config": {
                    **new_world_mode_config(),
                    "policy": policy,
                    "configured": True,
                },
                "market_multiplier": 1.0,
                "crews": {},
            }
        }
        self.profiles = {}
        self.dirty_profiles = set()
        self.dirty_worlds = set()
        self.leaderboard_rows = []

    async def get_world(self, scope_id):
        return self.worlds.setdefault(int(scope_id), {})

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))

    async def list_guild_leaderboard(self, guild_id, *, limit=10):
        return list(self.leaderboard_rows[:limit])


class ContextStub:
    def __init__(self, guild_id: int, user_id: int):
        self.author = SimpleNamespace(
            id=user_id,
            name="Tester",
            display_name="Tester",
            mention="<@42>",
            color=0,
        )
        self.guild = SimpleNamespace(
            id=guild_id,
            get_member=lambda member_id: (
                SimpleNamespace(display_name=f"Player {member_id}") if member_id else None
            ),
        )
        self.sent = []
        self.command = SimpleNamespace(reset_cooldown=lambda _ctx: None)

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return SimpleNamespace()


def quest(event: str, target: int = 1):
    return {
        "id": f"dq_{event}",
        "name": event,
        "desc": event,
        "event": event,
        "target": target,
        "progress": 0,
        "reward_cash": 0,
        "reward_xp": 0,
        "completed": False,
    }


def add_active_quests(profile: dict, *items: dict):
    profile["daily_quest_date"] = progression_core._today()
    profile["daily_quests_bonus_claimed"] = False
    profile["daily_quests"] = [*items, quest("water", 999)]


def test_economy_leaderboard_consumes_backend_tuple_contract():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id, policy=POLICY_SERVER)
        db.leaderboard_rows = [(77, 5_000), (88, 2_500)]
        ctx = ContextStub(guild_id, user_id)

        await Economy.leaderboard.callback(Economy(SimpleNamespace(db=db)), ctx)

        embed = ctx.sent[-1][1]["embed"]
        assert "Player 77" in embed.description
        assert "$5,000" in embed.description

    asyncio.run(scenario())


def test_plant_callback_advances_current_plant_quest():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id)
        profile = {
            "level": 1,
            "xp": 0,
            "grams": 500,
            "items": {"schwag seed": 1},
            "plants": [],
            "max_pots": 3,
            "stats": {},
            "achievements": [],
        }
        add_active_quests(profile, quest("plant"))
        db.profiles[(guild_id, user_id)] = profile
        ctx = ContextStub(guild_id, user_id)

        await Farming.plant.callback(
            Farming(SimpleNamespace(db=db)),
            ctx,
            strain_name="schwag",
        )

        assert profile["daily_quests"][0]["completed"] is True
        assert len(profile["plants"]) == 1
        assert profile["items"].get("schwag seed", 0) == 0

    asyncio.run(scenario())


def test_lab_collect_callback_advances_current_collect_quest():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id)
        profile = {
            "level": 5,
            "xp": 0,
            "grams": 0,
            "processing_queue": [{"type": "hash", "amount": 5, "finish_time": 0}],
            "concentrates": {},
            "stats": {},
            "achievements": [],
        }
        add_active_quests(profile, quest("collect_dabs", 5))
        db.profiles[(guild_id, user_id)] = profile
        ctx = ContextStub(guild_id, user_id)

        await Lab.collect.callback(Lab(SimpleNamespace(db=db)), ctx)

        assert profile["daily_quests"][0]["completed"] is True
        assert profile["concentrates"]["hash"] == 5
        assert profile["stats"]["concentrate_made"] == 5

    asyncio.run(scenario())


def test_launder_callback_updates_stat_achievement_source_and_quest():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id)
        profile = {
            "level": 5,
            "xp": 0,
            "grams": 0,
            "dirty_cash": 1_000,
            "heat": 0,
            "stats": {},
            "achievements": [],
        }
        add_active_quests(profile, quest("launder"))
        db.profiles[(guild_id, user_id)] = profile
        ctx = ContextStub(guild_id, user_id)

        await Crime.launder.callback(Crime(SimpleNamespace(db=db)), ctx, amount="all")

        assert profile["daily_quests"][0]["completed"] is True
        assert profile["stats"]["laundered"] == 1_000
        assert profile["dirty_cash"] == 0
        assert profile["grams"] == 800

    asyncio.run(scenario())


def test_crew_deposit_advances_cash_target_quest():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id, policy=POLICY_SERVER)
        profile = {
            "level": 5,
            "xp": 0,
            "grams": 10_000,
            "crew_id": "12345",
            "stats": {},
            "achievements": [],
        }
        add_active_quests(profile, quest("crew_deposit_cash", 5_000))
        db.profiles[(guild_id, user_id)] = profile
        db.worlds[guild_id]["crews"] = {
            "12345": {
                "id": "12345",
                "name": "Test Crew",
                "owner_id": user_id,
                "members": [user_id],
                "bank": 0,
                "level": 1,
            }
        }
        ctx = ContextStub(guild_id, user_id)

        await Social.crew_deposit.callback(
            Social(SimpleNamespace(db=db)),
            ctx,
            amount=5_000,
        )

        assert profile["daily_quests"][0]["completed"] is True
        assert db.worlds[guild_id]["crews"]["12345"]["bank"] == 5_000
        assert profile["grams"] == 5_000

    asyncio.run(scenario())


def test_atomic_casino_play_advances_play_and_win_quests():
    async def scenario():
        guild_id, user_id = 123456789012345678, 42
        db = MemoryDatabase(guild_id, user_id)
        profile = {
            "level": 1,
            "xp": 0,
            "grams": 1_000,
            "stats": {},
            "achievements": [],
        }
        play = quest("casino_play")
        win = quest("gamble_win")
        add_active_quests(profile, play, win)
        db.profiles[(guild_id, user_id)] = profile
        ctx = ContextStub(guild_id, user_id)
        cog = Gambling(SimpleNamespace(db=db))

        result = await cog._atomic_game(
            ctx,
            "100",
            "coinflip",
            lambda bet: {"payout": bet * 2},
            min_bet=10,
        )

        assert result is not None
        assert play["completed"] is True
        assert win["completed"] is True
        assert profile["stats"]["casino_total_bets"] == 1

    asyncio.run(scenario())
