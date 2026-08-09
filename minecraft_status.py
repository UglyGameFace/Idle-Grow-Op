from __future__ import annotations

import asyncio
import json
import re
import struct
import time
from datetime import datetime, timezone
from typing import Any


DEFAULT_PING_TIMEOUT_SECONDS = 4.0


class MinecraftPingError(RuntimeError):
    """Raised when a Java status ping cannot be completed safely."""


def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("host is required")
    if "://" in host:
        raise ValueError("use only the hostname or IP, without http:// or https://")
    if any(character.isspace() for character in host):
        raise ValueError("host cannot contain spaces")
    if "/" in host:
        raise ValueError("host cannot contain a path")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or len(host) > 255:
        raise ValueError("host is invalid")
    return host


def validate_port(value: int, name: str = "port") -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def _encode_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value &= 0xFFFFFFFF
    payload = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            payload.append(byte | 0x80)
        else:
            payload.append(byte)
            return bytes(payload)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    result = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
    raise MinecraftPingError("server returned an invalid VarInt")


def _encode_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _encode_varint(len(encoded)) + encoded


def _flatten_component(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flatten_component(part) for part in value)
    if not isinstance(value, dict):
        return ""
    text = str(value.get("text") or "")
    if not text and value.get("translate"):
        text = str(value["translate"])
    extra = value.get("extra")
    if isinstance(extra, list):
        text += "".join(_flatten_component(part) for part in extra)
    return text


_FORMATTING_CODE = re.compile(r"§.")


def clean_motd(value: Any) -> str:
    return _FORMATTING_CODE.sub("", _flatten_component(value)).strip()


async def ping_java_server(
    host: str,
    port: int,
    *,
    timeout: float = DEFAULT_PING_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Use Minecraft's Server List Ping protocol without an external API."""
    clean_host = validate_host(host)
    clean_port = validate_port(port)
    started = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(clean_host, clean_port),
            timeout=timeout,
        )
    except Exception as exc:
        raise MinecraftPingError(f"could not reach {clean_host}:{clean_port}") from exc

    try:
        handshake = (
            _encode_varint(0)
            + _encode_varint(0)
            + _encode_string(clean_host)
            + struct.pack(">H", clean_port)
            + _encode_varint(1)
        )
        writer.write(_encode_varint(len(handshake)) + handshake)
        writer.write(b"\x01\x00")
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        packet_length = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if not 1 <= packet_length <= 2_000_000:
            raise MinecraftPingError("server returned an invalid status packet length")
        packet_id = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if packet_id != 0:
            raise MinecraftPingError(f"unexpected status packet id {packet_id}")
        json_length = await asyncio.wait_for(_read_varint(reader), timeout=timeout)
        if not 1 <= json_length <= packet_length:
            raise MinecraftPingError("server returned an invalid status JSON length")
        raw = await asyncio.wait_for(reader.readexactly(json_length), timeout=timeout)
        response = json.loads(raw.decode("utf-8"))
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

    if not isinstance(response, dict):
        raise MinecraftPingError("server returned an invalid status document")
    version = response.get("version") if isinstance(response.get("version"), dict) else {}
    players = response.get("players") if isinstance(response.get("players"), dict) else {}
    sample = players.get("sample") if isinstance(players.get("sample"), list) else []

    return {
        "online": True,
        "host": clean_host,
        "port": clean_port,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "version_name": str(version.get("name") or "Unknown"),
        "protocol": int(version.get("protocol") or 0),
        "players_online": max(0, int(players.get("online") or 0)),
        "players_max": max(0, int(players.get("max") or 0)),
        "sample_names": [
            str(item.get("name"))
            for item in sample
            if isinstance(item, dict) and item.get("name")
        ],
        "motd": clean_motd(response.get("description")),
    }


def format_playtime(ticks: Any) -> str:
    seconds = max(0, int(ticks or 0)) // 20
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        timestamp = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            timestamp = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def discord_time(value: Any, style: str = "R") -> str:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "Unknown"
    return f"<t:{int(timestamp.timestamp())}:{style}>"
