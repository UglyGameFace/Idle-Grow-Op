import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import farming as farming_module
import game_hub as game_hub_module
from economy import SHOP_PAGE_SIZE, ShopItemSelect, ShopView, _bounded_listing
from economy_integrity import calculate_harvest_outcome
from farming import Farming
from game_hub import GameHubView, HubSeedSelect
from plant_care import (
    CARE_WATER_THRESHOLD,
    care_multiplier,
    initialize_plant_care,
    plant_care_grade,
    plant_care_status,
    plant_moisture,
    water_plant,
)
from strain_catalog import (
    EXPANDED_STRAIN_COUNT,
    GROWTH_CYCLES,
    LEGACY_GROWTH_CYCLES,
    _game_config,
    generated_seed_shop_items,
)
from strain_media import STRAIN_ARTWORK, get_strain_artwork
from utils import SHOP_ITEMS
from world_modes import GameScope, MODE_SERVER, POLICY_SERVER


def server_scope():
    return GameScope(
        guild_id=123,
        user_id=42,
        policy=POLICY_SERVER,
        mode=MODE_SERVER,
        scope_id=123,
        selection_explicit=True,
    )


def test_catalog_exceeds_requirement_and_preserves_every_legacy_balance_override():
    assert EXPANDED_STRAIN_COUNT >= 500
    assert len(GROWTH_CYCLES) == EXPANDED_STRAIN_COUNT

    for strain, expected in LEGACY_GROWTH_CYCLES.items():
        assert GROWTH_CYCLES[strain] == expected


def test_generated_catalog_stats_are_deterministic_game_values():
    first = _game_config("Regression Example", "Hybrid")
    second = _game_config("Regression Example", "Hybrid")

    assert first == second
    assert first["catalog"] == "expanded"
    assert 1 <= first["level_req"] <= 50
    assert first["time"] >= 60
    assert first["yield"][0] <= first["yield"][1]
    assert first["base_value"] > 0


def test_generated_seed_catalog_covers_every_strain_without_overwriting_legacy_store_values():
    generated = generated_seed_shop_items()

    assert len(generated) == len(GROWTH_CYCLES)
    assert all(
        generated[f"{strain} seed"]["strain_key"] == strain
        for strain in GROWTH_CYCLES
    )
    assert all(f"{strain} seed" in SHOP_ITEMS for strain in GROWTH_CYCLES)
    assert SHOP_ITEMS["schwag seed"]["cost"] == 15
    assert SHOP_ITEMS["og kush seed"]["cost"] == 1200
    assert SHOP_ITEMS["durban poison seed"]["cost"] == 25000


def test_shop_seed_picker_pages_the_full_catalog_instead_of_truncating_at_discord_limit():
    profile = {"grams": 10_000_000, "level": 50, "items": {}}
    view = ShopView(SimpleNamespace(), 42, 123, category="seeds")

    view.rebuild(profile)
    first = next(item for item in view.children if isinstance(item, ShopItemSelect))
    first_values = {option.value for option in first.options}

    assert len(first.options) == SHOP_PAGE_SIZE == 25
    assert view.total_pages > 1
    assert any(getattr(item, "label", None) == "Next" and not item.disabled for item in view.children)

    view.page = 1
    view.rebuild(profile)
    second = next(item for item in view.children if isinstance(item, ShopItemSelect))
    second_values = {option.value for option in second.options}

    assert first_values
    assert second_values
    assert first_values.isdisjoint(second_values)


def test_grow_owned_seed_picker_pages_more_than_twenty_five_owned_strains():
    strains = list(GROWTH_CYCLES)[:30]
    profile = {
        "level": 50,
        "xp": 0,
        "grams": 0,
        "items": {f"{strain} seed": 1 for strain in strains},
        "plants": [],
        "max_pots": 100,
        "flower_stash": {},
        "processing_queue": [],
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="grow")

    view.rebuild(server_scope(), profile, {})
    first = next(item for item in view.children if isinstance(item, HubSeedSelect))

    assert len(first.options) == 25
    assert view.seed_total_pages == 2
    assert any(getattr(item, "action", None) == "seed_next" for item in view.children)

    view.seed_page = 1
    view.rebuild(server_scope(), profile, {})
    second = next(item for item in view.children if isinstance(item, HubSeedSelect))

    assert 1 <= len(second.options) <= 5
    assert {option.value for option in first.options}.isdisjoint(
        {option.value for option in second.options}
    )


def test_grow_seed_page_change_clears_selected_strain_and_quantity():
    async def scenario():
        view = GameHubView(SimpleNamespace(), 42, 123, page="grow")
        view.seed_page = 0
        view.seed_total_pages = 2
        view.selected_seed = "schwag"
        view.selected_plant_quantity = "25"
        view.refresh = AsyncMock()

        await view.handle_action(SimpleNamespace(), "seed_next")

        assert view.seed_page == 1
        assert view.selected_seed is None
        assert view.selected_plant_quantity == "1"
        view.refresh.assert_awaited_once()

    asyncio.run(scenario())


