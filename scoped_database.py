import asyncio
import time
from copy import deepcopy
from collections.abc import MutableMapping
from typing import Any

from casino_contracts import reconcile_expired_casino_escrow
from guild_config import WORLD_SETTINGS_KEY
from persistence_scope import (
    RecordKey,
    global_account_key,
    guild_profile_key,
    guild_world_key,
)
from persistence_store import FlushResult, ScopedRecordStore
from world_mode_contracts import (
    PLAYER_MODE_SELECTION_KEY,
    WORLD_MODE_CONFIG_KEY,
    new_world_mode_config,
)
from profile_signature_contracts import (
    GUILD_PRIVACY_KEY,
    GLOBAL_PRIVACY_KEY,
    IDENTITY_KEY,
    SIGNATURE_CONFIG_KEY,
    SIGNATURE_STATE_KEY,
    default_global_privacy,
    default_guild_privacy,
    default_profile_identity,
    default_signature_config,
    default_signature_state,
)


FLUSH_INTERVAL_SECONDS = 10
CASINO_PROFIT_METRICS = {
    "casino_total_profit",
    "coinflip_profit",
    "slots_profit",
    "blackjack_profit",
    "dice_profit",
    "roulette_profit",
    "hilo_profit",
    "rps_profit",
    "crash_profit",
    "wheel_profit",
    "cups_profit",
    "keno_profit",
}


def make_default_account() -> dict[str, Any]:
    return {
        "created_at": 0,
        "cosmetics": {},
        "collection": {},
        "global_achievements": [],
        IDENTITY_KEY: default_profile_identity(),
        GLOBAL_PRIVACY_KEY: default_global_privacy(),
    }


def make_default_profile() -> dict[str, Any]:
    return {
        "grams": 500,
        "dirty_cash": 0,
        "heat": 0,
        "jail_until": 0,
        "items": {},
        "inventory": [],
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
        "crew_id": None,
        "stats": {},
        "created_at": 0,
        "daily_streak": 0,
        "settings": {"notifications": True},
        GUILD_PRIVACY_KEY: default_guild_privacy(),
        "daily_quests": [],
        "last_daily": 0,
        "last_login": 0,
    }


