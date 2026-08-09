import asyncio
import json
from pathlib import Path

import pytest

from minecraft_service import (
    TOP_METRICS,
    aura_total_level,
    clean_motd,
    format_duration_from_ticks,
    metric_value,
    normalize_host,
    ping_java_server,
    validate_port,
)
from minecraft_storage import (
    SCHEMA_STATEMENTS,
    TursoConfig,
    _typed_arg,
    sort_player_rows,
    turso_http_pipeline_url,
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


def test_turso_url_normalization_accepts_current_database_url_forms():
    assert (
        turso_http_pipeline_url("https://plug-example.turso.io")
        == "https://plug-example.turso.io/v2/pipeline"
    )
    assert (
        turso_http_pipeline_url("libsql://plug-example.turso.io")
        == "https://plug-example.turso.io/v2/pipeline"
    )
    assert (
        turso_http_pipeline_url("turso://plug-example.turso.io")
        == "https://plug-example.turso.io/v2/pipeline"
    )
    assert (
        turso_http_pipeline_url("https://plug-example.turso.io/v2/pipeline")
        == "https://plug-example.turso.io/v2/pipeline"
    )


def test_turso_config_requires_both_values(monkeypatch):
    monkeypatch.delenv("MINECRAFT_TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("MINECRAFT_TURSO_AUTH_TOKEN", raising=False)
    assert TursoConfig.from_env() is None

    monkeypatch.setenv("MINECRAFT_TURSO_DATABASE_URL", "turso://plug-example.turso.io")
    with pytest.raises(Exception, match="must both be set"):
        TursoConfig.from_env()

    monkeypatch.setenv("MINECRAFT_TURSO_AUTH_TOKEN", "test-token")
    config = TursoConfig.from_env()
    assert config is not None
    assert config.pipeline_url == "https://plug-example.turso.io/v2/pipeline"


def test_turso_bound_argument_encoding_preserves_large_discord_ids():
    assert _typed_arg(1534800308876742698) == {
        "type": "integer",
        "value": "1534800308876742698",
    }
    assert _typed_arg(None) == {"type": "null"}
    assert _typed_arg(12.5) == {"type": "float", "value": "12.5"}


def test_schema_is_dedicated_turso_minecraft_state():
    schema = "\n".join(SCHEMA_STATEMENTS).lower()
    for table in (
        "minecraft_servers",
        "minecraft_runtime",
        "minecraft_players",
        "minecraft_links",
        "minecraft_activity",
    ):
        assert table in schema
    assert "supabase" not in schema
    assert "player_ip" not in schema
    assert "ip_address" not in schema


def test_duration_aura_and_leaderboard_metrics():
    assert format_duration_from_ticks(20 * 90) == "1m"
    assert format_duration_from_ticks(20 * (2 * 3600 + 5 * 60)) == "2h 5m"
    player = {
        "username": "Miner",
        "playtime_ticks": 72000,
        "stats": {"player_kills": 7, "mob_kills": 80, "deaths": 2, "jumps": 123},
        "aura_skills": {
            "farming": {"level": 12, "xp": 4.5},
            "mining": {"level": 9, "xp": 1.0},
        },
    }
    other = {
        "username": "Builder",
        "playtime_ticks": 36000,
        "stats": {"player_kills": 2, "mob_kills": 10, "deaths": 1, "jumps": 20},
        "aura_skills": {"farming": {"level": 4}},
    }
    assert aura_total_level(player) == 21
    assert metric_value(player, "kills") == 7
    assert metric_value(player, "aura") == 21
    assert sort_player_rows([other, player], "playtime")[0][0]["username"] == "Miner"
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
        assert result["sample_names"] == ["PlayerOne"]
        assert result["motd"] == "Hello world"

    asyncio.run(scenario())


def test_minecraft_source_is_namespaced_and_has_no_supabase_bridge_path():
    source = (ROOT / "minecraft.py").read_text(encoding="utf-8")
    service = (ROOT / "minecraft_service.py").read_text(encoding="utf-8")
    storage = (ROOT / "minecraft_storage.py").read_text(encoding="utf-8")

    assert '@commands.command(name="mcprofile")' in source
    assert '@commands.command(name="mcstats")' in source
    assert '@commands.command(name="mcstatus")' in source
    assert '@commands.command(name="profile")' not in source
    assert '@commands.command(name="stats")' not in source
    assert '@commands.command(name="help")' not in source
    assert '@commands.command(name="players")' not in source
    assert 'name="minecraft"' in source
    assert "bridgekey" not in source
    assert "supabase" not in service.lower()
    assert "supabase" not in storage.lower()
