import asyncio
from copy import deepcopy

import pytest

from persistence_scope import global_account_key, guild_profile_key, guild_world_key
from supabase_scoped_backend import (
    ATOMIC_SAVE_RPC,
    REQUIRED_SCHEMA_VERSION,
    SupabaseSchemaError,
    SupabaseScopedBackend,
)


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = {}
        self.payload = None

    def select(self, columns):
        self.client.selects.append((self.table_name, columns))
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, amount):
        return self

    def upsert(self, payload):
        self.payload = deepcopy(payload)
        return self

    def execute(self):
        if self.table_name in self.client.fail_tables:
            raise RuntimeError(f"missing table: {self.table_name}")
        if self.payload is not None:
            self.client.upserts.append((self.table_name, self.payload))
            return Response(self.payload)
        self.client.loads.append((self.table_name, dict(self.filters)))
        data = self.client.records.get((self.table_name, tuple(sorted(self.filters.items()))))
        return Response(deepcopy(data or []))


class RpcQuery:
    def __init__(self, client, name, params):
        self.client = client
        self.name = name
        self.params = deepcopy(params)

    def execute(self):
        if self.name in self.client.fail_rpcs:
            raise RuntimeError(f"missing rpc: {self.name}")
        self.client.rpc_calls.append((self.name, deepcopy(self.params)))
        return Response(None)


class FakeClient:
    def __init__(self):
        self.records = {}
        self.loads = []
        self.selects = []
        self.upserts = []
        self.rpc_calls = []
        self.fail_tables = set()
        self.fail_rpcs = set()

    def table(self, table_name):
        return Query(self, table_name)

    def rpc(self, name, params):
        return RpcQuery(self, name, params)


def run(coro):
    return asyncio.run(coro)


def install_schema_version(client):
    client.records[("app_schema_migrations", (("version", REQUIRED_SCHEMA_VERSION),))] = [
        {"version": REQUIRED_SCHEMA_VERSION}
    ]


def test_schema_verification_requires_recorded_migration_and_all_tables():
    client = FakeClient()
    install_schema_version(client)
    backend = SupabaseScopedBackend(client)

    run(backend.verify_schema())

    selected_tables = [table for table, _columns in client.selects]
    assert selected_tables == [
        "app_schema_migrations",
        "global_accounts",
        "guild_profiles",
        "guild_worlds",
    ]


def test_schema_verification_rejects_missing_atomic_save_rpc():
    client = FakeClient()
    install_schema_version(client)
    client.fail_rpcs.add(ATOMIC_SAVE_RPC)
    backend = SupabaseScopedBackend(client)

    with pytest.raises(SupabaseSchemaError, match="Required Supabase RPC is unavailable"):
        run(backend.verify_schema())


def test_schema_verification_rejects_missing_migration():
    backend = SupabaseScopedBackend(FakeClient())

    with pytest.raises(SupabaseSchemaError, match="Required Supabase migration is missing"):
        run(backend.verify_schema())


def test_schema_verification_reports_missing_table():
    client = FakeClient()
    install_schema_version(client)
    client.fail_tables.add("guild_profiles")
    backend = SupabaseScopedBackend(client)

    with pytest.raises(SupabaseSchemaError, match="guild_profiles"):
        run(backend.verify_schema())


def test_load_routes_each_scope_to_its_own_table():
    client = FakeClient()
    backend = SupabaseScopedBackend(client)
    profile = guild_profile_key(100, 200)
    client.records[("guild_profiles", (("guild_id", 100), ("user_id", 200)))] = [
        {"data": {"grams": 900}}
    ]

    assert run(backend.load(profile)) == {"grams": 900}
    assert client.loads == [
        ("guild_profiles", {"guild_id": 100, "user_id": 200})
    ]


def test_missing_record_returns_none():
    backend = SupabaseScopedBackend(FakeClient())

    assert run(backend.load(guild_world_key(100))) is None


def test_save_many_uses_one_atomic_rpc_for_all_scoped_tables():
    client = FakeClient()
    backend = SupabaseScopedBackend(client)
    account = global_account_key(200)
    first_profile = guild_profile_key(100, 200)
    second_profile = guild_profile_key(101, 200)
    world = guild_world_key(100)

    run(
        backend.save_many(
            {
                account: {"collection": []},
                first_profile: {"grams": 500},
                second_profile: {"grams": 750},
                world: {"weather": "Rainy"},
            }
        )
    )

    assert client.upserts == []
    assert client.rpc_calls == []
    assert client.rpc_calls == [
        (
            ATOMIC_SAVE_RPC,
            {
                "p_global_accounts": [
                    {"user_id": 200, "data": {"collection": []}}
                ],
                "p_guild_profiles": [
                    {"guild_id": 100, "user_id": 200, "data": {"grams": 500}},
                    {"guild_id": 101, "user_id": 200, "data": {"grams": 750}},
                ],
                "p_guild_worlds": [
                    {"guild_id": 100, "data": {"weather": "Rainy"}}
                ],
            },
        )
    ]


def test_empty_save_does_not_touch_supabase():
    client = FakeClient()
    backend = SupabaseScopedBackend(client)

    run(backend.save_many({}))

    assert client.upserts == []
