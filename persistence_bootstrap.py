import os
from collections.abc import Mapping

from scoped_database import ScopedDatabaseManager
from supabase_scoped_backend import SupabaseScopedBackend


IDLE_SUPABASE_URL_ENV = "IDLE_SUPABASE_URL"
IDLE_SUPABASE_SERVICE_ROLE_KEY_ENV = "IDLE_SUPABASE_SERVICE_ROLE_KEY"


class PersistenceConfigurationError(RuntimeError):
    """Raised when required server-side persistence settings are missing."""


def _required_env(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name, "")).strip()
    if not value:
        raise PersistenceConfigurationError(f"{name} is required")
    return value


async def build_scoped_database(
    *,
    environ: Mapping[str, str] | None = None,
    create_client_fn=None,
    flush_interval: float = 10,
) -> ScopedDatabaseManager:
    """Build, verify, and start the production scoped database manager.

    Idle Grow uses dedicated environment names so another bot hosted beside it
    cannot accidentally supply a different Supabase project. The Discord bot is
    a trusted server process and therefore requires the service-role key.
    Public anon or publishable keys are intentionally unsupported.
    """

    env = environ if environ is not None else os.environ
    url = _required_env(env, IDLE_SUPABASE_URL_ENV)
    service_role_key = _required_env(env, IDLE_SUPABASE_SERVICE_ROLE_KEY_ENV)

    if create_client_fn is None:
        from supabase import create_client

        create_client_fn = create_client

    client = create_client_fn(url, service_role_key)
    backend = SupabaseScopedBackend(client)
    await backend.verify_schema()

    manager = ScopedDatabaseManager(backend, flush_interval=flush_interval)
    await manager.start()
    return manager
