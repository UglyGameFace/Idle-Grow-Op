"""Pure profile/signature persistence contracts.

This module intentionally has no Discord dependency so persistence defaults and
runtime UI can share one canonical schema.
"""

from __future__ import annotations

from typing import Any


SIGNATURE_CONFIG_KEY = "profile_signature_config"
SIGNATURE_STATE_KEY = "profile_signature_state"
SIGNATURE_ENABLED_KEY = "enabled"
SIGNATURE_CHANNELS_KEY = "channel_ids"
SIGNATURE_ALLOWED_FIELDS_KEY = "allowed_fields"

IDENTITY_KEY = "profile_identity"
GLOBAL_PRIVACY_KEY = "profile_privacy"
GUILD_PRIVACY_KEY = "profile_signature_privacy"

FIELD_LABELS = {
    "level": "Level & XP",
    "crew": "Crew",
    "grow_status": "Grow status",
    "wealth": "Balance / net worth",
    "inventory": "Inventory summary",
    "rank": "Server rank",
    "achievements": "Achievements",
    "activity": "Activity details",
    "platforms": "Gaming & social platforms",
}
ALL_PROFILE_FIELDS = tuple(FIELD_LABELS)
DEFAULT_VISIBLE_FIELDS = frozenset({"level", "crew", "grow_status"})
DEFAULT_SERVER_ALLOWED_FIELDS = frozenset(
    {"level", "crew", "grow_status", "rank", "achievements", "platforms"}
)


def default_profile_identity() -> dict[str, Any]:
    return {"platforms": {}}


def default_global_privacy() -> dict[str, Any]:
    return {
        "signature_enabled": True,
        "visible_fields": sorted(DEFAULT_VISIBLE_FIELDS),
    }


def default_guild_privacy() -> dict[str, Any]:
    return {
        "signature_disabled": False,
        "hidden_fields": [],
    }


def default_signature_config() -> dict[str, Any]:
    return {
        SIGNATURE_ENABLED_KEY: False,
        SIGNATURE_CHANNELS_KEY: [],
        SIGNATURE_ALLOWED_FIELDS_KEY: sorted(DEFAULT_SERVER_ALLOWED_FIELDS),
    }


def default_signature_state() -> dict[str, Any]:
    return {}
