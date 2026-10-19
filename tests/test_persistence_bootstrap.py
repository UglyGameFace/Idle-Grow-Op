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


class RpcQuery:
    def execute(self):
        return Response(None)


class FakeClient:
    def table(self, table_name):
        return Query(self, table_name)

    def rpc(self, _name, _params):
        return RpcQuery()


class Factory:
    def __init__(self):
        self.calls = []

    def __call__(self, url, key):
        self.calls.append((url, key))
        return FakeClient()


def run(coro):
    return asyncio.run(coro)


def test_bootstrap_requires_idle_supabase_url():
    with pytest.raises(PersistenceConfigurationError, match="IDLE_SUPABASE_URL"):
        run(build_scoped_database(environ={}, create_client_fn=Factory()))


def test_bootstrap_rejects_generic_or_legacy_keys():
    environment = {
        "SUPABASE_URL": "https://dank-shield.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "other-bot-secret",
        "IDLE_SUPABASE_URL": "https://idle-grow.supabase.co",
        "IDLE_SUPABASE_KEY": "public-or-legacy-key",
    }

    with pytest.raises(
        PersistenceConfigurationError,
        match="IDLE_SUPABASE_SERVICE_ROLE_KEY",
    ):
        run(build_scoped_database(environ=environment, create_client_fn=Factory()))


def test_bootstrap_uses_only_idle_grow_credentials_and_starts_manager():
    factory = Factory()
    environment = {
        "SUPABASE_URL": "https://dank-shield.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "other-bot-secret",
        "IDLE_SUPABASE_URL": "https://idle-grow.supabase.co",
        "IDLE_SUPABASE_SERVICE_ROLE_KEY": "idle-grow-server-secret",
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
                ("https://idle-grow.supabase.co", "idle-grow-server-secret")
            ]
        finally:
            await manager.close()

    run(scenario())


def test_neon_selected_requires_dedicated_connection_setting():
    with pytest.raises(PersistenceConfigurationError, match="IDLE_NEON_DATABASE_URL"):
        run(build_scoped_database(environ={"IDLE_PERSISTENCE_BACKEND": "neon"}))


def test_invalid_provider_never_silently_uses_supabase():
    with pytest.raises(PersistenceConfigurationError, match="IDLE_PERSISTENCE_BACKEND"):
        run(build_scoped_database(environ={"IDLE_PERSISTENCE_BACKEND": "unknown"}))


def test_neon_selection_starts_backend_without_supabase_credentials(monkeypatch):
    import persistence_bootstrap

    created = []

    class FakeNeon:
        def __init__(self, dsn):
            created.append(self)
            self.dsn = dsn
            self.opened = False
            self.verified = False
            self.closed = False

        async def start(self):
            self.opened = True

        async def verify_schema(self):
            assert self.opened
            self.verified = True

        async def close(self):
            self.closed = True

        async def load(self, _key):
            return None

        async def save_many(self, _records):
            return None

    monkeypatch.setattr(persistence_bootstrap, "NeonScopedBackend", FakeNeon)

    async def scenario():
        manager = await build_scoped_database(
            environ={
                "IDLE_PERSISTENCE_BACKEND": "neon",
                "IDLE_NEON_DATABASE_URL": "postgresql://secret.test/neon",
            },
            create_client_fn=lambda *_: (_ for _ in ()).throw(
                AssertionError("Supabase must not be used for Neon")
            ),
        )
        assert created[0].verified
        assert manager.backend is created[0]
        await manager.close()
        assert created[0].closed

    run(scenario())


def test_neon_failed_schema_check_closes_connection_pool(monkeypatch):
    import persistence_bootstrap

    state = {"closed": False}

    class BrokenNeon:
        def __init__(self, _dsn):
            pass

        async def start(self):
            pass

        async def verify_schema(self):
            raise RuntimeError("schema check failed")

        async def close(self):
            state["closed"] = True

    monkeypatch.setattr(persistence_bootstrap, "NeonScopedBackend", BrokenNeon)

    with pytest.raises(RuntimeError, match="schema check failed"):
        run(build_scoped_database(environ={
            "IDLE_PERSISTENCE_BACKEND": "neon",
            "IDLE_NEON_DATABASE_URL": "postgresql://example.test/neon",
        }))
    assert state["closed"]
