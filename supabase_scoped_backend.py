import asyncio
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from persistence_scope import (
    GLOBAL_ACCOUNT_PREFIX,
    GUILD_PROFILE_PREFIX,
    GUILD_WORLD_PREFIX,
    RecordKey,
)


REQUIRED_SCHEMA_VERSION = "001_guild_scoped_persistence"


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
                "Scoped Supabase schema is unavailable. Run "
                "migrations/001_guild_scoped_persistence.sql with the Supabase SQL editor."
            ) from exc

        versions = response.data or []
        if not versions:
            raise SupabaseSchemaError(
                f"Required Supabase migration is missing: {REQUIRED_SCHEMA_VERSION}"
            )

        required_columns = {
            "global_accounts": "data",
            "guild_profiles": "data,balance,heist_wins,has_notification_work",
            "guild_worlds": "data",
        }
        for table_name, columns in required_columns.items():
            try:
                self.client.table(table_name).select(columns).limit(1).execute()
            except Exception as exc:
                raise SupabaseSchemaError(
                    f"Required Supabase table or column is unavailable: {table_name}"
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
        return await self._list_guild_metric(
            guild_id,
            metric="balance",
            limit=limit,
        )

    async def list_guild_heist_leaderboard(
        self,
        guild_id: Any,
        *,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._list_guild_metric(
            guild_id,
            metric="heist_wins",
            limit=limit,
        )

    async def _list_guild_metric(
        self,
        guild_id: Any,
        *,
        metric: str,
        limit: int,
    ) -> list[tuple[int, int]]:
        guild_number = self._positive_int(guild_id, "guild_id")
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if metric not in {"balance", "heist_wins"}:
            raise ValueError("unsupported leaderboard metric")
        return await asyncio.to_thread(
            self._list_guild_metric_sync,
            guild_number,
            metric,
            int(limit),
        )

    def _list_guild_metric_sync(
        self,
        guild_id: int,
        metric: str,
        limit: int,
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
        return [
            (int(row["user_id"]), max(0, int(row.get(metric, 0) or 0)))
            for row in (response.data or [])
        ]

    async def list_guild_notification_candidates(
        self,
        guild_id: Any,
        *,
        limit: int = 500,
    ) -> list[int]:
        guild_number = self._positive_int(guild_id, "guild_id")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        return await asyncio.to_thread(
            self._list_guild_notification_candidates_sync,
            guild_number,
            int(limit),
        )

    def _list_guild_notification_candidates_sync(
        self,
        guild_id: int,
        limit: int,
    ) -> list[int]:
        response = (
            self.client.table("guild_profiles")
            .select("user_id")
            .eq("guild_id", guild_id)
            .eq("has_notification_work", True)
            .order("user_id")
            .limit(limit)
            .execute()
        )
        return [int(row["user_id"]) for row in (response.data or [])]

    async def save_many(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        if not records:
            return
        await asyncio.to_thread(self._save_many_sync, records)

    def _save_many_sync(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for key, data in records.items():
            table_name, filters = self._table_and_filters(key)
            grouped[table_name].append({**filters, "data": dict(data)})

        for table_name, payload in grouped.items():
            self.client.table(table_name).upsert(payload).execute()

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
