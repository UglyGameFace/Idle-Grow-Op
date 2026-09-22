from types import SimpleNamespace

import pytest

from persistence_context import GuildContextRequired, require_guild_id


def test_require_guild_id_returns_valid_server_scope():
    context = SimpleNamespace(guild=SimpleNamespace(id=123))
    assert require_guild_id(context) == 123


def test_require_guild_id_rejects_dm_context():
    context = SimpleNamespace(guild=None)
    with pytest.raises(GuildContextRequired, match="only be used inside a server"):
        require_guild_id(context)


@pytest.mark.parametrize("guild_id", [None, 0, -1, "not-a-snowflake"])
def test_require_guild_id_rejects_invalid_server_identifiers(guild_id):
    context = SimpleNamespace(guild=SimpleNamespace(id=guild_id))
    with pytest.raises(GuildContextRequired, match="Discord guild context is invalid"):
        require_guild_id(context)
