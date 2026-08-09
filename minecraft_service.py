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
    pass


class MinecraftDataUnavailable(MinecraftServiceError):
    pass


def normalize_host(value: str) -> str:
    return validate_host(value)


def discord_timestamp(value: Any, style: str = "R") -> str:
    return discord_time(value, style)


def format_duration_from_ticks(value: Any) -> str:
    return format_playtime(value)


def metric_value(row: dict[str, Any], metric: str) -> int:
    key = str(metric or "playtime").lower()
    if key == "playtime":
        return max(0, int(row.get("playtime_ticks") or 0))
    if key == "aura":
        return aura_total_level(row)
    stat_key = {
        "kills": "player_kills",
        "mobs": "mob_kills",
        "deaths": "deaths",
        "jumps": "jumps",
    }.get(key)
    if stat_key is None:
        raise ValueError("metric must be playtime, kills, mobs, deaths, jumps, or aura")
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    return max(0, int(stats.get(stat_key) or 0))


class MinecraftDataService:
    """Small command-layer facade over The Plug's dedicated Turso Minecraft store."""

    def __init__(self, *, store: MinecraftTursoStore | None = None):
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

    async def player_by_name(self, guild_id: Any, username: str):
        try:
            return await self.store.get_player_by_name(int(guild_id), username)
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def player_by_discord(self, guild_id: Any, discord_user_id: Any):
        try:
            return await self.store.get_player_by_discord(
                int(guild_id), int(discord_user_id)
            )
        except MinecraftStoreError as exc:
            raise MinecraftDataUnavailable(str(exc)) from exc

    async def recent_activity(self, guild_id: Any, *, limit: int = 12):
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

    async def records(self, guild_id: Any):
        rows = await self.list_players(guild_id, limit=500)
        result: dict[str, tuple[dict[str, Any], int] | None] = {}
        for metric in TOP_METRICS:
            ranked = sort_player_rows(rows, metric)
            result[metric] = ranked[0] if ranked else None
        return result
