import asyncio
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest

from persistence_scope import RecordKey, guild_profile_key, guild_world_key
from persistence_store import ScopedRecordStore


class MemoryBackend:
    def __init__(self, records=None):
        self.records = {
            key.cache_key: deepcopy(value)
            for key, value in (records or {}).items()
        }
        self.loads = []
        self.saved_batches = []
        self.fail_saves = False

    async def load(self, key: RecordKey) -> Mapping[str, Any] | None:
        self.loads.append(key.cache_key)
        value = self.records.get(key.cache_key)
        return deepcopy(value) if value is not None else None

    async def save_many(self, records):
        if self.fail_saves:
            raise RuntimeError("backend unavailable")
        batch = {key.cache_key: deepcopy(dict(value)) for key, value in records.items()}
        self.saved_batches.append(batch)
        self.records.update(batch)


def defaults(key):
    if key.kind == "world":
        return {"weather": "Sunny", "market_multiplier": 1.0}
    return {"grams": 500, "plants": []}


@pytest.mark.asyncio
async def test_records_are_loaded_lazily_one_key_at_a_time():
    first = guild_profile_key(100, 200)
    second = guild_profile_key(100, 201)
    backend = MemoryBackend({first: {"grams": 900}})
    store = ScopedRecordStore(backend, defaults)

    assert not store.cached_keys
    assert await store.get(first) == {"grams": 900}
    assert backend.loads == [first.cache_key]
    assert second.cache_key not in store.cached_keys


@pytest.mark.asyncio
async def test_missing_record_gets_default_and_is_marked_dirty():
    key = guild_world_key(100)
    backend = MemoryBackend()
    store = ScopedRecordStore(backend, defaults)

    record = await store.get(key)

    assert record == {"weather": "Sunny", "market_multiplier": 1.0}
    assert store.dirty_keys == {key.cache_key}


@pytest.mark.asyncio
async def test_flush_writes_only_explicitly_dirty_records():
    changed = guild_profile_key(100, 200)
    untouched = guild_profile_key(100, 201)
    backend = MemoryBackend(
        {
            changed: {"grams": 500},
            untouched: {"grams": 700},
        }
    )
    store = ScopedRecordStore(backend, defaults)

    changed_record = await store.get(changed)
    await store.get(untouched)
    changed_record["grams"] = 600
    store.mark_dirty(changed)

    result = await store.flush()

    assert result.saved_keys == (changed.cache_key,)
    assert backend.saved_batches == [{changed.cache_key: {"grams": 600}}]
    assert not store.dirty_keys


@pytest.mark.asyncio
async def test_failed_flush_keeps_records_dirty_for_retry():
    key = guild_profile_key(100, 200)
    backend = MemoryBackend({key: {"grams": 500}})
    store = ScopedRecordStore(backend, defaults)
    record = await store.get(key)
    record["grams"] = 650
    store.mark_dirty(key)
    backend.fail_saves = True

    with pytest.raises(RuntimeError, match="backend unavailable"):
        await store.flush()

    assert store.dirty_keys == {key.cache_key}

    backend.fail_saves = False
    result = await store.flush()
    assert result.saved_keys == (key.cache_key,)
    assert backend.records[key.cache_key] == {"grams": 650}


@pytest.mark.asyncio
async def test_concurrent_first_reads_share_one_backend_load():
    key = guild_profile_key(100, 200)
    backend = MemoryBackend({key: {"grams": 500}})
    store = ScopedRecordStore(backend, defaults)

    first, second = await asyncio.gather(store.get(key), store.get(key))

    assert first is second
    assert backend.loads == [key.cache_key]


@pytest.mark.asyncio
async def test_dirty_record_cannot_be_evicted_before_flush():
    key = guild_profile_key(100, 200)
    backend = MemoryBackend()
    store = ScopedRecordStore(backend, defaults)
    await store.get(key)

    with pytest.raises(RuntimeError, match="cannot evict dirty"):
        store.evict(key)
