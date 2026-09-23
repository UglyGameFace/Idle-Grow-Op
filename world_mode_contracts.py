"""Pure world-mode persistence contract with no Discord dependency."""

from __future__ import annotations

from typing import Any


# Reserved persistence scope for the cross-server Open World.
# Discord guild snowflakes are far larger than this value.
OPEN_WORLD_SCOPE_ID = 1

WORLD_MODE_CONFIG_KEY = "world_mode_config"
PLAYER_MODE_SELECTION_KEY = "world_mode_selection"

POLICY_SERVER = "server"
POLICY_SOLO = "solo"
POLICY_OPEN = "open"
POLICY_CHOICE = "choice"

MODE_SERVER = "server"
MODE_SOLO = "solo"
MODE_OPEN = "open"

VALID_POLICIES = {POLICY_SERVER, POLICY_SOLO, POLICY_OPEN, POLICY_CHOICE}
VALID_PLAYER_MODES = {MODE_SOLO, MODE_OPEN}

DEFAULT_PLAYER_MODE = MODE_SOLO
DEFAULT_SWITCH_COOLDOWN_SECONDS = 7 * 24 * 60 * 60


def new_world_mode_config() -> dict[str, Any]:
    """Safe default for a newly created guild world."""
    return {
        "policy": POLICY_SOLO,
        "default_player_mode": DEFAULT_PLAYER_MODE,
        "switch_cooldown_seconds": DEFAULT_SWITCH_COOLDOWN_SECONDS,
        "configured": False,
        "updated_at": 0,
    }


def legacy_world_mode_config() -> dict[str, Any]:
    """Compatibility interpretation for worlds created before mode controls."""
    return {
        "policy": POLICY_SERVER,
        "default_player_mode": DEFAULT_PLAYER_MODE,
        "switch_cooldown_seconds": DEFAULT_SWITCH_COOLDOWN_SECONDS,
        "configured": False,
        "legacy_compatibility": True,
        "updated_at": 0,
    }
