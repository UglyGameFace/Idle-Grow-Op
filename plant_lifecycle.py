"""Canonical plant timing and readiness helpers.

Weather and equipment are snapshotted when a plant is created. Existing legacy
plants without a ready_at timestamp use a deterministic strain-duration fallback
so their readiness cannot move backward when world weather changes.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from utils import GROWTH_CYCLES, get_plant_grow_time


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def legacy_plant_duration(plant: Mapping[str, Any]) -> int:
    strain = str(plant.get("strain", "schwag") or "schwag").strip().lower()
    config = GROWTH_CYCLES.get(strain, {})
    return max(60, int(_safe_float(config.get("time", 300), 300)))


def plant_ready_at(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
) -> float:
    del profile, world
    ready_at = _safe_float(plant.get("ready_at"), 0)
    if ready_at > 0:
        return ready_at
    planted_at = _safe_float(plant.get("planted_at"), 0)
    return planted_at + legacy_plant_duration(plant)


def plant_duration_seconds(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
) -> int:
    planted_at = _safe_float(plant.get("planted_at"), 0)
    ready_at = plant_ready_at(profile, world, plant)
    return max(1, int(ready_at - planted_at))


def plant_is_ready(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
) -> bool:
    return float(now) >= plant_ready_at(profile, world, plant)


def plant_remaining_seconds(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: Mapping[str, Any],
    *,
    now: float,
) -> int:
    return max(0, int(plant_ready_at(profile, world, plant) - float(now)))


def stamp_plant_ready_at(
    profile: Mapping[str, Any],
    world: Mapping[str, Any],
    plant: MutableMapping[str, Any],
    *,
    planted_at: float,
) -> float:
    start = float(planted_at)
    plant["planted_at"] = start
    duration = get_plant_grow_time(profile, world, plant)
    ready_at = start + max(1, int(duration))
    plant["ready_at"] = ready_at
    return ready_at
