import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from persistence_scope import RecordKey, parse_cache_key


class RecordBackend(Protocol):
    async def load(self, key: RecordKey) -> Mapping[str, Any] | None:
        """Load one scoped record, returning None when it does not exist."""

    async def save_many(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        """Persist exactly the supplied records atomically from the store's perspective."""


DefaultFactory = Callable[[RecordKey], MutableMapping[str, Any]]


@dataclass(frozen=True, slots=True)
class FlushResult:
    saved_keys: tuple[str, ...]

    @property
    def saved_count(self) -> int:
        return len(self.saved_keys)


class ScopedRecordStore:
    """Lazy in-memory cache for explicitly scoped persistence records.

    Records are loaded one at a time. Only keys explicitly marked dirty are
    written. Failed writes stay dirty so the next flush can retry them.
    """

    def __init__(self, backend: RecordBackend, default_factory: DefaultFactory):
        self._backend = backend
        self._default_factory = default_factory
        self._cache: dict[str, MutableMapping[str, Any]] = {}
        self._dirty: set[str] = set()
        self._load_locks: dict[str, asyncio.Lock] = {}
        self._flush_lock = asyncio.Lock()

    @property
    def cached_keys(self) -> frozenset[str]:
        return frozenset(self._cache)

    @property
    def dirty_keys(self) -> frozenset[str]:
        return frozenset(self._dirty)

    def is_cached(self, key: RecordKey) -> bool:
        return key.cache_key in self._cache

    async def get(self, key: RecordKey) -> MutableMapping[str, Any]:
        cache_key = key.cache_key
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        load_lock = self._load_locks.setdefault(cache_key, asyncio.Lock())
        async with load_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            loaded = await self._backend.load(key)
            if loaded is None:
                record = deepcopy(self._default_factory(key))
                self._dirty.add(cache_key)
            else:
                record = deepcopy(dict(loaded))

            self._cache[cache_key] = record
            return record

    def mark_dirty(self, key: RecordKey) -> None:
        cache_key = key.cache_key
        if cache_key not in self._cache:
            raise KeyError(f"cannot mark uncached record dirty: {cache_key}")
        self._dirty.add(cache_key)

    def evict(self, key: RecordKey) -> None:
        cache_key = key.cache_key
        if cache_key in self._dirty:
            raise RuntimeError(f"cannot evict dirty record: {cache_key}")
        self._cache.pop(cache_key, None)
        self._load_locks.pop(cache_key, None)

    async def flush(self) -> FlushResult:
        async with self._flush_lock:
            snapshot_keys = tuple(sorted(self._dirty))
            if not snapshot_keys:
                return FlushResult(saved_keys=())

            records: dict[RecordKey, Mapping[str, Any]] = {}
            for cache_key in snapshot_keys:
                record = self._cache.get(cache_key)
                if record is None:
                    raise RuntimeError(f"dirty record missing from cache: {cache_key}")
                records[parse_cache_key(cache_key)] = deepcopy(dict(record))

            await self._backend.save_many(records)

            for cache_key in snapshot_keys:
                self._dirty.discard(cache_key)
            return FlushResult(saved_keys=snapshot_keys)
