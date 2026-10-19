import asyncio
import json
from types import SimpleNamespace

import pytest

from neon_scoped_backend import NeonSchemaError, NeonScopedBackend
from persistence_scope import (
    global_account_key,
    guild_profile_key,
    guild_world_key,
)
from supabase_scoped_backend import CASINO_PROFIT_METRICS, REQUIRED_SCHEMA_VERSION


DSN = "postgresql://owner:password@ep-test.us-east-1.aws.neon.tech/idle_grow_op?sslmode=require"


class Connection:
    def __init__(self):
        self.operations = []
        self.missing_version = False
        self.missing_function = False
        self.missing_column = False
        self.fail_save = False
        self.records = {
            "guild_profiles": {
                "data": json.dumps({"grams": 123, "plants": [{"strain": "schwag"}]})
            },
            "global_accounts": {"data": '{"cosmetics": {"hat": true}}'},
            "guild_worlds": {"data": '{"market_multiplier": 1.5}'},
        }

    async def fetchval(self, sql, *params):
        self.operations.append(("fetchval", sql, params))
        if "app_schema_migrations" in sql:
            return None if self.missing_version else 1
        if "to_regprocedure" in sql:
            return None if self.missing_function else params[0]
        if "idle_grow_save_scoped_records" in sql:
            if self.fail_save:
                raise RuntimeError("simulated atomic write failure")
            return None
        raise AssertionError(sql)

    async def fetchrow(self, sql, *params):
        self.operations.append(("fetchrow", sql, params))
        table = next(
            (name for name in self.records if "public." + name in sql),
            None,
        )
        return self.records.get(table)

    async def fetch(self, sql, *params):
        self.operations.append(("fetch", sql, params))
        if "information_schema.columns" in sql:
            table = params[0]
            if table == "guild_profiles":
                cols = {
                    "guild_id", "user_id", "data", "balance", "heist_wins",
                    "has_notification_work", "has_pending_notification_work",
                    *CASINO_PROFIT_METRICS,
                }
            elif table == "global_accounts":
                cols = {"user_id", "data"}
            else:
                cols = {"guild_id", "data"}
            if self.missing_column and table == "guild_profiles":
                cols.remove("balance")
            return [{"column_name": name} for name in cols]
        if "idle_grow_list_notification_candidates" in sql:
            return [{"guild_id": 123, "user_id": 42}]
        if "FROM public.guild_profiles" in sql:
            return [
                {"user_id": 42, "balance": 50, "casino_total_profit": -30},
                {"user_id": 43, "balance": 0, "casino_total_profit": 60},
            ]
        raise AssertionError(sql)


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_):
        return False


class Pool:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False

    def acquire(self):
        return Acquire(self.conn)

    async def close(self):
        self.closed = True


class PoolFactory:
    def __init__(self):
        self.conn = Connection()
        self.pool = Pool(self.conn)
        self.kwargs = None

    async def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.pool


def run(coro):
    return asyncio.run(coro)


def test_neon_url_must_not_point_at_supabase_or_other_database():
    with pytest.raises(ValueError, match="Neon PostgreSQL URL"):
        NeonScopedBackend("postgresql://postgres@db.example.com/db")


def test_neon_schema_and_readonly_contract():
    async def scenario():
        factory = PoolFactory()
        backend = NeonScopedBackend(DSN, pool_factory=factory)
        await backend.start()
        assert factory.kwargs["max_size"] == 3
        assert factory.kwargs["min_size"] == 0
        try:
            await backend.verify_schema()
            assert await backend.load(guild_profile_key(123, 42)) == {
                "grams": 123,
                "plants": [{"strain": "schwag"}],
            }
            assert await backend.load(global_account_key(42)) == {
                "cosmetics": {"hat": True}
            }
            assert await backend.load(guild_world_key(123)) == {
                "market_multiplier": 1.5
            }
            assert await backend.list_guild_leaderboard(123, limit=2) == [
                (42, 50), (43, 0)
            ]
            assert await backend.list_guild_casino_leaderboard(
                123, metric="casino_total_profit", limit=2
            ) == [(42, -30), (43, 60)]
            assert await backend.list_notification_candidates([123, 123]) == [
                (123, 42)
            ]
            assert await backend.list_notification_candidates([]) == []
            assert any(
                REQUIRED_SCHEMA_VERSION in params
                for _kind, _sql, params in factory.conn.operations
            )
        finally:
            await backend.close()
        assert factory.pool.closed is True

    run(scenario())


@pytest.mark.parametrize("broken", ["missing_version", "missing_column", "missing_function"])
def test_neon_rejects_missing_schema(broken):
    async def scenario():
        factory = PoolFactory()
        setattr(factory.conn, broken, True)
        backend = NeonScopedBackend(DSN, pool_factory=factory)
        await backend.start()
        try:
            with pytest.raises(NeonSchemaError):
                await backend.verify_schema()
        finally:
            await backend.close()
    run(scenario())


def test_neon_atomic_save_fails_without_partial_fallback():
    async def scenario():
        factory = PoolFactory()
        backend = NeonScopedBackend(DSN, pool_factory=factory)
        await backend.start()
        try:
            await backend.save_many({
                global_account_key(42): {"cosmetics": {"item": "a"}},
                guild_profile_key(123, 42): {"grams": 999},
                guild_world_key(123): {"market_multiplier": 1.2},
            })
            writes = [
                (sql, args) for kind, sql, args in factory.conn.operations
                if "idle_grow_save_scoped_records" in sql
            ]
            assert len(writes) == 1
            sql, params = writes[0]
            assert "$1::jsonb,$2::jsonb,$3::jsonb" in sql
            assert json.loads(params[0])[0]["user_id"] == 42
            assert json.loads(params[1])[0]["guild_id"] == 123
            assert json.loads(params[2])[0]["data"] == {"market_multiplier": 1.2}
            factory.conn.fail_save = True
            with pytest.raises(RuntimeError, match="atomic write failure"):
                await backend.save_many({guild_profile_key(123, 42): {"grams": 1000}})
            await backend.save_many({})
            assert len([
                1 for _kind, sql, _params in factory.conn.operations
                if "idle_grow_save_scoped_records" in sql
            ]) == 2
        finally:
            await backend.close()
    run(scenario())


def test_neon_rejects_invalid_leaderboards():
    async def scenario():
        backend = NeonScopedBackend(DSN, pool_factory=PoolFactory())
        await backend.start()
        try:
            with pytest.raises(ValueError, match="unsupported casino"):
                await backend.list_guild_casino_leaderboard(
                    123, metric="sql_injection"
                )
            with pytest.raises(ValueError, match="limit"):
                await backend.list_guild_leaderboard(123, limit=101)
        finally:
            await backend.close()
    run(scenario())
