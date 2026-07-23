from collections.abc import Callable, Iterable, Mapping
from math import ceil
from typing import Any


def require_positive_amount(value: Any, *, minimum: int = 1) -> int:
    """Return a validated positive integer amount.

    Economy commands must reject booleans, zero, negatives, floats, and strings
    that are not exact integers before mutating player state.
    """
    if isinstance(value, bool):
        raise ValueError("amount must be an integer")

    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("amount must be an integer") from exc

    if str(value).strip() not in {str(amount), f"+{amount}"} and not isinstance(value, int):
        raise ValueError("amount must be an integer")
    if amount < minimum:
        raise ValueError(f"amount must be at least {minimum}")
    return amount


def flower_required_for_output(output_amount: Any, yield_ratio: Any) -> int:
    """Calculate flower input without ever rounding the cost down."""
    amount = require_positive_amount(output_amount)
    ratio = float(yield_ratio)
    if ratio <= 0:
        raise ValueError("yield ratio must be positive")
    return max(1, ceil(amount / ratio))


def validate_auction_prices(start_price: Any, buyout: Any = 0) -> tuple[int, int]:
    """Validate an auction's escrow prices before removing the seller's item."""
    start = require_positive_amount(start_price)
    try:
        buyout_amount = int(buyout)
    except (TypeError, ValueError) as exc:
        raise ValueError("buyout must be an integer") from exc

    if buyout_amount < 0:
        raise ValueError("buyout cannot be negative")
    if buyout_amount and buyout_amount < start:
        raise ValueError("buyout cannot be lower than the starting price")
    return start, buyout_amount


def validate_bid_amount(amount: Any, *, current_bid: Any, end_time: Any, now: float) -> int:
    """Validate a bid before any bidder or seller balance is touched."""
    bid = require_positive_amount(amount)
    if now >= float(end_time):
        raise ValueError("auction has expired")
    if bid <= int(current_bid):
        raise ValueError("bid must be higher than the current bid")
    return bid


def pot_upgrade_capacity(
    user: Mapping[str, Any],
    item_name: str,
    limits: Mapping[str, int],
    *,
    base_capacity: int = 3,
) -> int:
    """Return the new pot capacity or reject a purchase beyond its item limit."""
    clean_name = str(item_name).strip().lower()
    if clean_name not in limits:
        raise ValueError("unknown pot upgrade")

    items = user.get("items", {})
    owned = int(items.get(clean_name, 0)) if isinstance(items, Mapping) else 0
    limit = max(0, int(limits[clean_name]))
    if owned >= limit:
        raise ValueError("pot upgrade limit reached")

    current = max(base_capacity, int(user.get("max_pots", base_capacity)))
    return current + 1


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