def test_strain_browser_pages_filters_exact_names_first_and_only_attaches_vetted_art():
    cog = Farming(SimpleNamespace())

    catalog_embed, pages = cog.build_strains_embed()
    assert pages > 1
    assert 1 <= len(catalog_embed.fields) <= cog.STRAIN_PAGE_SIZE

    exact_embed, exact_pages = cog.build_strains_embed(query="blue dream")
    artwork = get_strain_artwork("blue dream")

    assert exact_pages == 1
    assert len(exact_embed.fields) == 1
    assert exact_embed.fields[0].name.endswith("Blue Dream")
    assert artwork is not None
    assert exact_embed.thumbnail.url == artwork.image_url
    assert "Artwork:" in exact_embed.description
    assert artwork.source_url in exact_embed.description

    type_embed, type_pages = cog.build_strains_embed(query="sativa")
    assert type_pages >= 1
    assert "matching game strain" in type_embed.description


def test_strain_artwork_registry_is_small_explicit_and_license_vetted():
    assert {"og kush", "blue dream", "sour diesel"} <= set(STRAIN_ARTWORK)

    for strain, artwork in STRAIN_ARTWORK.items():
        assert strain in GROWTH_CYCLES
        assert artwork.image_url.startswith("https://upload.wikimedia.org/")
        assert artwork.source_url.startswith("https://commons.wikimedia.org/wiki/File:")
        assert artwork.author
        assert artwork.license_name == "Public Domain"
        assert artwork.attribution_required is False


def test_inventory_listing_stays_within_discord_field_limit_and_reports_overflow():
    listing = _bounded_listing(
        [f"**Seed {index}**: x1" for index in range(100)],
        limit=18,
    )

    assert len(listing) <= 1024
    assert "and **82 more**" in listing


def _plant(*, planted_at=0.0, ready_at=5000.0):
    plant = {
        "strain": "schwag",
        "planted_at": planted_at,
        "ready_at": ready_at,
    }
    initialize_plant_care(plant, now=planted_at)
    return plant


def test_game_moisture_decays_and_wicking_controller_slow_loss_without_touching_ready_at():
    now = 1200.0
    base_plant = _plant()
    ready_at = base_plant["ready_at"]

    base = plant_moisture({}, {}, base_plant, now=now)
    wicking = plant_moisture(
        {"items": {"wicking tray": 1}},
        {},
        _plant(),
        now=now,
    )
    controller = plant_moisture(
        {"items": {"environment controller": 1}},
        {},
        _plant(),
        now=now,
    )
    combined = plant_moisture(
        {"items": {"wicking tray": 1, "environment controller": 1}},
        {},
        _plant(),
        now=now,
    )

    assert base is not None
    assert base <= CARE_WATER_THRESHOLD
    assert wicking > base
    assert controller > base
    assert combined > wicking
    assert combined > controller
    assert base_plant["ready_at"] == ready_at


def test_water_only_mutates_plants_in_the_care_window_and_never_ready_plants():
    fresh = _plant()
    fresh_before = dict(fresh["care"])
    fresh_result = water_plant({}, {}, fresh, now=100.0)
    assert fresh_result["watered"] is False
    assert fresh_result["reason"] == "still_fresh"
    assert fresh["care"] == fresh_before

    thirsty = _plant()
    ready_at = thirsty["ready_at"]
    thirsty_result = water_plant({}, {}, thirsty, now=1200.0)
    assert thirsty_result["watered"] is True
    assert thirsty["care"]["waterings"] == 1
    assert thirsty["ready_at"] == ready_at

    ready = _plant(ready_at=1000.0)
    ready_before = dict(ready["care"])
    ready_result = water_plant({}, {}, ready, now=1000.0)
    assert ready_result["watered"] is False
    assert ready_result["reason"] == "ready"
    assert ready["care"] == ready_before


def test_legacy_plants_are_neutral_and_not_retroactively_penalized():
    legacy = {"strain": "schwag", "planted_at": 0.0, "ready_at": 5000.0}

    label, multiplier, score = plant_care_grade({}, {}, legacy, now=2500.0)

    assert (label, multiplier, score) == ("Standard", 1.0, 75)
    assert care_multiplier({}, {}, legacy, now=2500.0) == 1.0
    assert plant_care_status({}, {}, legacy, now=2500.0) == "💧 Neutral"


def test_moisture_meter_reveals_exact_game_percentage_without_changing_care():
    plant = _plant()
    broad = plant_care_status({}, {}, plant, now=1200.0, exact=False)
    exact = plant_care_status({}, {}, plant, now=1200.0, exact=True)

    assert "%" not in broad
    assert "%" in exact
    assert "Ready to Water" in broad


