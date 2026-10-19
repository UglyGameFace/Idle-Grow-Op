"""Neon PostgreSQL implementation of Idle Grow's scoped persistence contract."""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from persistence_scope import RecordKey
from supabase_scoped_backend import (
    ATOMIC_SAVE_RPC,
    CASINO_PROFIT_METRICS,
    NOTIFICATION_BATCH_RPC,
    REQUIRED_SCHEMA_VERSION,
    SupabaseScopedBackend,
)


class NeonSchemaError(RuntimeError):
    """The expected Idle Grow PostgreSQL schema is unavailable."""


class NeonScopedBackend:
    """Bounded async connection pool; never silently falls back to Supabase."""

    def __init__(self, dsn: str, *, pool_factory=None):
        address = urlsplit(str(dsn or ""))
        if (
            address.scheme not in {"postgres", "postgresql"}
            or not address.hostname
            or not address.hostname.endswith(".neon.tech")
        ):
            raise ValueError("IDLE_NEON_DATABASE_URL must be a Neon PostgreSQL URL")
        self._dsn = dsn
        self._pool_factory = pool_factory
        self._pool = None

    async def start(self) -> None:
        if self._pool is not None:
            raise RuntimeError("Neon pool is already started")
        factory = self._pool_factory
        if factory is None:
            import asyncpg

            factory = asyncpg.create_pool
        self._pool = await factory(
            dsn=self._dsn,
            min_size=0,
            max_size=3,
            timeout=15,
            command_timeout=20,
            max_inactive_connection_lifetime=45,
            server_settings={"application_name": "idle-grow-op"},
        )

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()

    def _ready_pool(self):
        if self._pool is None:
            raise RuntimeError("Neon database is not started")
        return self._pool

    async def verify_schema(self) -> None:
        required_columns = {
            "global_accounts": {"user_id", "data"},
            "guild_profiles": {
                "guild_id", "user_id", "data", "balance", "heist_wins",
                "has_notification_work", "has_pending_notification_work",
                *CASINO_PROFIT_METRICS,
            },
            "guild_worlds": {"guild_id", "data"},
        }
        async with self._ready_pool().acquire() as conn:
            version = await conn.fetchval(
                "SELECT 1 FROM public.app_schema_migrations WHERE version = $1",
                REQUIRED_SCHEMA_VERSION,
            )
            if version != 1:
                raise NeonSchemaError(
                    f"Missing Neon schema migration {REQUIRED_SCHEMA_VERSION}"
                )
            for table, expected in required_columns.items():
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=$1", table,
                )
                actual = {row["column_name"] for row in rows}
                if expected - actual:
                    raise NeonSchemaError(
                        f"Missing Neon columns in {table}: "
                        + ", ".join(sorted(expected - actual))
                    )
            for signature in (
                f"public.{ATOMIC_SAVE_RPC}(jsonb,jsonb,jsonb)",
                f"public.{NOTIFICATION_BATCH_RPC}(bigint[])",
            ):
                if not await conn.fetchval(
                    "SELECT to_regprocedure($1::text)::text", signature,
                ):
                    raise NeonSchemaError(f"Missing Neon function {signature}")

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        number = int(value)
        if number <= 0:
            raise ValueError(f"{field} must be positive")
        return number

    async def load(self, key: RecordKey) -> Mapping[str, Any] | None:
        table, filters = SupabaseScopedBackend._table_and_filters(key)
        where = " AND ".join(
            f"{column} = ${index}"
            for index, column in enumerate(filters, 1)
        )
        async with self._ready_pool().acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT data FROM public.{table} WHERE {where} LIMIT 1",
                *filters.values(),
            )
        if row is None:
            return None
        data = row["data"]
        return dict(json.loads(data) if isinstance(data, str) else data or {})

    async def save_many(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        if not records:
            return
        payload = {
            "global_accounts": [], "guild_profiles": [], "guild_worlds": [],
        }
        for key, record in records.items():
            table, filters = SupabaseScopedBackend._table_and_filters(key)
            payload[table].append({**filters, "data": dict(record)})
        params = [
            json.dumps(payload[table], ensure_ascii=False, separators=(",", ":"))
            for table in ("global_accounts", "guild_profiles", "guild_worlds")
        ]
        # Existing PostgreSQL function commits all three groups atomically.
        async with self._ready_pool().acquire() as conn:
            await conn.fetchval(
                f"SELECT public.{ATOMIC_SAVE_RPC}($1::jsonb,$2::jsonb,$3::jsonb)",
                *params,
            )

    async def _list_metric(
        self, guild_id: Any, metric: str, limit: int, *, clamp: bool = True,
    ) -> list[tuple[int, int]]:
        guild_id = self._positive_int(guild_id, "guild_id")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if metric not in {"balance", "heist_wins", *CASINO_PROFIT_METRICS}:
            raise ValueError("unsupported metric")
        # SQL identifier is selected from a fixed allowlist, never user input.
        sql = (
            f"SELECT user_id,{metric} FROM public.guild_profiles "
            f"WHERE guild_id=$1 ORDER BY {metric} DESC,user_id LIMIT $2"
        )
        async with self._ready_pool().acquire() as conn:
            rows = await conn.fetch(sql, guild_id, limit)
        return [
            (int(row["user_id"]), max(0, int(row[metric] or 0))
             if clamp else int(row[metric] or 0))
            for row in rows
        ]

    async def list_guild_leaderboard(
        self, guild_id: Any, *, limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._list_metric(guild_id, "balance", limit)

    async def list_guild_heist_leaderboard(
        self, guild_id: Any, *, limit: int = 10,
    ) -> list[tuple[int, int]]:
        return await self._list_metric(guild_id, "heist_wins", limit)

    async def list_guild_casino_leaderboard(
        self, guild_id: Any, *, metric: str = "casino_total_profit",
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        if metric not in CASINO_PROFIT_METRICS:
            raise ValueError("unsupported casino leaderboard metric")
        return await self._list_metric(guild_id, metric, limit, clamp=False)

    async def list_notification_candidates(
        self, guild_ids: list[Any] | tuple[Any, ...] | set[Any],
    ) -> list[tuple[int, int]]:
        ids = sorted({self._positive_int(x, "guild_id") for x in guild_ids})
        if not ids:
            return []
        async with self._ready_pool().acquire() as conn:
            rows = await conn.fetch(
                f"SELECT guild_id,user_id FROM public.{NOTIFICATION_BATCH_RPC}($1::bigint[])",
                ids,
            )
        return [(int(row["guild_id"]), int(row["user_id"])) for row in rows]
