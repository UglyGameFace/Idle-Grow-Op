import asyncio
from types import SimpleNamespace

import pytest

from persistence_context import (
    GuildContextRequired,
    get_context_profile,
    get_context_world,
    mark_context_profile_dirty,
    mark_context_world_dirty,
    require_guild_id,
)


class FakeDatabase:
    def __init__(self):
        self.calls = []

    async def get_profile(self, guild_id, user_id):
        self.calls.append(("get_profile", guild_id, user_id))
        return {"guild_id": guild_id, "user_id": user_id}

    async def get_world(self, guild_id):
        self.calls.append(("get_world", guild_id))
        return {"guild_id": guild_id}

    def mark_profile_dirty(self, guild_id, user_id):
        self.calls.append(("mark_profile_dirty", guild_id, user_id))

    def mark_world_dirty(self, guild_id):
        self.calls.append(("mark_world_dirty", guild_id))


def run(coro):
    return asyncio.run(coro)


def test_require_guild_id_rejects_dm_context():
    context = SimpleNamespace(guild=None)
    with pytest.raises(GuildContextRequired, match="only be used inside a server"):
        require_guild_id(context)


def test_context_helpers_use_exact_guild_and_author_scope():
    database = FakeDatabase()
    context = SimpleNamespace(
        guild=SimpleNamespace(id=123),
        author=SimpleNamespace(id=456),
    )

    profile = run(get_context_profile(database, context))
    world = run(get_context_world(database, context))
    mark_context_profile_dirty(database, context)
    mark_context_world_dirty(database, context)

    assert profile == {"guild_id": 123, "user_id": 456}
    assert world == {"guild_id": 123}
    assert database.calls == [
        ("get_profile", 123, 456),
        ("get_world", 123),
        ("mark_profile_dirty", 123, 456),
        ("mark_world_dirty", 123),
    ]


def test_explicit_target_user_stays_in_current_guild():
    database = FakeDatabase()
    context = SimpleNamespace(
        guild=SimpleNamespace(id=123),
        author=SimpleNamespace(id=456),
    )

    profile = run(get_context_profile(database, context, 999))
    mark_context_profile_dirty(database, context, 999)

    assert profile == {"guild_id": 123, "user_id": 999}
    assert database.calls == [
        ("get_profile", 123, 999),
        ("mark_profile_dirty", 123, 999),
    ]


def test_context_without_author_requires_explicit_user_id():
    database = FakeDatabase()
    context = SimpleNamespace(guild=SimpleNamespace(id=123), author=None)

    with pytest.raises(ValueError, match="user_id is required"):
        run(get_context_profile(database, context))
    with pytest.raises(ValueError, match="user_id is required"):
        mark_context_profile_dirty(database, context)
