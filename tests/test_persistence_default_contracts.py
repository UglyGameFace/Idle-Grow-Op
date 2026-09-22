from profile_signature_contracts import (
    GLOBAL_PRIVACY_KEY,
    GUILD_PRIVACY_KEY,
    IDENTITY_KEY,
    SIGNATURE_CONFIG_KEY,
    SIGNATURE_STATE_KEY,
    default_global_privacy,
    default_guild_privacy,
    default_profile_identity,
    default_signature_config,
    default_signature_state,
)
from guild_config import WORLD_SETTINGS_KEY
from scoped_database import make_default_account, make_default_profile, make_default_world
from world_mode_contracts import OPEN_WORLD_SCOPE_ID, WORLD_MODE_CONFIG_KEY, new_world_mode_config


def test_database_profile_signature_defaults_use_canonical_builders():
    account = make_default_account()
    profile = make_default_profile()
    world = make_default_world()

    assert account[IDENTITY_KEY] == default_profile_identity()
    assert account[GLOBAL_PRIVACY_KEY] == default_global_privacy()
    assert profile[GUILD_PRIVACY_KEY] == default_guild_privacy()
    assert world[SIGNATURE_CONFIG_KEY] == default_signature_config()
    assert world[SIGNATURE_STATE_KEY] == default_signature_state()


def test_database_world_mode_default_uses_canonical_builder():
    world = make_default_world()

    assert world[WORLD_MODE_CONFIG_KEY] == new_world_mode_config()


def test_removed_durability_state_is_not_created_for_new_profiles():
    profile = make_default_profile()

    assert "item_wear" not in profile


def test_database_world_settings_use_canonical_key():
    world = make_default_world()

    assert WORLD_SETTINGS_KEY in world
    assert world[WORLD_SETTINGS_KEY] == {}


def test_open_world_scope_is_owned_by_pure_world_mode_contract():
    import world_modes
    import world_mode_contracts

    assert OPEN_WORLD_SCOPE_ID == 1
    assert world_modes.OPEN_WORLD_SCOPE_ID == world_mode_contracts.OPEN_WORLD_SCOPE_ID


def test_new_world_starts_with_no_phantom_district_bonus():
    world = make_default_world()

    assert world["district"] == {
        "owner_crew_id": None,
        "owner_name": None,
        "multiplier": 1.0,
        "expires_at": 0,
    }
