import asyncio
from types import SimpleNamespace

from game_hub import (
    GameHub,
    CASINO_GAMES,
    GameHubView,
    HubCasinoGameSelect,
    HubConcentrateSelect,
    HubStealTargetSelect,
    SAFE_HUB_COMMANDS,
    _keno_bet_token,
)
from utils import CONCENTRATE_TYPES
from world_modes import GameScope, MODE_SERVER, POLICY_SERVER


def scope():
    return GameScope(
        guild_id=123,
        user_id=42,
        policy=POLICY_SERVER,
        mode=MODE_SERVER,
        scope_id=123,
        selection_explicit=True,
    )


def test_hub_allowlist_excludes_privileged_or_destructive_admin_surfaces():
    assert "setup" not in SAFE_HUB_COMMANDS
    assert "sync" not in SAFE_HUB_COMMANDS
    assert "wipeuser" not in SAFE_HUB_COMMANDS
    assert "setmoney" not in SAFE_HUB_COMMANDS


def test_grow_page_uses_stable_ready_at_after_weather_changes(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1200.0)
    cog = GameHub(SimpleNamespace())
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [
            {
                "strain": "schwag",
                "planted_at": 1000.0,
                "ready_at": 1150.0,
            }
        ],
        "items": {},
        "flower_stash": {},
        "concentrates": {},
    }

    sunny = cog.build_embed(
        scope(),
        profile,
        {"weather": "420 Day 🍁"},
        page="grow",
    )
    misty = cog.build_embed(
        scope(),
        profile,
        {"weather": "Misty 🌫️"},
        page="grow",
    )

    assert "1 plants (1 ready)" in sunny.description
    assert "1 plants (1 ready)" in misty.description
    assert "✅ READY" in sunny.fields[0].value
    assert "✅ READY" in misty.fields[0].value


def test_home_page_recommends_real_next_move_without_requiring_command_memory(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1000.0)
    cog = GameHub(SimpleNamespace())
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
        "flower_stash": {},
        "concentrates": {},
        "unlocked_strains": ["schwag"],
    }

    embed = cog.build_embed(scope(), profile, {}, page="home")

    assert "Recommended Next Move" in embed.fields[0].name
    assert "Play from this panel" in embed.fields[-1].name
    assert "memorize" in embed.fields[-1].value



def _button(view, label):
    return next(
        item
        for item in view.children
        if getattr(item, "label", None) == label
    )


def test_hub_allowlist_includes_only_needed_direct_nested_player_actions():
    assert "steal" in SAFE_HUB_COMMANDS
    assert {
        "crew create",
        "crew join",
        "crew leave",
        "crew info",
        "crew deposit",
        "crew war",
    } <= SAFE_HUB_COMMANDS


def test_grow_inventory_and_lab_buttons_disable_when_action_has_no_work(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1_000.0)
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
        "flower_stash": {},
        "processing_queue": [],
    }

    grow = GameHubView(SimpleNamespace(), 42, 123, page="grow")
    grow.rebuild(scope(), profile, {})
    assert _button(grow, "Harvest Ready").disabled is True

    inventory = GameHubView(SimpleNamespace(), 42, 123, page="inventory")
    inventory.rebuild(scope(), profile, {})
    assert _button(inventory, "Sell All Flower").disabled is True
    assert _button(inventory, "Collect Lab").disabled is True

    lab = GameHubView(SimpleNamespace(), 42, 123, page="lab")
    lab.rebuild(scope(), profile, {})
    assert any(isinstance(item, HubConcentrateSelect) for item in lab.children)
    assert _button(lab, "Start Batch").disabled is True

    profile["plants"] = [
        {"strain": "schwag", "planted_at": 0.0, "ready_at": 500.0}
    ]
    profile["flower_stash"] = {"schwag": 10}
    profile["processing_queue"] = [{"finish_time": 900.0, "amount": 1, "type": "hash"}]
    grow.rebuild(scope(), profile, {})
    inventory.rebuild(scope(), profile, {})
    assert _button(grow, "Harvest Ready").disabled is False
    assert _button(inventory, "Sell All Flower").disabled is False
    assert _button(inventory, "Collect Lab").disabled is False

    lab.selected_concentrate = next(iter(CONCENTRATE_TYPES))
    lab.rebuild(scope(), profile, {})
    assert _button(lab, "Start Batch").disabled is False
    assert _button(lab, "Collect Ready").disabled is False


def test_social_page_changes_from_join_flow_to_member_controls():
    profile = {
        "grams": 100_000,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="social")
    view.rebuild(scope(), profile, {})

    labels = {getattr(item, "label", None) for item in view.children}
    assert "Create Crew" in labels
    assert "Join Crew" in labels
    assert "Crew Info" not in labels

    profile["crew_id"] = "12345"
    view.rebuild(scope(), profile, {})
    labels = {getattr(item, "label", None) for item in view.children}
    assert {"Crew Info", "Deposit", "Leave Crew", "Turf War"} <= labels
    assert "Create Crew" not in labels


def test_crime_page_uses_user_picker_and_only_enables_robbery_after_selection():
    profile = {
        "grams": 500,
        "dirty_cash": 0,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="crime")
    view.rebuild(scope(), profile, {})

    assert any(isinstance(item, HubStealTargetSelect) for item in view.children)
    assert _button(view, "Rob Selected").disabled is True

    view.selected_steal_target = SimpleNamespace(id=77)
    view.rebuild(scope(), profile, {})
    assert _button(view, "Rob Selected").disabled is False


def test_home_page_exposes_one_tap_next_move():
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="home")
    view.rebuild(scope(), profile, {})

    assert _button(view, "Do Next Move").disabled is False



def test_casino_page_uses_game_picker_and_requires_explicit_selection():
    profile = {
        "grams": 5_000,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="casino")
    view.rebuild(scope(), profile, {})

    assert any(isinstance(item, HubCasinoGameSelect) for item in view.children)
    assert _button(view, "Play Selected").disabled is True

    view.selected_casino_game = CASINO_GAMES[0][0]
    view.rebuild(scope(), profile, {})
    assert _button(view, "Play Selected").disabled is False


def test_casino_launcher_allowlist_covers_every_selectable_game():
    assert {key for key, _label, _emoji in CASINO_GAMES} <= SAFE_HUB_COMMANDS



def test_keno_launcher_disambiguates_small_numeric_bets_from_picks():
    assert _keno_bet_token("10") == "$10"
    assert _keno_bet_token("$25") == "$25"
    assert _keno_bet_token("1,000") == "$1000"
    assert _keno_bet_token("1k") == "1k"
    assert _keno_bet_token("half") == "half"
    assert _keno_bet_token("25%") == "25%"



def test_game_hub_timeout_disables_visible_controls_and_edits_message():
    class Message:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    async def scenario():
        profile = {
            "grams": 500,
            "level": 1,
            "xp": 0,
            "plants": [],
            "items": {},
        }
        view = GameHubView(SimpleNamespace(), 42, 123, page="home")
        view.rebuild(scope(), profile, {})
        message = Message()
        view.message = message

        await view.on_timeout()

        assert all(item.disabled for item in view.children)
        assert message.edits == [{"view": view}]

    asyncio.run(scenario())
