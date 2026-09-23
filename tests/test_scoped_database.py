import asyncio
from copy import deepcopy

import pytest

from persistence_scope import RecordKey
from scoped_database import (
    ScopedDatabaseManager,
    profile_has_pending_notification_work,
)


class MemoryBackend:
    def __init__(self):
        self.records = {}
        self.saved_batches = []
        self.notification_rows = []
        self.notification_calls = []

    async def load(self, key: RecordKey):
        value = self.records.get(key.cache_key)
        return deepcopy(value) if value is not None else None

    async def save_many(self, records):
        batch = {key.cache_key: deepcopy(dict(value)) for key, value in records.items()}
        self.saved_batches.append(batch)
        self.records.update(batch)


    async def list_notification_candidates(self, guild_ids):
        normalized = tuple(sorted(int(value) for value in guild_ids))
        self.notification_calls.append(normalized)
        return list(self.notification_rows)


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


def test_profile_first_load_repairs_and_persists_legacy_xp_overflow():
    async def scenario():
        backend = MemoryBackend()
        backend.records["profile:100:200"] = {
            "level": 20,
            "xp": 9_802,
            "grams": 500,
        }
        database = ScopedDatabaseManager(backend)

        profile = await database.get_profile(100, 200)

        assert profile["level"] == 21
        assert profile["xp"] == 858
        assert "profile:100:200" in database.store.dirty_keys

        await database.flush()

        assert backend.records["profile:100:200"]["level"] == 21
        assert backend.records["profile:100:200"]["xp"] == 858

        backend.saved_batches.clear()
        again = await database.get_profile(100, 200)
        await database.flush()

        assert again is profile
        assert backend.saved_batches == []

    run(scenario())


def test_notification_candidates_prime_once_then_use_memory_only():
    async def scenario():
        backend = MemoryBackend()
        backend.notification_rows = [(100, 200)]
        database = ScopedDatabaseManager(backend)

        first = await database.list_notification_candidates([100])
        second = await database.list_notification_candidates([100])

        assert first == [(100, 200)]
        assert second == [(100, 200)]
        assert backend.notification_calls == [(100,)]

    run(scenario())


def test_profile_mutations_update_notification_candidates_without_backend_reread():
    async def scenario():
        backend = MemoryBackend()
        database = ScopedDatabaseManager(backend)

        assert await database.list_notification_candidates([100]) == []
        profile = await database.get_profile(100, 200)

        profile["plants"] = [{"strain": "schwag", "notified": False}]
        database.mark_profile_dirty(100, 200)
        assert await database.list_notification_candidates([100]) == [(100, 200)]

        profile["plants"][0]["notified"] = True
        database.mark_profile_dirty(100, 200)
        assert await database.list_notification_candidates([100]) == []

        assert backend.notification_calls == [(100,)]

    run(scenario())


def test_cached_profile_state_wins_over_stale_prime_rows():
    async def scenario():
        backend = MemoryBackend()
        backend.notification_rows = [(100, 200)]
        database = ScopedDatabaseManager(backend)
        profile = await database.get_profile(100, 200)
        assert profile["plants"] == []

        assert await database.list_notification_candidates([100]) == []
        assert backend.notification_calls == [(100,)]

    run(scenario())


def test_pending_notification_predicate_respects_private_preferences():
    profile = {
        "settings": {
            "notifications": True,
            "notification_categories": {
                "plant_ready": False,
                "lab_ready": True,
            },
        },
        "plants": [{"notified": False}],
        "processing_queue": [],
    }
    assert profile_has_pending_notification_work(profile) is False

    profile["processing_queue"] = [{"notified": False}]
    assert profile_has_pending_notification_work(profile) is True

    profile["settings"]["notifications"] = False
    assert profile_has_pending_notification_work(profile) is False
