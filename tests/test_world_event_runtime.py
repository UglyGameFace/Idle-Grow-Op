import tasks as tasks_module
from tasks import Tasks
from utils import SPECIAL_EVENTS, WEATHER_TYPES


def test_only_functional_special_events_are_selectable():
    assert set(SPECIAL_EVENTS) == {"MARKET_BOOM", "MARKET_CRASH"}
    for event in SPECIAL_EVENTS.values():
        assert event["effect"] == "market_multiplier"
        assert float(event["multiplier"]) > 0


def test_special_event_uses_its_declared_market_multiplier(monkeypatch):
    monkeypatch.setattr(tasks_module.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(tasks_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(tasks_module.random, "choice", lambda values: "MARKET_BOOM")

    world = {"event": None, "market_multiplier": 1.0}

    changed = Tasks._advance_world(world)

    assert changed is True
    assert world["event"]["id"] == "MARKET_BOOM"
    assert world["market_multiplier"] == SPECIAL_EVENTS["MARKET_BOOM"]["multiplier"]


def test_weather_table_only_contains_runtime_owned_modifiers():
    assert WEATHER_TYPES
    for weather in WEATHER_TYPES.values():
        assert set(weather) == {"growth", "price"}
        assert float(weather["growth"]) > 0
        assert float(weather["price"]) > 0
