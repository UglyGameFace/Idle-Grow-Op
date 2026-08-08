import asyncio
import json
from pathlib import Path

import pytest

from minecraft_service import (
    TOP_METRICS,
    MinecraftDataService,
    aura_total_level,
    clean_motd,
    format_duration_from_ticks,
    metric_value,
    normalize_host,
    ping_java_server,
    validate_port,
)


ROOT = Path(__file__).resolve().parents[1]


def test_host_and_port_validation():
    assert normalize_host("play.example.net") == "play.example.net"
    assert normalize_host("[::1]") == "::1"
    with pytest.raises(ValueError):
        normalize_host("https://play.example.net")
    with pytest.raises(ValueError):
        normalize_host("play.example.net/path")
    assert validate_port(27002) == 27002
    with pytest.raises(ValueError):
        validate_port(0)
    with pytest.raises(ValueError):
        validate_port(70000)


def test_duration_and_aura_metrics():
    assert format_duration_from_ticks(20 * 90) == "1m"
    assert format_duration_from_ticks(20 * (2 * 3600 + 5 * 60)) == "2h 5m"
    row = {
        "playtime_ticks": 72000,
        "stats": {"player_kills": 7, "mob_kills": 80, "deaths": 2, "jumps": 123},
        "aura_skills": {
            "farming": {"level": 12, "xp": 4.5},
            "mining": {"level": 9, "xp": 1.0},
        },
    }
    assert aura_total_level(row) == 21
    assert metric_value(row, "kills") == 7
    assert metric_value(row, "aura") == 21
    assert set(TOP_METRICS) == {"playtime", "kills", "mobs", "deaths", "jumps", "aura"}


def test_motd_flattens_components_and_strips_format_codes():
    value = {
        "text": "§aThe 420 ",
        "extra": [{"text": "§bServer"}, {"text": "!"}],
    }
    assert clean_motd(value) == "The 420 Server!"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


async def _read_varint(reader):
    result = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
    raise AssertionError("bad varint")


def test_java_status_ping_protocol_round_trip():
    async def scenario():
        async def handler(reader, writer):
            length = await _read_varint(reader)
            await reader.readexactly(length)
            request_length = await _read_varint(reader)
            assert request_length == 1
            request_id = await _read_varint(reader)
            assert request_id == 0

            payload = json.dumps(
                {
                    "version": {"name": "Paper 26.2", "protocol": 776},
                    "players": {
                        "online": 2,
                        "max": 100,
                        "sample": [{"name": "PlayerOne", "id": "x"}],
                    },
                    "description": {"text": "Hello", "extra": [{"text": " world"}]},
                }
            ).encode()
            packet = b"\x00" + _varint(len(payload)) + payload
            writer.write(_varint(len(packet)) + packet)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            result = await ping_java_server("127.0.0.1", port, timeout=2)
        assert result["players_online"] == 2
        assert result["players_max"] == 100
        assert result["version_name"] == "Paper 26.2"
        assert result["protocol"] == 776
        assert result["sample_names"] == ["PlayerOne"]
        assert result["motd"] == "Hello world"

    asyncio.run(scenario())


class FakeResponse:
    def __init__(self, data=None):
        self.data = data or []


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = []
        self.payload = None
        self.operation = "select"

    def select(self, _fields):
        self.operation = "select"
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def ilike(self, key, value):
        self.filters.append(("ilike", key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _limit):
        return self

    def upsert(self, payload, on_conflict=None):
        self.operation = "upsert"
        self.payload = dict(payload)
        return self

    def execute(self):
        if self.operation == "upsert":
            self.client.rows.setdefault(self.table_name, [])
            guild_id = self.payload.get("guild_id")
            existing = next(
                (row for row in self.client.rows[self.table_name] if row.get("guild_id") == guild_id),
                None,
            )
            if existing is None:
                existing = dict(self.payload)
                self.client.rows[self.table_name].append(existing)
            else:
                existing.update(self.payload)
            return FakeResponse([dict(existing)])

        rows = list(self.client.rows.get(self.table_name, []))
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif kind == "ilike":
                rows = [row for row in rows if str(row.get(key, "")).lower() == str(value).lower()]
        return FakeResponse([dict(row) for row in rows])


class FakeClient:
    def __init__(self):
        self.rows = {
            "minecraft_servers": [],
            "minecraft_bridge_auth": [],
            "minecraft_players": [],
            "minecraft_activity": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


def test_data_service_configures_server_and_rotates_secret():
    async def scenario():
        client = FakeClient()
        service = MinecraftDataService(lambda: client)
        row = await service.configure_server(
            123,
            display_name="The 420 Server",
            host="play.example.net",
            java_port=27002,
            bedrock_port=27002,
        )
        assert row["host"] == "play.example.net"
        loaded = await service.get_server(123)
        assert loaded["display_name"] == "The 420 Server"

        first = await service.rotate_bridge_secret(123)
        second = await service.rotate_bridge_secret(123)
        assert first != second
        assert len(second) >= 40
        auth = client.rows["minecraft_bridge_auth"][0]
        assert auth["bridge_secret"] == second

    asyncio.run(scenario())


def test_minecraft_source_does_not_steal_existing_generic_prefixes():
    source = (ROOT / "minecraft.py").read_text(encoding="utf-8")
    assert '@commands.command(name="mcprofile")' in source
    assert '@commands.command(name="mcstats")' in source
    assert '@commands.command(name="mcstatus")' in source
    assert '@commands.command(name="profile")' not in source
    assert '@commands.command(name="stats")' not in source
    assert '@commands.command(name="help")' not in source
    assert '@commands.command(name="players")' not in source
    assert 'name="minecraft"' in source
