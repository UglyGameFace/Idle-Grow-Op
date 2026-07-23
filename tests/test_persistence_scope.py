import pytest

from persistence_scope import (
    global_account_key,
    guild_profile_key,
    guild_world_key,
    parse_cache_key,
)


def test_global_account_key_is_cross_server_identity_only():
    key = global_account_key(123)
    assert key.cache_key == "account:123"
    assert key.guild_id is None
    assert key.user_id == "123"


def test_guild_profile_key_isolated_by_guild_and_user():
    first = guild_profile_key(10, 123)
    second = guild_profile_key(20, 123)

    assert first.cache_key == "profile:10:123"
    assert second.cache_key == "profile:20:123"
    assert first != second


def test_guild_world_key_isolated_by_guild():
    assert guild_world_key(10).cache_key == "world:10"
    assert guild_world_key(20).cache_key == "world:20"


@pytest.mark.parametrize(
    "raw",
    ["account:123", "profile:10:123", "world:10"],
)
def test_cache_keys_round_trip(raw):
    assert parse_cache_key(raw).cache_key == raw


@pytest.mark.parametrize(
    "factory,args",
    [
        (global_account_key, (0,)),
        (global_account_key, (-1,)),
        (global_account_key, (True,)),
        (guild_profile_key, (0, 1)),
        (guild_profile_key, (1, 0)),
        (guild_world_key, ("nope",)),
    ],
)
def test_invalid_snowflakes_are_rejected(factory, args):
    with pytest.raises(ValueError):
        factory(*args)


def test_unscoped_legacy_keys_are_not_accepted():
    with pytest.raises(ValueError):
        parse_cache_key("123")
    with pytest.raises(ValueError):
        parse_cache_key("__world__")
