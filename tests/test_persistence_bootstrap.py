import asyncio

import pytest

from persistence_bootstrap import PersistenceConfigurationError, build_scoped_database
from supabase_scoped_backend import REQUIRED_SCHEMA_VERSION


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _amount):
        return self

    def execute(self):
        if self.table_name == "app_schema_migrations":
            if self.filters.get("version") == REQUIRED_SCHEMA_VERSION:
                return Response([{"version": REQUIRED_SCHEMA_VERSION}])
            return Response([])
        return Response([])


class FakeClient:
    def table(self, table_name):
        return Query(self, table_name)


class Factory:
    def __init__(self):
        self.calls = []

    def __call__(self, url, key):
        self.calls.append((url, key))
        return FakeClient()


def run(coro):
    return asyncio.run(coro)


def test_bootstrap_requires_supabase_url():
    with pytest.raises(PersistenceConfigurationError, match="SUPABASE_URL"):
        run(build_scoped_database(environ={}, create_client_fn=Factory()))


def test_bootstrap_requires_service_role_key_not_generic_anon_key():
    environment = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "public-anon-key",
    }

    with pytest.raises(PersistenceConfigurationError, match="SUPABASE_SERVICE_ROLE_KEY"):
        run(build_scoped_database(environ=environment, create_client_fn=Factory()))


def test_bootstrap_verifies_schema_and_starts_manager():
    factory = Factory()
    environment = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
    }

    async def scenario():
        manager = await build_scoped_database(
            environ=environment,
            create_client_fn=factory,
            flush_interval=60,
        )
        try:
            assert manager._flush_task is not None
            assert factory.calls == [
                ("https://example.supabase.co", "server-secret")
            ]
        finally:
            await manager.close()

    run(scenario())