def reset_gameplay_profile(profile: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Reset gameplay while preserving user control/privacy preferences."""
    preserved: dict[str, Any] = {}
    settings = profile.get("settings")
    if isinstance(settings, dict):
        preserved["settings"] = deepcopy(settings)
    guild_privacy = profile.get(GUILD_PRIVACY_KEY)
    if isinstance(guild_privacy, dict):
        preserved[GUILD_PRIVACY_KEY] = deepcopy(guild_privacy)
    mode_selection = profile.get(PLAYER_MODE_SELECTION_KEY)
    if isinstance(mode_selection, dict):
        preserved[PLAYER_MODE_SELECTION_KEY] = deepcopy(mode_selection)

    profile.clear()
    profile.update(make_default_profile())
    profile.update(preserved)
    return profile


def make_default_world() -> dict[str, Any]:
    return {
        "weather": "Sunny ☀️",
        "market_multiplier": 1.0,
        "event": None,
        "crews": {},
        "district": {
            "owner_crew_id": None,
            "owner_name": None,
            "multiplier": 1.0,
            "expires_at": 0,
        },
        "auctions": {},
        "auction_counter": 0,
        WORLD_SETTINGS_KEY: {},
        WORLD_MODE_CONFIG_KEY: new_world_mode_config(),
        SIGNATURE_CONFIG_KEY: default_signature_config(),
        SIGNATURE_STATE_KEY: default_signature_state(),
    }


def default_record(key: RecordKey) -> MutableMapping[str, Any]:
    if key.kind == "account":
        return make_default_account()
    if key.kind == "profile":
        return make_default_profile()
    if key.kind == "world":
        return make_default_world()
    raise ValueError(f"unsupported record kind: {key.kind}")


def profile_has_pending_notification_work(
    profile: MutableMapping[str, Any],
) -> bool:
    settings = profile.get("settings")
    if not isinstance(settings, dict):
        settings = {}

    notifications_enabled = settings.get("notifications", True)
    if not isinstance(notifications_enabled, bool):
        notifications_enabled = True
    if not notifications_enabled:
        return False

    categories = settings.get("notification_categories")
    if not isinstance(categories, dict):
        categories = {}

    plant_enabled = categories.get("plant_ready", notifications_enabled)
    if not isinstance(plant_enabled, bool):
        plant_enabled = notifications_enabled
    lab_enabled = categories.get("lab_ready", notifications_enabled)
    if not isinstance(lab_enabled, bool):
        lab_enabled = notifications_enabled

    if plant_enabled:
        plants = profile.get("plants")
        if isinstance(plants, list) and any(
            isinstance(plant, dict) and plant.get("notified") is not True
            for plant in plants
        ):
            return True

    if lab_enabled:
        queue = profile.get("processing_queue")
        if isinstance(queue, list) and any(
            isinstance(batch, dict) and batch.get("notified") is not True
            for batch in queue
        ):
            return True

    return False


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
        self._notification_candidates: set[tuple[int, int]] = set()
        self._notification_primed_scopes: set[int] = set()
        self._notification_prime_lock = asyncio.Lock()

    async def get_account(self, user_id: Any) -> MutableMapping[str, Any]:
        return await self.store.get(global_account_key(user_id))

    async def get_profile(self, guild_id: Any, user_id: Any) -> MutableMapping[str, Any]:
        key = guild_profile_key(guild_id, user_id)
        profile = await self.store.get(key)
        if not self.lock.locked() and reconcile_expired_casino_escrow(
            profile,
            now=time.time(),
        ):
            self.store.mark_dirty(key)
        self._sync_notification_candidate(key, profile)
        return profile

    async def get_world(self, guild_id: Any) -> MutableMapping[str, Any]:
        return await self.store.get(guild_world_key(guild_id))

    async def list_guild_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._run_backend_query(
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
        return await self._run_backend_query(
            "list_guild_heist_leaderboard",
            guild_id,
            limit=limit,
        )

    async def list_guild_casino_leaderboard(
        self,
        guild_id: Any,
        *,
        metric: str = "casino_total_profit",
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        if metric not in CASINO_PROFIT_METRICS:
            raise ValueError("unsupported casino leaderboard metric")
        query = getattr(self.backend, "list_guild_casino_leaderboard", None)
        if query is None:
            raise RuntimeError("database backend does not support list_guild_casino_leaderboard")
        return await query(guild_id, metric=metric, limit=limit)

    async def list_notification_candidates(
        self,
        guild_ids: list[Any] | tuple[Any, ...] | set[Any],
    ) -> list[tuple[int, int]]:
        active_scopes = {
            int(guild_world_key(guild_id).guild_id)
            for guild_id in guild_ids
        }
        if not active_scopes:
            return []

        async with self._notification_prime_lock:
            unprimed = active_scopes - self._notification_primed_scopes
            if unprimed:
                query = getattr(self.backend, "list_notification_candidates", None)
                if query is None:
                    raise RuntimeError(
                        "database backend does not support list_notification_candidates"
                    )
                rows = await query(sorted(unprimed))
                for scope_id, user_id in rows:
                    pair = (int(scope_id), int(user_id))
                    if pair[0] not in unprimed:
                        continue
                    key = guild_profile_key(pair[0], pair[1])
                    cached = self.store.peek_cached(key)
                    if cached is None:
                        self._notification_candidates.add(pair)
                    else:
                        self._sync_notification_candidate(key, cached)
                self._notification_primed_scopes.update(unprimed)

        return sorted(
            pair
            for pair in self._notification_candidates
            if pair[0] in active_scopes
        )

    async def _run_backend_query(
        self,
        method_name: str,
        guild_id: Any,
        *,
        limit: int,
    ):
        query = getattr(self.backend, method_name, None)
        if query is None:
            raise RuntimeError(f"database backend does not support {method_name}")
        return await query(guild_id, limit=limit)

    def mark_account_dirty(self, user_id: Any) -> None:
        self.store.mark_dirty(global_account_key(user_id))

    def _sync_notification_candidate(
        self,
        key: RecordKey,
        profile: MutableMapping[str, Any],
    ) -> None:
        if key.guild_id is None or key.user_id is None:
            raise ValueError("notification candidate requires a profile key")
        pair = (int(key.guild_id), int(key.user_id))
        if profile_has_pending_notification_work(profile):
            self._notification_candidates.add(pair)
        else:
            self._notification_candidates.discard(pair)

    def mark_profile_dirty(self, guild_id: Any, user_id: Any) -> None:
        key = guild_profile_key(guild_id, user_id)
        self.store.mark_dirty(key)
        profile = self.store.peek_cached(key)
        if profile is None:
            raise RuntimeError("dirty profile missing from cache")
        self._sync_notification_candidate(key, profile)

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
