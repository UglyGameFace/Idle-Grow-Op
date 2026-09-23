from types import SimpleNamespace

from game_hub import GameHub, SAFE_HUB_COMMANDS
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
