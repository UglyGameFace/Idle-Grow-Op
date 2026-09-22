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
from scoped_database import make_default_account, make_default_profile, make_default_world
from world_mode_contracts import WORLD_MODE_CONFIG_KEY, new_world_mode_config


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
