import asyncio
from collections.abc import MutableMapping
from typing import Any

from persistence_scope import (
    RecordKey,
    global_account_key,
    guild_profile_key,
    guild_world_key,
)
from persistence_store import FlushResult, ScopedRecordStore


FLUSH_INTERVAL_SECONDS = 10


def make_default_account() -> dict[str, Any]:
    return {
        "created_at": 0,
        "cosmetics": {},
        "collection": {},
        "global_achievements": [],
    }


def make_default_profile() -> dict[str, Any]:
    return {
        "grams": 500,
        "dirty_cash": 0,
        "heat": 0,
        "jail_until": 0,
        "items": {},
        "inventory": [],
        "item_wear": {},
        "flower_stash": {},
        "concentrates": {},
        "plants": [],
        "max_pots": 3,
        "processing_queue": [],
        "unlocked_strains": ["schwag", "mexican brick"],
        "xp": 0,
        "level": 1,
        "prestige": 0,
        "achievements": [],
        "skills": {},
        "crew_id": None,
        "stats": {},
        "created_at": 0,
        "daily_streak": 0,
        "settings": {"notifications": True},
        "daily_quests": [],
        "last_daily": 0,
        "last_login": 0,
    }


def make_default_world() -> dict[str, Any]:
    return {
        "weather": "Sunny ☀️",
        "market_multiplier": 1.0,
        "event": None,
        "crews": {},
        "district": {
            "owner_crew_id": None,
            "owner_name": None,
            "multiplier": 1.10,
            "expires_at": 0,
        },
        "auctions": {},
        "auction_counter": 0,
        "settings": {},
    }


def default_record(key: RecordKey) -> MutableMapping[str, Any]:
    if key.kind == "account":
        return make_default_account()
    if key.kind == "profile":
        return make_default_profile()
    if key.kind == "world":
        return make_default_world()
    raise ValueError(f"unsupported record kind: {key.kind}")


class ScopedDatabaseManager:
    """Explicit guild-scoped database access with dirty-record persistence."""

    def __init__(self, backend, *, flush_interval: float = FLUSH_INTERVAL_SECONDS):
        if flush_interval <= 0:
            raise ValueError("flush_interval must be positive")
        self.backend = backend
        self.lock = asyncio.Lock()
        self.store = ScopedRecordStore(backend, default_record)
        self.flush_interval = float(flush_interval)
        self._flush_task: asyncio.Task | None = None
        self._closed = False

    async def get_account(self, user_id: Any) -> MutableMapping[str, Any]:
        return await self.store.get(global_account_key(user_id))

    async def get_profile(self, guild_id: Any, user_id: Any) -> MutableMapping[str, Any]:
        return await self.store.get(guild_profile_key(guild_id, user_id))

    async def get_world(self, guild_id: Any) -> MutableMapping[str, Any]:
        return await self.store.get(guild_world_key(guild_id))

    async def list_guild_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._run_backend_leaderboard(
            "list_guild_leaderboard",
            guild_id,
            limit=limit,
        )

    async def list_guild_heist_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._run_backend_leaderboard(
            "list_guild_heist_leaderboard",
            guild_id,
            limit=limit,
        )

    async def _run_backend_leaderboard(
        self,
        method_name: str,
        guild_id: Any,
        *,
        limit: int,
    ) -> list[tuple[int, int]]:
        query = getattr(self.backend, method_name, None)
        if query is None:
            raise RuntimeError(f"database backend does not support {method_name}")
        return await query(guild_id, limit=limit)

    def mark_account_dirty(self, user_id: Any) -> None:
        self.store.mark_dirty(global_account_key(user_id))

    def mark_profile_dirty(self, guild_id: Any, user_id: Any) -> None:
        self.store.mark_dirty(guild_profile_key(guild_id, user_id))

    def mark_world_dirty(self, guild_id: Any) -> None:
        self.store.mark_dirty(guild_world_key(guild_id))

    async def flush(self) -> FlushResult:
        return await self.store.flush()

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("database manager is closed")
        if self._flush_task is not None:
            raise RuntimeError("database manager already started")
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="idle-grow-scoped-db-flush",
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._flush_task
        self._flush_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            try:
                await self.flush()
            except Exception as exc:
                print(f"❌ Scoped persistence flush failed: {exc}")
