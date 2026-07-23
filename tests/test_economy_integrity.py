import pytest

from economy_integrity import (
    calculate_harvest_outcome,
    flower_required_for_output,
    pot_upgrade_capacity,
    require_positive_amount,
    validate_auction_prices,
    validate_bid_amount,
)


def test_mixed_strain_harvest_preserves_per_strain_yields():
    plants = [
        {"strain": "schwag", "planted_at": 0},
        {"strain": "og kush", "planted_at": 0},
        {"strain": "schwag", "planted_at": 95},
    ]
    configs = {
        "schwag": {"yield": (5, 10)},
        "og kush": {"yield": (20, 40)},
    }
    rolls = iter([7, 30])

    outcome = calculate_harvest_outcome(
        plants,
        now=100,
        strain_configs=configs,
        grow_time_for_plant=lambda plant: 10,
        yield_multiplier=1.0,
        randint=lambda minimum, maximum: next(rolls),
    )

    assert outcome["flower_by_strain"] == {"schwag": 7, "og kush": 30}
    assert outcome["total_yield"] == 37
    assert outcome["harvested_count"] == 2
    assert outcome["remaining_plants"] == [plants[2]]


def test_harvest_outcome_contains_no_cash_credit():
    outcome = calculate_harvest_outcome(
        [{"strain": "schwag", "planted_at": 0}],
        now=100,
        strain_configs={"schwag": {"yield": (5, 10)}},
        grow_time_for_plant=lambda plant: 10,
        yield_multiplier=1.0,
        randint=lambda minimum, maximum: 6,
    )

    assert outcome["flower_by_strain"] == {"schwag": 6}
    assert "grams" not in outcome
    assert "cash" not in outcome
    assert "money" not in outcome


def test_unknown_plant_is_preserved_instead_of_deleted():
    plant = {"strain": "legacy mystery", "planted_at": 0}

    outcome = calculate_harvest_outcome(
        [plant],
        now=1000,
        strain_configs={},
        grow_time_for_plant=lambda value: 10,
        yield_multiplier=1.0,
        randint=lambda minimum, maximum: minimum,
    )

    assert outcome["harvested_count"] == 0
    assert outcome["remaining_plants"] == [plant]


def test_yield_multiplier_is_applied_once_per_plant():
    outcome = calculate_harvest_outcome(
        [{"strain": "schwag", "planted_at": 0}],
        now=100,
        strain_configs={"schwag": {"yield": (5, 10)}},
        grow_time_for_plant=lambda plant: 10,
        yield_multiplier=1.5,
        randint=lambda minimum, maximum: 8,
    )

    assert outcome["flower_by_strain"] == {"schwag": 12}
    assert outcome["total_yield"] == 12


def test_negative_yield_multiplier_is_rejected():
    with pytest.raises(ValueError, match="yield_multiplier"):
        calculate_harvest_outcome(
            [],
            now=0,
            strain_configs={},
            grow_time_for_plant=lambda plant: 1,
            yield_multiplier=-1,
            randint=lambda minimum, maximum: minimum,
        )


@pytest.mark.parametrize("value", [0, -1, -100, True, 1.5, "1.5", "nope"])
def test_non_positive_or_non_integer_economy_amounts_are_rejected(value):
    with pytest.raises(ValueError):
        require_positive_amount(value)


def test_positive_amount_can_enforce_a_minimum_bet():
    assert require_positive_amount(10, minimum=10) == 10
    with pytest.raises(ValueError):
        require_positive_amount(9, minimum=10)


def test_flower_requirement_rounds_up_instead_of_undercharging():
    assert flower_required_for_output(1, 0.20) == 5
    assert flower_required_for_output(2, 0.15) == 14
    assert flower_required_for_output(10, 0.12) == 84


def test_flower_requirement_rejects_invalid_output_and_ratio():
    with pytest.raises(ValueError):
        flower_required_for_output(0, 0.2)
    with pytest.raises(ValueError):
        flower_required_for_output(1, 0)


def test_auction_prices_must_be_positive_and_coherent():
    assert validate_auction_prices(100, 500) == (100, 500)
    assert validate_auction_prices(100, 0) == (100, 0)
    with pytest.raises(ValueError):
        validate_auction_prices(0, 0)
    with pytest.raises(ValueError):
        validate_auction_prices(100, -1)
    with pytest.raises(ValueError):
        validate_auction_prices(100, 99)


def test_expired_or_non_increasing_bids_are_rejected():
    assert validate_bid_amount(101, current_bid=100, end_time=200, now=100) == 101
    with pytest.raises(ValueError, match="expired"):
        validate_bid_amount(101, current_bid=100, end_time=100, now=100)
    with pytest.raises(ValueError, match="higher"):
        validate_bid_amount(100, current_bid=100, end_time=200, now=100)


def test_pot_upgrade_limit_is_enforced_before_capacity_changes():
    user = {"max_pots": 5, "items": {"clay pot": 2}}
    assert pot_upgrade_capacity(user, "clay pot", {"clay pot": 3}) == 6

    user["items"]["clay pot"] = 3
    with pytest.raises(ValueError, match="limit"):
        pot_upgrade_capacity(user, "clay pot", {"clay pot": 3})
