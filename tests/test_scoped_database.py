import asyncio
from copy import deepcopy

import pytest

from persistence_scope import RecordKey
from scoped_database import ScopedDatabaseManager


class MemoryBackend:
    def __init__(self):
        self.records = {}
        self.saved_batches = []

    async def load(self, key: RecordKey):
        value = self.records.get(key.cache_key)
        return deepcopy(value) if value is not None else None

    async def save_many(self, records):
        batch = {key.cache_key: deepcopy(dict(value)) for key, value in records.items()}
        self.saved_batches.append(batch)
        self.records.update(batch)


def run(coro):
    return asyncio.run(coro)


def test_profiles_and_worlds_are_isolated_by_guild():
    async def scenario():
        backend = MemoryBackend()
        database = ScopedDatabaseManager(backend)

        first = await database.get_profile(100, 200)
        second = await database.get_profile(101, 200)
        first["grams"] = 900
        database.mark_profile_dirty(100, 200)
        await database.flush()

        assert first is not second
        assert second["grams"] == 500
        assert backend.records["profile:100:200"]["grams"] == 900
        assert "profile:101:200" in backend.records

    run(scenario())


def test_flush_writes_only_marked_records_after_defaults_are_created():
    async def scenario():
        backend = MemoryBackend()
        database = ScopedDatabaseManager(backend)
        profile = await database.get_profile(100, 200)
        world = await database.get_world(100)

        await database.flush()
        backend.saved_batches.clear()

        profile["grams"] += 100
        database.mark_profile_dirty(100, 200)
        world["weather"] = "Rainy 🌧️"

        result = await database.flush()

        assert result.saved_keys == ("profile:100:200",)
        assert backend.saved_batches == [
            {"profile:100:200": deepcopy(profile)}
        ]

    run(scenario())


def test_manager_rejects_double_start_without_hidden_guard():
    async def scenario():
        database = ScopedDatabaseManager(MemoryBackend(), flush_interval=60)
        await database.start()
        with pytest.raises(RuntimeError, match="already started"):
            await database.start()
        await database.close()

    run(scenario())


def test_close_flushes_dirty_records():
    async def scenario():
        backend = MemoryBackend()
        database = ScopedDatabaseManager(backend, flush_interval=60)
        await database.start()
        profile = await database.get_profile(100, 200)
        profile["grams"] = 777
        database.mark_profile_dirty(100, 200)

        await database.close()

        assert backend.records["profile:100:200"]["grams"] == 777

    run(scenario())
