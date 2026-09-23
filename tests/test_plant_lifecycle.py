from plant_lifecycle import (
    legacy_plant_duration,
    plant_duration_seconds,
    plant_is_ready,
    plant_ready_at,
    stamp_plant_ready_at,
)


def test_new_plant_readiness_is_frozen_at_planting_weather():
    profile = {"items": {}}
    world = {"weather": "420 Day 🍁"}
    plant = {"strain": "schwag"}

    ready_at = stamp_plant_ready_at(
        profile,
        world,
        plant,
        planted_at=1_000,
    )

    assert ready_at == 1_150
    assert plant["ready_at"] == 1_150
    assert plant_duration_seconds(profile, world, plant) == 150

    world["weather"] = "Misty 🌫️"

    assert plant_ready_at(profile, world, plant) == 1_150
    assert plant_duration_seconds(profile, world, plant) == 150
    assert plant_is_ready(profile, world, plant, now=1_150) is True


def test_ready_plant_cannot_become_unready_when_weather_changes():
    profile = {"items": {}}
    world = {"weather": "Sunny ☀️"}
    plant = {"strain": "schwag"}

    stamp_plant_ready_at(profile, world, plant, planted_at=1_000)
    assert plant_is_ready(profile, world, plant, now=1_260) is True

    world["weather"] = "Misty 🌫️"

    assert plant_is_ready(profile, world, plant, now=1_260) is True


def test_legacy_plant_fallback_is_deterministic_and_weather_independent():
    profile = {"items": {"led lights": 1, "nutes": 1}}
    plant = {"strain": "schwag", "planted_at": 1_000}

    assert legacy_plant_duration(plant) == 300
    assert plant_ready_at(profile, {"weather": "420 Day 🍁"}, plant) == 1_300
    assert plant_ready_at(profile, {"weather": "Misty 🌫️"}, plant) == 1_300
    assert plant_is_ready(profile, {"weather": "Sunny ☀️"}, plant, now=1_299) is False
    assert plant_is_ready(profile, {"weather": "Misty 🌫️"}, plant, now=1_300) is True


def test_malformed_legacy_timestamp_fails_open_instead_of_trapping_plant():
    profile = {"items": {}}
    plant = {"strain": "schwag", "planted_at": "broken"}

    assert plant_ready_at(profile, {}, plant) == 300
    assert plant_is_ready(profile, {}, plant, now=300) is True