def test_environment_controller_only_modestly_improves_care_harvest_multiplier():
    now = 3600.0
    craft = _plant(ready_at=3600.0)
    craft["care"].update(
        {"moisture": 100.0, "updated_at": now, "waterings": 2, "late_waterings": 0}
    )
    stressed = _plant(ready_at=3600.0)
    stressed["care"].update(
        {"moisture": 0.0, "updated_at": now, "waterings": 0, "late_waterings": 0}
    )

    craft_grade = plant_care_grade({}, {}, craft, now=now)
    controlled_grade = plant_care_grade(
        {"items": {"environment controller": 1}},
        {},
        craft,
        now=now,
    )
    stressed_grade = plant_care_grade({}, {}, stressed, now=now)

    assert craft_grade[0:2] == ("Craft", 1.15)
    assert controlled_grade[1] == pytest.approx(1.18)
    assert stressed_grade[0:2] == ("Stressed", 0.90)


def test_harvest_outcome_applies_per_plant_care_multiplier():
    now = 3600.0
    craft = _plant(ready_at=3600.0)
    craft["care"].update(
        {"moisture": 100.0, "updated_at": now, "waterings": 2, "late_waterings": 0}
    )
    stressed = _plant(ready_at=3600.0)
    stressed["care"].update(
        {"moisture": 0.0, "updated_at": now, "waterings": 0, "late_waterings": 0}
    )
    configs = {"schwag": {"yield": (10, 10)}}

    outcome = calculate_harvest_outcome(
        [craft, stressed],
        now=now,
        strain_configs=configs,
        grow_time_for_plant=lambda _plant: 3600,
        yield_multiplier=1.0,
        randint=lambda minimum, _maximum: minimum,
        yield_multiplier_for_plant=lambda plant: care_multiplier(
            {},
            {},
            plant,
            now=now,
        ),
    )

    assert outcome["harvested_count"] == 2
    assert outcome["total_yield"] == 20
    assert outcome["flower_by_strain"]["schwag"] == 20


class _WaterDatabase:
    def __init__(self, profile):
        self.lock = asyncio.Lock()
        self.profile = profile
        self.dirty = []

    async def get_profile(self, scope_id, user_id):
        return self.profile

    async def get_world(self, scope_id):
        return {}

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty.append((scope_id, user_id))


class _WaterContext:
    def __init__(self):
        self.guild = SimpleNamespace(id=123)
        self.author = SimpleNamespace(id=42)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_water_command_counts_only_real_waterings_and_advances_progress_once(monkeypatch):
    async def scenario():
        thirsty = _plant(ready_at=5000.0)
        fresh = _plant(ready_at=5000.0)
        fresh["care"]["updated_at"] = 1150.0
        ready = _plant(ready_at=1000.0)
        profile = {
            "level": 5,
            "xp": 0,
            "grams": 0,
            "items": {},
            "plants": [thirsty, fresh, ready],
            "stats": {},
            "achievements": [],
        }
        db = _WaterDatabase(profile)
        progress = []
        achievement_checks = []

        async def resolve_scope(_db, guild_id, user_id):
            return SimpleNamespace(scope_id=123)

        monkeypatch.setattr(farming_module, "resolve_game_scope", resolve_scope)
        monkeypatch.setattr(farming_module.time, "time", lambda: 1200.0)
        monkeypatch.setattr(
            farming_module,
            "add_progress",
            lambda _user, event, amount, **_kwargs: progress.append((event, amount)),
        )
        monkeypatch.setattr(
            farming_module,
            "check_achievements",
            lambda _user: achievement_checks.append(True),
        )

        ctx = _WaterContext()
        await Farming.water.callback(Farming(SimpleNamespace(db=db)), ctx)

        assert profile["stats"]["watered"] == 1
        assert progress == [("water", 1)]
        assert achievement_checks == [True]
        assert db.dirty == [(123, 42)]
        assert thirsty["care"]["waterings"] == 1
        assert fresh["care"]["waterings"] == 0
        assert ready["care"]["waterings"] == 0

    asyncio.run(scenario())


def test_hub_water_all_enables_only_when_a_growing_plant_needs_care(monkeypatch):
    view = GameHubView(SimpleNamespace(), 42, 123, page="grow")
    profile = {
        "level": 50,
        "xp": 0,
        "grams": 0,
        "items": {"schwag seed": 1},
        "plants": [_plant(ready_at=5000.0)],
        "max_pots": 10,
        "flower_stash": {},
        "processing_queue": [],
    }

    monkeypatch.setattr(game_hub_module.time, "time", lambda: 1200.0)
    view.rebuild(server_scope(), profile, {})
    water = next(item for item in view.children if getattr(item, "action", None) == "water")
    assert water.disabled is False

    monkeypatch.setattr(game_hub_module.time, "time", lambda: 6000.0)
    view.rebuild(server_scope(), profile, {})
    water = next(item for item in view.children if getattr(item, "action", None) == "water")
    assert water.disabled is True
