import asyncio

from onboarding import (
    STARTER_SEED_COST,
    Onboarding,
    choose_onboarding_step,
)
from world_modes import (
    GameScope,
    MODE_OPEN,
    MODE_SOLO,
    POLICY_CHOICE,
    POLICY_OPEN,
    POLICY_SOLO,
)


def scope(*, policy=POLICY_SOLO, mode=MODE_SOLO, explicit=True, scope_id=100):
    return GameScope(
        guild_id=100,
        user_id=7,
        policy=policy,
        mode=mode,
        scope_id=scope_id,
        selection_explicit=explicit,
    )


def test_player_choice_without_explicit_selection_starts_with_world_mode():
    step = choose_onboarding_step(
        scope(policy=POLICY_CHOICE, explicit=False),
        {"grams": 500},
        {},
        now=1000,
    )
    assert step.key == "world_mode"
    assert step.command == "/world-mode"


def test_empty_new_profile_is_told_to_buy_the_real_starter_seed():
    step = choose_onboarding_step(
        scope(),
        {
            "grams": 500,
            "level": 1,
            "unlocked_strains": ["schwag", "mexican brick"],
            "items": {},
            "plants": [],
            "flower_stash": {},
        },
        {},
        now=1000,
    )
    assert STARTER_SEED_COST == 15
    assert step.key == "buy_seed"
    assert step.command == "/buy item_name:schwag seed"


def test_owned_seed_is_planted_before_buying_more():
    step = choose_onboarding_step(
        scope(),
        {
            "grams": 485,
            "level": 1,
            "unlocked_strains": ["schwag"],
            "items": {"schwag seed": 1},
            "plants": [],
        },
        {},
        now=1000,
    )
    assert step.key == "plant"
    assert step.command == "/plant strain_name:schwag"


def test_growing_plant_uses_status_until_watering_is_due():
    profile = {
        "grams": 485,
        "level": 1,
        "plants": [
            {
                "strain": "mexican brick",
                "planted_at": 900,
                "last_watered": 900,
                "water_count": 1,
                "quality": 1.0,
            }
        ],
    }
    assert choose_onboarding_step(scope(), profile, {}, now=1000).key == "status"
    assert choose_onboarding_step(scope(), profile, {}, now=1301).key == "water"


def test_ready_plant_is_harvested_before_other_actions():
    step = choose_onboarding_step(
        scope(),
        {
            "grams": 485,
            "level": 1,
            "plants": [
                {
                    "strain": "schwag",
                    "planted_at": 0,
                    "last_watered": 0,
                    "water_count": 1,
                    "quality": 1.0,
                }
            ],
        },
        {},
        now=1000,
    )
    assert step.key == "harvest"
    assert step.command == "/harvest"


def test_harvested_flower_is_sold_before_buying_or_planting():
    step = choose_onboarding_step(
        scope(),
        {
            "grams": 485,
            "flower_stash": {"schwag": 8},
            "items": {"schwag seed": 1},
            "plants": [],
        },
        {},
        now=1000,
    )
    assert step.key == "sell"
    assert step.command == "/sell amount:all"


def test_completed_lab_batch_is_collected_when_no_grow_work_is_waiting():
    step = choose_onboarding_step(
        scope(),
        {
            "grams": 100,
            "processing_queue": [{"finish_time": 500, "type": "hash", "amount": 1}],
        },
        {},
        now=1000,
    )
    assert step.key == "collect"
    assert step.command == "/collect"


def test_seedless_broke_profile_is_sent_to_daily_progression():
    step = choose_onboarding_step(
        scope(),
        {"grams": STARTER_SEED_COST - 1, "items": {}, "plants": []},
        {},
        now=1000,
    )
    assert step.key == "daily"
    assert step.command == "/growdaily"


class FakeDatabase:
    def __init__(self):
        self.worlds = {
            500: {
                "world_mode_config": {
                    "policy": POLICY_OPEN,
                    "default_player_mode": MODE_SOLO,
                    "switch_cooldown_seconds": 604800,
                    "configured": True,
                    "updated_at": 0,
                }
            },
            1: {},
        }
        self.profiles = {
            (1, 7): {
                "grams": 500,
                "level": 1,
                "unlocked_strains": ["schwag"],
                "items": {},
                "plants": [],
                "flower_stash": {},
            }
        }
        self.dirty_profiles = []
        self.dirty_worlds = []

    async def get_world(self, scope_id):
        return self.worlds[int(scope_id)]

    async def get_profile(self, scope_id, user_id):
        return self.profiles[(int(scope_id), int(user_id))]

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.append((int(scope_id), int(user_id)))

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.append(int(scope_id))


class FakeBot:
    def __init__(self, database):
        self.db = database


def test_building_start_guide_reads_open_world_without_dirtying_any_record():
    async def scenario():
        database = FakeDatabase()
        cog = Onboarding(FakeBot(database))

        embed = await cog.build_start_embed(500, 7)

        assert "Open World" in embed.description
        assert database.dirty_profiles == []
        assert database.dirty_worlds == []

    asyncio.run(scenario())
