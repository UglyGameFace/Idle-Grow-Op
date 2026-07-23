from collections.abc import Callable, Iterable, Mapping
from typing import Any


def calculate_harvest_outcome(
    plants: Iterable[dict[str, Any]],
    *,
    now: float,
    strain_configs: Mapping[str, Mapping[str, Any]],
    grow_time_for_plant: Callable[[dict[str, Any]], int],
    yield_multiplier: float,
    randint: Callable[[int, int], int],
) -> dict[str, Any]:
    """Calculate a harvest without mutating player state.

    Flower is tracked per strain. This helper deliberately knows nothing about
    cash so harvesting cannot accidentally credit currency.
    """
    if yield_multiplier < 0:
        raise ValueError("yield_multiplier cannot be negative")

    remaining_plants: list[dict[str, Any]] = []
    flower_by_strain: dict[str, int] = {}
    total_xp = 0
    harvested_count = 0

    for plant in plants:
        strain = str(plant.get("strain", "")).strip().lower()
        config = strain_configs.get(strain)
        if config is None:
            # Preserve unknown/malformed plants rather than deleting player data.
            remaining_plants.append(plant)
            continue

        planted_at = float(plant.get("planted_at", now))
        grow_time = max(1, int(grow_time_for_plant(plant)))
        if now - planted_at < grow_time:
            remaining_plants.append(plant)
            continue

        minimum, maximum = config.get("yield", (5, 10))
        minimum = max(0, int(minimum))
        maximum = max(minimum, int(maximum))
        base_yield = randint(minimum, maximum)
        final_yield = max(0, int(base_yield * yield_multiplier))

        flower_by_strain[strain] = flower_by_strain.get(strain, 0) + final_yield
        total_xp += int(grow_time / 100) + 5
        harvested_count += 1

    return {
        "remaining_plants": remaining_plants,
        "flower_by_strain": flower_by_strain,
        "total_yield": sum(flower_by_strain.values()),
        "total_xp": total_xp,
        "harvested_count": harvested_count,
    }
