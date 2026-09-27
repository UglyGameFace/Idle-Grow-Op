"""Gameified plant-care mechanics.

This module intentionally models abstract in-game care, not real cultivation
instructions. Plant readiness remains owned by plant_lifecycle; care only affects
the harvest multiplier and UI condition labels.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from plant_lifecycle import plant_duration_seconds, plant_is_ready
from utils import inv_get


CARE_STATE_KEY = "care"
CARE_MAX = 100.0
CARE_WATER_THRESHOLD = 55.0
CARE_CRITICAL_THRESHOLD = 20.0
CARE_DRY_FLOOR_SECONDS = 15 * 60


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, minimum: float = 0.0, maximum: float = CARE_MAX) -> float:
    return max(minimum, min(maximum, float(value)))


def initialize_plant_care(
    plant: MutableMapping[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    state = {
        "moisture": CARE_MAX,
        "updated_at": float(now),
        "waterings": 0,
        "late_waterings": 0,
    }
    plant[CARE_STATE_KEY] = state
    return state


def _care_state(plant: Mapping[str, Any]) -> Mapping[str, Any] | None:
    state = plant.get(CARE_STATE_KEY)
    return state if isinstance(state, Mapping) else None


def care_loss_multiplier(profile: Mapping[str, Any]) -> float:
    multiplier = 1.0
    if inv_get(profile, "wicking tray") > 0:
        multiplier *= 0.75
    if inv_get(profile, "environment controller") > 0:
        multiplier *= 0.85
    return max(0.45, multiplier)


def care_dryout_seconds(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
) -> float:
    duration = max(1, plant_duration_seconds(profile, world, plant))
    return max(float(CARE_DRY_FLOOR_SECONDS), float(duration) * 0.45)


def plant_moisture(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
) -> float | None:
    state = _care_state(plant)
    if state is None:
        return None

    baseline = _clamp(_float(state.get("moisture"), CARE_MAX))
    updated_at = _float(
        state.get("updated_at"),
        _float(plant.get("planted_at"), float(now)),
    )
    elapsed = max(0.0, float(now) - updated_at)
    dryout = care_dryout_seconds(profile, world, plant)
    loss = (elapsed / dryout) * CARE_MAX * care_loss_multiplier(profile)
    return _clamp(baseline - loss)


def plant_care_status(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
    exact: bool = False,
) -> str:
    moisture = plant_moisture(profile, world, plant, now=now)
    if moisture is None:
        return "💧 Neutral"

    if moisture >= 70:
        label = "Fresh"
    elif moisture >= 40:
        label = "Ready to Water"
    elif moisture > 0:
        label = "Dry"
    else:
        label = "Stressed"

    if exact:
        return f"💧 {int(round(moisture))}% • {label}"
    return f"💧 {label}"


def water_plant(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: MutableMapping[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    if plant_is_ready(profile, world, plant, now=float(now)):
        return {"watered": False, "reason": "ready", "moisture": 100.0}

    state = plant.get(CARE_STATE_KEY)
    if not isinstance(state, MutableMapping):
        state = {
            "moisture": CARE_WATER_THRESHOLD,
            "updated_at": float(now),
            "waterings": 0,
            "late_waterings": 0,
        }
        plant[CARE_STATE_KEY] = state

    moisture = plant_moisture(profile, world, plant, now=float(now))
    moisture = CARE_WATER_THRESHOLD if moisture is None else moisture
    if moisture > CARE_WATER_THRESHOLD:
        return {
            "watered": False,
            "reason": "still_fresh",
            "moisture": moisture,
        }

    state["moisture"] = CARE_MAX
    state["updated_at"] = float(now)
    state["waterings"] = max(0, int(state.get("waterings", 0) or 0)) + 1
    if moisture < CARE_CRITICAL_THRESHOLD:
        state["late_waterings"] = (
            max(0, int(state.get("late_waterings", 0) or 0)) + 1
        )

    return {
        "watered": True,
        "reason": "watered",
        "moisture": moisture,
    }


def expected_waterings(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
) -> int:
    duration = max(1, plant_duration_seconds(profile, world, plant))
    dryout = care_dryout_seconds(profile, world, plant)
    return max(0, min(4, int(duration // dryout)))


def plant_care_grade(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
) -> tuple[str, float, int]:
    state = _care_state(plant)
    if state is None:
        return "Standard", 1.0, 75

    moisture = plant_moisture(profile, world, plant, now=float(now))
    moisture = 0.0 if moisture is None else moisture
    expected = expected_waterings(profile, world, plant)
    actual = max(0, int(state.get("waterings", 0) or 0))
    late = max(0, int(state.get("late_waterings", 0) or 0))

    coverage = 1.0 if expected == 0 else min(1.0, actual / expected)
    score = 45.0 + (30.0 * coverage) + (25.0 * (moisture / CARE_MAX))
    score -= min(20.0, late * 5.0)

    if inv_get(profile, "environment controller") > 0:
        score += 3.0

    score_i = max(0, min(100, int(round(score))))
    if score_i >= 90:
        label, multiplier = "Craft", 1.15
    elif score_i >= 75:
        label, multiplier = "Healthy", 1.08
    elif score_i >= 55:
        label, multiplier = "Standard", 1.00
    else:
        label, multiplier = "Stressed", 0.90

    if inv_get(profile, "environment controller") > 0:
        multiplier = min(1.18, multiplier + 0.03)

    return label, multiplier, score_i


def care_multiplier(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
) -> float:
    return plant_care_grade(profile, world, plant, now=now)[1]
