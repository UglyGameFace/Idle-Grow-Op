from economy_integrity import calculate_harvest_outcome


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
    try:
        calculate_harvest_outcome(
            [],
            now=0,
            strain_configs={},
            grow_time_for_plant=lambda plant: 1,
            yield_multiplier=-1,
            randint=lambda minimum, maximum: minimum,
        )
    except ValueError as error:
        assert "yield_multiplier" in str(error)
    else:
        raise AssertionError("negative multiplier should be rejected")
