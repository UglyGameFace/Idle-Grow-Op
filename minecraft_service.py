from __future__ import annotations

from typing import Any

from minecraft_status import (
    MinecraftPingError,
    clean_motd,
    discord_time,
    format_playtime,
    ping_java_server,
    validate_host,
    validate_port,
)
from minecraft_storage import (
    MinecraftStoreError,
    MinecraftTursoStore,
    aura_total_level,
    metric_value,
    sort_player_rows,
)


DEFAULT_JAVA_PORT = 27002
DEFAULT_BEDROCK_PORT = 27002
TOP_METRICS = {
    "playtime": ("playtime_ticks", "Playtime"),
    "kills": ("player_kills", "Player Kills"),
    "mobs": ("mob_kills", "Mob Kills"),
    "deaths": ("deaths", "Deaths"),
    "jumps": ("jumps", "Jumps"),
    "aura": ("aura_total_level", "AuraSkills Total"),
}


class MinecraftServiceError(RuntimeError):
    """Base error surfaced by the Discord Minecraft command layer."""


class MinecraftDataUnavailable(MinecraftServiceError):
    """Raised when the dedicated Minecraft Turso store cannot be used."""


def normalize_host(value: str) -> str:
    return validate_host(value)


def discord_timestamp(value: Any, style: str = "R") -> str:
    return discord_time(value, style)


def format_duration_from_ticks(value: Any) -> str:
    return format_playtime(value)


class MinecraftDataService:
    """Compatibility facade over the dedicated Turso Minecraft store.

    The existing Idle Grow Supabase persistence remains untouched. Minecraft data is
    intentionally isolated in its own Turso database so neither project can corrupt
    or authorize the other by accident.
    """

    def __init__(self, _legacy_client_provider=None, *, store: MinecraftTursoStore | None = None):
        # `_legacy_client_provider` is accepted temporarily so the command cog can be
        # migrated without a second command implementation. It is intentionally ignored.
        self.store = store or MinecraftTursoStore.from_env()

    @property
    def configured(self) -> bool:
        return self.store.configured

    async def close(self) -> None:
        await self.store.close()

    async def ensure_schema(self) -> None:
        try:
            await self.store.ensure_schema()
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def get_server(self, guild_id: Any) -> dict[str, Any] | None:
        try:
            return await self.store.get_server_with_runtime(int(guild_id))
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def configure_server(
        self,
        guild_id: Any,
        *,
        display_name: str,
        host: str,
        java_port: int = DEFAULT_JAVA_PORT,
        bedrock_port: int = DEFAULT_BEDROCK_PORT,
    ) -> dict[str, Any]:
        clean_host = normalize_host(host)
        clean_java = validate_port(java_port, "java_port")
        clean_bedrock = validate_port(bedrock_port, "bedrock_port")
        try:
            return await self.store.upsert_server(
                int(guild_id),
                display_name=str(display_name or "Minecraft Server").strip() or "Minecraft Server",
                host=clean_host,
                java_port=clean_java,
                bedrock_port=clean_bedrock,
            )
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def rotate_bridge_secret(self, guild_id: Any) -> str:
        raise MinecraftDataUnavailable(
            "Bridge secrets were retired when Minecraft persistence moved to Turso. "
            "Use a dedicated fine-grained Turso bridge token instead."
        )

    async def list_players(
        self,
        guild_id: Any,
        *,
        online_only: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        try:
            return await self.store.list_players(
                int(guild_id),
                online_only=online_only,
                limit=limit,
            )
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def player_by_name(
        self,
        guild_id: Any,
        username: str,
    ) -> dict[str, Any] | None:
        try:
            return await self.store.get_player_by_name(int(guild_id), username)
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def player_by_discord(
        self,
        guild_id: Any,
        discord_user_id: Any,
    ) -> dict[str, Any] | None:
        try:
            return await self.store.get_player_by_discord(
                int(guild_id),
                int(discord_user_id),
            )
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def recent_activity(
        self,
        guild_id: Any,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        try:
            return await self.store.recent_activity(int(guild_id), limit=limit)
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def top_players(
        self,
        guild_id: Any,
        metric: str,
        *,
        limit: int = 10,
    ) -> list[tuple[dict[str, Any], int]]:
        key = str(metric or "playtime").lower()
        if key not in TOP_METRICS:
            raise ValueError(
                f"metric must be one of: {', '.join(sorted(TOP_METRICS))}"
            )
        rows = await self.list_players(guild_id, limit=500)
        return sort_player_rows(rows, key)[: max(1, min(int(limit), 25))]

    async def records(
        self,
        guild_id: Any,
    ) -> dict[str, tuple[dict[str, Any], int] | None]:
        rows = await self.list_players(guild_id, limit=500)
        result: dict[str, tuple[dict[str, Any], int] | None] = {}
        for metric in TOP_METRICS:
            ranked = sort_player_rows(rows, metric)
            result[metric] = ranked[0] if ranked else None
        return result
