import os
from collections.abc import Mapping

from neon_scoped_backend import NeonScopedBackend
from scoped_database import ScopedDatabaseManager
from supabase_scoped_backend import SupabaseScopedBackend


IDLE_PERSISTENCE_BACKEND_ENV = "IDLE_PERSISTENCE_BACKEND"
IDLE_NEON_DATABASE_URL_ENV = "IDLE_NEON_DATABASE_URL"
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

    Idle Grow uses dedicated environment names so other bots cannot
    accidentally supply database credentials. The existing Supabase route
    remains the default until Neon is explicitly selected; no automatic
    cross-provider fallback is allowed if the new provider fails.
    """

    env = environ if environ is not None else os.environ
    selected = str(env.get(IDLE_PERSISTENCE_BACKEND_ENV, "supabase")).lower().strip()
    if selected == "neon":
        backend = NeonScopedBackend(_required_env(env, IDLE_NEON_DATABASE_URL_ENV))
        await backend.start()
    elif selected == "supabase":
        url = _required_env(env, IDLE_SUPABASE_URL_ENV)
        key = _required_env(env, IDLE_SUPABASE_SERVICE_ROLE_KEY_ENV)
        if create_client_fn is None:
            from supabase import create_client

            create_client_fn = create_client
        backend = SupabaseScopedBackend(create_client_fn(url, key))
    else:
        raise PersistenceConfigurationError(
            "IDLE_PERSISTENCE_BACKEND must be 'supabase' or 'neon'"
        )

    try:
        await backend.verify_schema()
        manager = ScopedDatabaseManager(backend, flush_interval=flush_interval)
        await manager.start()
        return manager
    except Exception:
        close = getattr(backend, "close", None)
        if callable(close):
            await close()
        raise
