from tasks import MAJOR_MARKET_CHANGE, Tasks


def test_special_event_start_generates_announcement():
    before = {"event": {}, "weather": "Sunny ☀️", "market_multiplier": 1.0}
    world = {
        "event": {"id": "festival", "name": "Harvest Festival"},
        "weather": "Sunny ☀️",
        "market_multiplier": 1.5,
    }

    embed = Tasks._build_world_announcement(before, world)

    assert embed is not None
    assert embed.title == "🚨 Special World Event Started"
    assert "Harvest Festival" in embed.description
    assert "1.50x" in embed.description


def test_special_event_end_generates_announcement():
    before = {
        "event": {"id": "festival", "name": "Harvest Festival"},
        "weather": "Sunny ☀️",
        "market_multiplier": 1.5,
    }
    world = {"event": None, "weather": "Rainy 🌧️", "market_multiplier": 1.0}

    embed = Tasks._build_world_announcement(before, world)

    assert embed is not None
    assert embed.title == "✅ Special World Event Ended"
    assert "Harvest Festival" in embed.description
    assert "1.00x" in embed.description


def test_routine_weather_roll_does_not_generate_announcement():
    before = {"event": {}, "weather": "Sunny ☀️", "market_multiplier": 1.0}
    world = {"event": None, "weather": "Rainy 🌧️", "market_multiplier": 1.05}

    assert Tasks._build_world_announcement(before, world) is None


def test_major_market_change_generates_announcement_at_threshold():
    before = {"event": {}, "weather": "Sunny ☀️", "market_multiplier": 1.0}
    world = {
        "event": None,
        "weather": "Heat Wave 🔥",
        "market_multiplier": 1.0 + MAJOR_MARKET_CHANGE,
    }

    embed = Tasks._build_world_announcement(before, world)

    assert embed is not None
    assert embed.title == "📈 Market Surged"
    assert "Heat Wave" in embed.description


def test_small_market_change_stays_silent():
    before = {"event": {}, "weather": "Sunny ☀️", "market_multiplier": 1.0}
    world = {
        "event": None,
        "weather": "Cloudy ☁️",
        "market_multiplier": 1.0 + MAJOR_MARKET_CHANGE - 0.01,
    }

    assert Tasks._build_world_announcement(before, world) is None
