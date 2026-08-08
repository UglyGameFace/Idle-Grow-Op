from __future__ import annotations

import asyncio
import json
import re
import secrets
import struct
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


DEFAULT_JAVA_PORT = 27002
DEFAULT_BEDROCK_PORT = 27002
DEFAULT_PING_TIMEOUT = 4.0
MINECRAFT_PLAYER_LIMIT = 500
MINECRAFT_ACTIVITY_LIMIT = 50

TOP_METRICS = {
    "playtime": ("playtime_ticks", "Playtime"),
    "kills": ("player_kills", "Player Kills"),
    "mobs": ("mob_kills", "Mob Kills"),
    "deaths": ("deaths", "Deaths"),
    "jumps": ("jumps", "Jumps"),
    "aura": ("aura_total_level", "AuraSkills Total"),
}


class MinecraftServiceError(RuntimeError):
    """Base error for Minecraft companion operations."""


class MinecraftDataUnavailable(MinecraftServiceError):
    """Raised when the companion Supabase schema is unavailable."""


class MinecraftPingError(MinecraftServiceError):
    """Raised when the Java server status endpoint cannot be reached."""


def _positive_int(value: Any, name: str) -> int:
    number = int(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def validate_port(value: Any, name: str = "port") -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def normalize_host(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("host is required")
    if "://" in host:
        raise ValueError("enter only the hostname or IP, without http:// or https://")
    if any(char.isspace() for char in host):
        raise ValueError("host cannot contain spaces")
    if "/" in host:
        raise ValueError("host cannot contain a path")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if len(host) > 255:
        raise ValueError("host is too long")
    return host


def _encode_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    result = 0
    for shift in range(0, 35, 7):
        raw = await reader.readexactly(1)
        byte = raw[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
    raise MinecraftPingError("server returned an invalid VarInt")


def _encode_string(value: str) -> bytes:
    payload = value.encode("utf-8")
    return _encode_varint(len(payload)) + payload


def _flatten_component(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flatten_component(item) for item in value)
    if not isinstance(value, dict):
        return ""
    text = str(value.get("text") or "")
    extra = value.get("extra")
    if isinstance(extra, list):
        text += "".join(_flatten_component(item) for item in extra)
    translate = value.get("translate")
    if translate and not text:
        text = str(translate)
    return text


_FORMAT_CODE = re.compile(r"§.")


def clean_motd(value: Any) -> str:
    return _FORMAT_CODE.sub("", _flatten_component(value)).strip()


async def ping_java_server(
    host: str,
    port: int,
    *,
    timeout: float = DEFAULT_PING_TIMEOUT,
) -> dict[str, Any]:
    """Perform the Java Server List Ping protocol without an extra dependency."""
    clean_host = normalize_host(host)
    clean_port = validate_port(port)
    started = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(clean_host, clean_port),
            timeout=timeout,
        )
    except Exception as exc:
        raise MinecraftPingError(f"could not connect to {clean_host}:{clean_port}") from exc

    try:
        # Status handshakes are intentionally version-tolerant. Protocol 0 is sufficient
        # because the server returns status before any login/version negotiation occurs.
        handshake = (
            _encode_varint(0)
            + _encode_varint(0)
            + _encode_string(clean_host)
            + struct.pack(">H", clean_port)
            + _encode_varint(1)
        )
        writer.write(_encode_varint(len(handshake)) + handshake)
        writer.write(b"\x01\x00")  # packet length 1, status request packet id 0
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        packet_length = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if packet_length <= 0 or packet_length > 2_000_000:
            raise MinecraftPingError("server returned an invalid status packet length")

        packet_id = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if packet_id != 0:
            raise MinecraftPingError(f"unexpected status packet id {packet_id}")

        string_length = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if string_length <= 0 or string_length > packet_length:
            raise MinecraftPingError("server returned an invalid status JSON length")

        raw = await asyncio.wait_for(reader.readexactly(string_length), timeout=timeout)
        payload = json.loads(raw.decode("utf-8"))
    except MinecraftPingError:
        raise
    except Exception as exc:
        raise MinecraftPingError("server status response could not be decoded") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    version = payload.get("version") if isinstance(payload.get("version"), dict) else {}
    players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
    sample = players.get("sample") if isinstance(players.get("sample"), list) else []
    sample_names = [
        str(row.get("name"))
        for row in sample
        if isinstance(row, dict) and row.get("name")
    ]

    return {
        "host": clean_host,
        "port": clean_port,
        "online": True,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "version_name": str(version.get("name") or "Unknown"),
        "protocol": int(version.get("protocol") or 0),
        "players_online": int(players.get("online") or 0),
        "players_max": int(players.get("max") or 0),
        "sample_names": sample_names,
        "motd": clean_motd(payload.get("description")),
        "raw": payload,
    }


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def discord_timestamp(value: Any, style: str = "R") -> str:
    dt = parse_timestamp(value)
    if dt is None:
        return "Unknown"
    return f"<t:{int(dt.timestamp())}:{style}>"


def format_duration_from_ticks(value: Any) -> str:
    ticks = max(0, int(value or 0))
    seconds = ticks // 20
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def aura_total_level(row: dict[str, Any]) -> int:
    skills = row.get("aura_skills")
    if not isinstance(skills, dict):
        return 0
    total = 0
    for value in skills.values():
        if isinstance(value, dict):
            total += max(0, int(value.get("level") or 0))
    return total


def metric_value(row: dict[str, Any], metric: str) -> int:
    key = str(metric or "playtime").lower()
    if key not in TOP_METRICS:
        raise ValueError(f"unsupported metric: {key}")
    field, _ = TOP_METRICS[key]
    if field == "aura_total_level":
        return aura_total_level(row)
    if field == "playtime_ticks":
        return max(0, int(row.get("playtime_ticks") or 0))
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    return max(0, int(stats.get(field) or 0))


class MinecraftDataService:
    """Async wrapper around the existing trusted Supabase client."""

    def __init__(self, client_provider: Callable[[], Any]):
        self._client_provider = client_provider

    def _client(self):
        client = self._client_provider()
        if client is None:
            raise MinecraftDataUnavailable("trusted Supabase client is unavailable")
        return client

    async def _thread(self, fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except MinecraftServiceError:
            raise
        except Exception as exc:
            raise MinecraftDataUnavailable(
                "Minecraft companion database is unavailable. "
                "Run migrations/003_minecraft_companion.sql first."
            ) from exc

    async def get_server(self, guild_id: Any) -> dict[str, Any] | None:
        guild_number = _positive_int(guild_id, "guild_id")

        def run():
            response = (
                self._client()
                .table("minecraft_servers")
                .select("*")
                .eq("guild_id", guild_number)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            return dict(rows[0]) if rows else None

        return await self._thread(run)

    async def configure_server(
        self,
        guild_id: Any,
        *,
        display_name: str,
        host: str,
        java_port: int = DEFAULT_JAVA_PORT,
        bedrock_port: int = DEFAULT_BEDROCK_PORT,
    ) -> dict[str, Any]:
        guild_number = _positive_int(guild_id, "guild_id")
        clean_host = normalize_host(host)
        payload = {
            "guild_id": guild_number,
            "display_name": str(display_name or "Minecraft Server").strip()[:100],
            "host": clean_host,
            "java_port": validate_port(java_port, "java_port"),
            "bedrock_port": validate_port(bedrock_port, "bedrock_port"),
            "enabled": True,
        }

        def run():
            response = (
                self._client()
                .table("minecraft_servers")
                .upsert(payload, on_conflict="guild_id")
                .execute()
            )
            rows = response.data or []
            return dict(rows[0]) if rows else dict(payload)

        return await self._thread(run)

    async def rotate_bridge_secret(self, guild_id: Any) -> str:
        guild_number = _positive_int(guild_id, "guild_id")
        secret = secrets.token_urlsafe(36)
        payload = {
            "guild_id": guild_number,
            "bridge_secret": secret,
            "enabled": True,
        }

        def run():
            self._client().table("minecraft_bridge_auth").upsert(
                payload,
                on_conflict="guild_id",
            ).execute()

        await self._thread(run)
        return secret

    async def list_players(
        self,
        guild_id: Any,
        *,
        online_only: bool = False,
        limit: int = MINECRAFT_PLAYER_LIMIT,
    ) -> list[dict[str, Any]]:
        guild_number = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), MINECRAFT_PLAYER_LIMIT))

        def run():
            query = (
                self._client()
                .table("minecraft_players")
                .select("*")
                .eq("guild_id", guild_number)
            )
            if online_only:
                query = query.eq("online", True)
            response = query.order("username").limit(limit).execute()
            return [dict(row) for row in (response.data or [])]

        return await self._thread(run)

    async def player_by_name(
        self,
        guild_id: Any,
        username: str,
    ) -> dict[str, Any] | None:
        guild_number = _positive_int(guild_id, "guild_id")
        clean_name = str(username or "").strip()
        if not clean_name:
            return None

        def run():
            response = (
                self._client()
                .table("minecraft_players")
                .select("*")
                .eq("guild_id", guild_number)
                .ilike("username", clean_name)
                .order("last_seen", desc=True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            return dict(rows[0]) if rows else None

        return await self._thread(run)

    async def player_by_discord(
        self,
        guild_id: Any,
        discord_user_id: Any,
    ) -> dict[str, Any] | None:
        guild_number = _positive_int(guild_id, "guild_id")
        discord_number = _positive_int(discord_user_id, "discord_user_id")

        def run():
            response = (
                self._client()
                .table("minecraft_players")
                .select("*")
                .eq("guild_id", guild_number)
                .eq("discord_user_id", discord_number)
                .order("last_seen", desc=True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            return dict(rows[0]) if rows else None

        return await self._thread(run)

    async def recent_activity(
        self,
        guild_id: Any,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        guild_number = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), MINECRAFT_ACTIVITY_LIMIT))

        def run():
            response = (
                self._client()
                .table("minecraft_activity")
                .select("*")
                .eq("guild_id", guild_number)
                .order("occurred_at", desc=True)
                .limit(limit)
                .execute()
            )
            return [dict(row) for row in (response.data or [])]

        return await self._thread(run)

    async def top_players(
        self,
        guild_id: Any,
        metric: str,
        *,
        limit: int = 10,
    ) -> list[tuple[dict[str, Any], int]]:
        metric = str(metric or "playtime").lower()
        if metric not in TOP_METRICS:
            raise ValueError(
                f"metric must be one of: {', '.join(sorted(TOP_METRICS))}"
            )
        rows = await self.list_players(guild_id, limit=MINECRAFT_PLAYER_LIMIT)
        ranked = [(row, metric_value(row, metric)) for row in rows]
        ranked.sort(
            key=lambda item: (
                -item[1],
                str(item[0].get("username") or "").lower(),
            )
        )
        return ranked[: max(1, min(int(limit), 25))]

    async def records(self, guild_id: Any) -> dict[str, tuple[dict[str, Any], int] | None]:
        rows = await self.list_players(guild_id, limit=MINECRAFT_PLAYER_LIMIT)
        result: dict[str, tuple[dict[str, Any], int] | None] = {}
        for metric in ("playtime", "kills", "mobs", "deaths", "jumps", "aura"):
            ranked = [(row, metric_value(row, metric)) for row in rows]
            ranked.sort(key=lambda item: -item[1])
            result[metric] = ranked[0] if ranked else None
        return result
