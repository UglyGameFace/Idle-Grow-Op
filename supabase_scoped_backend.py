import asyncio
from collections.abc import Mapping
from typing import Any

from persistence_scope import (
    GLOBAL_ACCOUNT_PREFIX,
    GUILD_PROFILE_PREFIX,
    GUILD_WORLD_PREFIX,
    RecordKey,
)


REQUIRED_SCHEMA_VERSION = "004_batched_notification_candidates"
ATOMIC_SAVE_RPC = "idle_grow_save_scoped_records"
NOTIFICATION_BATCH_RPC = "idle_grow_list_notification_candidates"
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


class SupabaseSchemaError(RuntimeError):
    """Raised when the required scoped persistence schema is unavailable."""


class SupabaseScopedBackend:
    """Persist scoped records in the normalized Supabase tables."""

    def __init__(self, client):
        if client is None:
            raise ValueError("Supabase client is required")
        self.client = client

    async def verify_schema(self) -> None:
        await asyncio.to_thread(self._verify_schema_sync)

    def _verify_schema_sync(self) -> None:
        try:
            response = (
                self.client.table("app_schema_migrations")
                .select("version")
                .eq("version", REQUIRED_SCHEMA_VERSION)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise SupabaseSchemaError(
                "Enterprise scoped Supabase schema is unavailable. Run migrations/001_guild_scoped_persistence.sql, migrations/002_enterprise_casino_metrics.sql, and migrations/003_atomic_scoped_record_batch.sql."
            ) from exc

        if not (response.data or []):
            raise SupabaseSchemaError(
                f"Required Supabase migration is missing: {REQUIRED_SCHEMA_VERSION}"
            )

        casino_columns = ",".join(sorted(CASINO_PROFIT_METRICS))
        required_columns = {
            "global_accounts": "data",
            "guild_profiles": f"data,balance,heist_wins,has_notification_work,{casino_columns}",
            "guild_worlds": "data",
        }
        for table_name, columns in required_columns.items():
            try:
                self.client.table(table_name).select(columns).limit(1).execute()
            except Exception as exc:
                raise SupabaseSchemaError(
                    f"Required Supabase table or column is unavailable: {table_name}"
                ) from exc

        required_rpcs = (
            (ATOMIC_SAVE_RPC, self._empty_save_payload()),
            (NOTIFICATION_BATCH_RPC, {"p_guild_ids": []}),
        )
        for rpc_name, payload in required_rpcs:
            try:
                self.client.rpc(rpc_name, payload).execute()
            except Exception as exc:
                raise SupabaseSchemaError(
                    f"Required Supabase RPC is unavailable: {rpc_name}"
                ) from exc

    async def load(self, key: RecordKey) -> Mapping[str, Any] | None:
        return await asyncio.to_thread(self._load_sync, key)

    def _load_sync(self, key: RecordKey) -> Mapping[str, Any] | None:
        table_name, filters = self._table_and_filters(key)
        query = self.client.table(table_name).select("data")
        for column, value in filters.items():
            query = query.eq(column, value)
        response = query.limit(1).execute()
        if not response.data:
            return None
        return dict(response.data[0].get("data") or {})

    async def list_guild_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._list_guild_metric(guild_id, metric="balance", limit=limit)

    async def list_guild_heist_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._list_guild_metric(guild_id, metric="heist_wins", limit=limit)

    async def list_guild_casino_leaderboard(
        self,
        guild_id: Any,
        *,
        metric: str = "casino_total_profit",
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        if metric not in CASINO_PROFIT_METRICS:
            raise ValueError("unsupported casino leaderboard metric")
        return await self._list_guild_metric(
            guild_id,
            metric=metric,
            limit=limit,
            clamp_nonnegative=False,
        )

    async def _list_guild_metric(
        self,
        guild_id: Any,
        *,
        metric: str,
        limit: int,
        clamp_nonnegative: bool = True,
    ) -> list[tuple[int, int]]:
        guild_number = self._positive_int(guild_id, "guild_id")
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        allowed = {"balance", "heist_wins", *CASINO_PROFIT_METRICS}
        if metric not in allowed:
            raise ValueError("unsupported leaderboard metric")
        return await asyncio.to_thread(
            self._list_guild_metric_sync,
            guild_number,
            metric,
            int(limit),
            clamp_nonnegative,
        )

    def _list_guild_metric_sync(
        self,
        guild_id: int,
        metric: str,
        limit: int,
        clamp_nonnegative: bool,
    ) -> list[tuple[int, int]]:
        response = (
            self.client.table("guild_profiles")
            .select(f"user_id,{metric}")
            .eq("guild_id", guild_id)
            .order(metric, desc=True)
            .order("user_id")
            .limit(limit)
            .execute()
        )
        rows = []
        for row in response.data or []:
            value = int(row.get(metric, 0) or 0)
            rows.append((int(row["user_id"]), max(0, value) if clamp_nonnegative else value))
        return rows

    async def list_notification_candidates(
        self,
        guild_ids: list[Any] | tuple[Any, ...] | set[Any],
    ) -> list[tuple[int, int]]:
        normalized = sorted(
            {
                self._positive_int(guild_id, "guild_id")
                for guild_id in guild_ids
            }
        )
        if not normalized:
            return []
        return await asyncio.to_thread(
            self._list_notification_candidates_sync,
            normalized,
        )

    def _list_notification_candidates_sync(
        self,
        guild_ids: list[int],
    ) -> list[tuple[int, int]]:
        response = self.client.rpc(
            NOTIFICATION_BATCH_RPC,
            {"p_guild_ids": guild_ids},
        ).execute()
        return [
            (int(row["guild_id"]), int(row["user_id"]))
            for row in (response.data or [])
        ]

    async def save_many(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        if not records:
            return
        await asyncio.to_thread(self._save_many_sync, records)

    def _save_many_sync(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        payload = self._empty_save_payload()
        payload_keys = {
            "global_accounts": "p_global_accounts",
            "guild_profiles": "p_guild_profiles",
            "guild_worlds": "p_guild_worlds",
        }
        for key, data in records.items():
            table_name, filters = self._table_and_filters(key)
            payload[payload_keys[table_name]].append({**filters, "data": dict(data)})

        self.client.rpc(ATOMIC_SAVE_RPC, payload).execute()

    @staticmethod
    def _empty_save_payload() -> dict[str, list[dict[str, Any]]]:
        return {
            "p_global_accounts": [],
            "p_guild_profiles": [],
            "p_guild_worlds": [],
        }

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        number = int(value)
        if number <= 0:
            raise ValueError(f"{name} must be positive")
        return number

    @staticmethod
    def _table_and_filters(key: RecordKey) -> tuple[str, dict[str, int]]:
        if key.kind == GLOBAL_ACCOUNT_PREFIX and key.user_id:
            return "global_accounts", {"user_id": int(key.user_id)}
        if key.kind == GUILD_PROFILE_PREFIX and key.guild_id and key.user_id:
            return "guild_profiles", {
                "guild_id": int(key.guild_id),
                "user_id": int(key.user_id),
            }
        if key.kind == GUILD_WORLD_PREFIX and key.guild_id:
            return "guild_worlds", {"guild_id": int(key.guild_id)}
        raise ValueError("unsupported or incomplete record key")
