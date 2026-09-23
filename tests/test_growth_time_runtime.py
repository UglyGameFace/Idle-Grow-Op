from utils import get_plant_grow_time


def test_weather_growth_speed_changes_real_grow_time():
    user = {"items": {}}
    plant = {"strain": "schwag"}

    assert get_plant_grow_time(user, {"weather": "Sunny ☀️"}, plant) == 260
    assert get_plant_grow_time(user, {"weather": "420 Day 🍁"}, plant) == 150
    assert get_plant_grow_time(user, {"weather": "Unknown"}, plant) == 300


def test_weather_and_equipment_modifiers_compose_once():
    user = {"items": {"led lights": 1}}
    plant = {"strain": "schwag"}

    assert get_plant_grow_time(user, {"weather": "Sunny ☀️"}, plant) == 208
