from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import aiohttp


MINECRAFT_TURSO_DATABASE_URL_ENV = "MINECRAFT_TURSO_DATABASE_URL"
MINECRAFT_TURSO_AUTH_TOKEN_ENV = "MINECRAFT_TURSO_AUTH_TOKEN"
MINECRAFT_SCHEMA_VERSION = "001_minecraft_companion"
MAX_PLAYER_QUERY = 500
MAX_ACTIVITY_QUERY = 50
DEFAULT_TIMEOUT_SECONDS = 12


class MinecraftStoreError(RuntimeError):
    pass


class MinecraftStoreNotConfigured(MinecraftStoreError):
    pass


class MinecraftSchemaError(MinecraftStoreError):
    pass


class MinecraftStoreRequestError(MinecraftStoreError):
    pass


def turso_http_pipeline_url(value: str) -> str:
    """Normalize Turso/libSQL connection URLs to the documented SQL-over-HTTP endpoint."""
    raw = str(value or "").strip()
    if not raw:
        raise MinecraftStoreNotConfigured("Minecraft Turso database URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme not in {"https", "turso", "libsql"}:
        raise MinecraftStoreNotConfigured(
            "Minecraft Turso URL must start with https://, turso://, or libsql://"
        )
    if not parsed.hostname:
        raise MinecraftStoreNotConfigured("Minecraft Turso URL has no hostname")
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    if path.endswith("/v2/pipeline"):
        path = path[: -len("/v2/pipeline")]
    return f"https://{host}{path}/v2/pipeline"


@dataclass(frozen=True)
class TursoConfig:
    database_url: str
    auth_token: str

    @classmethod
    def from_env(cls) -> "TursoConfig | None":
        url = str(os.getenv(MINECRAFT_TURSO_DATABASE_URL_ENV, "")).strip()
        token = str(os.getenv(MINECRAFT_TURSO_AUTH_TOKEN_ENV, "")).strip()
        if not url and not token:
            return None
        if not url or not token:
            raise MinecraftStoreNotConfigured(
                f"{MINECRAFT_TURSO_DATABASE_URL_ENV} and "
                f"{MINECRAFT_TURSO_AUTH_TOKEN_ENV} must both be set"
            )
        turso_http_pipeline_url(url)
        return cls(url, token)

    @property
    def pipeline_url(self) -> str:
        return turso_http_pipeline_url(self.database_url)


SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS minecraft_schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS minecraft_servers (
        guild_id INTEGER PRIMARY KEY,
        display_name TEXT NOT NULL,
        host TEXT NOT NULL,
        java_port INTEGER NOT NULL DEFAULT 25565,
        bedrock_port INTEGER NOT NULL DEFAULT 19132,
        enabled INTEGER NOT NULL DEFAULT 1,
        chat_channel_id INTEGER,
        log_channel_id INTEGER,
        proximity_lobby_id INTEGER,
        linked_role_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS minecraft_runtime (
        guild_id INTEGER PRIMARY KEY,
        bridge_instance_id TEXT,
        bridge_version TEXT,
        heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        minecraft_version TEXT,
        paper_version TEXT,
        geyser_version TEXT,
        floodgate_version TEXT,
        tps_1m REAL,
        tps_5m REAL,
        tps_15m REAL,
        mspt REAL,
        memory_used_mb REAL,
        memory_max_mb REAL,
        online_players INTEGER NOT NULL DEFAULT 0,
        max_players INTEGER NOT NULL DEFAULT 0,
        bedrock_online INTEGER NOT NULL DEFAULT 0,
        plugins_json TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS minecraft_players (
        guild_id INTEGER NOT NULL,
        player_uuid TEXT NOT NULL,
        username TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'java',
        xuid TEXT,
        discord_user_id INTEGER,
        online INTEGER NOT NULL DEFAULT 0,
        first_seen TEXT,
        last_seen TEXT,
        joined_at TEXT,
        playtime_ticks INTEGER NOT NULL DEFAULT 0,
        world TEXT,
        game_mode TEXT,
        health REAL,
        food INTEGER,
        experience_level INTEGER,
        stats_json TEXT NOT NULL DEFAULT '{}',
        aura_skills_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, player_uuid)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_minecraft_players_name ON minecraft_players (guild_id, username COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_minecraft_players_discord ON minecraft_players (guild_id, discord_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_minecraft_players_online ON minecraft_players (guild_id, online)",
    """CREATE TABLE IF NOT EXISTS minecraft_links (
        guild_id INTEGER NOT NULL,
        discord_user_id INTEGER NOT NULL,
        player_uuid TEXT NOT NULL,
        username TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'java',
        xuid TEXT,
        linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, discord_user_id, player_uuid)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_minecraft_links_player ON minecraft_links (guild_id, player_uuid)",
    """CREATE TABLE IF NOT EXISTS minecraft_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        player_uuid TEXT,
        username TEXT,
        event_type TEXT NOT NULL,
        detail TEXT,
        occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_minecraft_activity_recent ON minecraft_activity (guild_id, occurred_at DESC)",
)


def _typed_arg(value: Any) -> dict[str, str]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": "text", "value": str(value)}


def _statement(sql: str, args=()) -> dict[str, Any]:
    stmt: dict[str, Any] = {"sql": str(sql)}
    if args:
        stmt["args"] = [_typed_arg(value) for value in args]
    return {"type": "execute", "stmt": stmt}


def _decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    kind = value.get("type")
    raw = value.get("value")
    if kind == "null":
        return None
    if kind == "integer":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if kind == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    return raw


def _rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    response = result.get("response") if isinstance(result, dict) else None
    execute = response.get("result") if isinstance(response, dict) else None
    if not isinstance(execute, dict):
        return []
    columns = [str(column.get("name") or "") for column in (execute.get("cols") or [])]
    return [
        dict(zip(columns, [_decode_value(value) for value in row]))
        for row in (execute.get("rows") or [])
    ]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(decoded) if isinstance(decoded, list) else []


def _normalize_player(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["online"] = bool(row.get("online"))
    row["stats"] = _json_object(row.pop("stats_json", "{}"))
    row["aura_skills"] = _json_object(row.pop("aura_skills_json", "{}"))
    return row


def _normalize_runtime(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["plugins"] = _json_array(row.pop("plugins_json", "[]"))
    row["bridge_last_seen"] = row.get("heartbeat_at")
    row["tps"] = row.get("tps_1m")
    return row


class MinecraftTursoStore:
    """Dedicated Minecraft persistence using Turso's SQL-over-HTTP pipeline."""

    def __init__(self, config: TursoConfig | None, *, session=None):
        self.config = config
        self._session: aiohttp.ClientSession | None = session
        self._owns_session = session is None
        self._schema_ready = False

    @classmethod
    def from_env(cls) -> "MinecraftTursoStore":
        return cls(TursoConfig.from_env())

    @property
    def configured(self) -> bool:
        return self.config is not None

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
            )
            self._owns_session = True
        return self._session

    async def _pipeline(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.config is None:
            raise MinecraftStoreNotConfigured(
                "Minecraft Turso storage is not configured on the bot host"
            )
        session = await self._http_session()
        try:
            async with session.post(
                self.config.pipeline_url,
                headers={
                    "Authorization": f"Bearer {self.config.auth_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [*requests, {"type": "close"}]},
            ) as response:
                body = await response.text()
                if not 200 <= response.status < 300:
                    raise MinecraftStoreRequestError(
                        f"Turso returned HTTP {response.status}"
                    )
        except MinecraftStoreError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise MinecraftStoreRequestError("Turso request failed") from exc

        try:
            document = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MinecraftStoreRequestError("Turso returned invalid JSON") from exc
        results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(results, list):
            raise MinecraftStoreRequestError("Turso response contained no results")
        results = results[: len(requests)]
        if len(results) != len(requests) or any(
            not isinstance(result, dict) or result.get("type") != "ok"
            for result in results
        ):
            raise MinecraftStoreRequestError("Turso rejected a SQL statement")
        return results

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        requests = [_statement(sql) for sql in SCHEMA_STATEMENTS]
        requests.append(
            _statement(
                "INSERT OR IGNORE INTO minecraft_schema_migrations (version) VALUES (?)",
                (MINECRAFT_SCHEMA_VERSION,),
            )
        )
        try:
            await self._pipeline(requests)
        except MinecraftStoreError as exc:
            raise MinecraftSchemaError(
                "Could not prepare the Minecraft companion Turso schema"
            ) from exc
        self._schema_ready = True

    async def _query(self, sql: str, args=()) -> list[dict[str, Any]]:
        await self.ensure_schema()
        return _rows_from_result((await self._pipeline([_statement(sql, args)]))[0])

    async def _execute(self, sql: str, args=()) -> None:
        await self.ensure_schema()
        await self._pipeline([_statement(sql, args)])

    async def get_server(self, guild_id: int) -> dict[str, Any] | None:
        rows = await self._query(
            "SELECT * FROM minecraft_servers WHERE guild_id = ? LIMIT 1",
            (int(guild_id),),
        )
        return rows[0] if rows else None

    async def get_runtime(self, guild_id: int) -> dict[str, Any] | None:
        rows = await self._query(
            "SELECT * FROM minecraft_runtime WHERE guild_id = ? LIMIT 1",
            (int(guild_id),),
        )
        return _normalize_runtime(rows[0]) if rows else None

    async def get_server_with_runtime(self, guild_id: int) -> dict[str, Any] | None:
        server = await self.get_server(guild_id)
        if server is None:
            return None
        runtime = await self.get_runtime(guild_id)
        if runtime:
            server.update(runtime)
        return server

    async def upsert_server(
        self,
        guild_id: int,
        *,
        display_name: str,
        host: str,
        java_port: int,
        bedrock_port: int,
    ) -> dict[str, Any]:
        guild = int(guild_id)
        await self._execute(
            """INSERT INTO minecraft_servers (
                guild_id, display_name, host, java_port, bedrock_port, enabled
            ) VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET
                display_name = excluded.display_name,
                host = excluded.host,
                java_port = excluded.java_port,
                bedrock_port = excluded.bedrock_port,
                enabled = 1,
                updated_at = CURRENT_TIMESTAMP""",
            (guild, display_name[:100], host, int(java_port), int(bedrock_port)),
        )
        row = await self.get_server(guild)
        if row is None:
            raise MinecraftStoreRequestError("Minecraft server configuration was not saved")
        return row

    async def list_players(self, guild_id: int, *, online_only=False, limit=500):
        limit = max(1, min(int(limit), MAX_PLAYER_QUERY))
        sql = "SELECT * FROM minecraft_players WHERE guild_id = ?"
        args: list[Any] = [int(guild_id)]
        if online_only:
            sql += " AND online = 1"
        sql += " ORDER BY username COLLATE NOCASE LIMIT ?"
        args.append(limit)
        return [_normalize_player(row) for row in await self._query(sql, args)]

    async def get_player_by_name(self, guild_id: int, username: str):
        clean = str(username or "").strip()
        if not clean:
            return None
        rows = await self._query(
            """SELECT * FROM minecraft_players
            WHERE guild_id = ? AND username = ? COLLATE NOCASE
            ORDER BY last_seen DESC LIMIT 1""",
            (int(guild_id), clean),
        )
        return _normalize_player(rows[0]) if rows else None

    async def get_player_by_discord(self, guild_id: int, discord_user_id: int):
        args = (int(guild_id), int(discord_user_id))
        rows = await self._query(
            """SELECT * FROM minecraft_players
            WHERE guild_id = ? AND discord_user_id = ?
            ORDER BY last_seen DESC LIMIT 1""",
            args,
        )
        if rows:
            return _normalize_player(rows[0])
        rows = await self._query(
            """SELECT p.* FROM minecraft_links AS l
            JOIN minecraft_players AS p
              ON p.guild_id = l.guild_id AND p.player_uuid = l.player_uuid
            WHERE l.guild_id = ? AND l.discord_user_id = ?
            ORDER BY p.last_seen DESC LIMIT 1""",
            args,
        )
        return _normalize_player(rows[0]) if rows else None

    async def recent_activity(self, guild_id: int, *, limit=12):
        limit = max(1, min(int(limit), MAX_ACTIVITY_QUERY))
        return await self._query(
            """SELECT * FROM minecraft_activity
            WHERE guild_id = ? ORDER BY occurred_at DESC, id DESC LIMIT ?""",
            (int(guild_id), limit),
        )

    async def leaderboard_rows(self, guild_id: int):
        return await self.list_players(guild_id, limit=MAX_PLAYER_QUERY)

    async def link_player(self, guild_id: int, *, discord_user_id: int, player_uuid: str):
        rows = await self._query(
            "SELECT username, platform, xuid FROM minecraft_players WHERE guild_id = ? AND player_uuid = ? LIMIT 1",
            (int(guild_id), str(player_uuid)),
        )
        if not rows:
            raise MinecraftStoreRequestError("Minecraft player does not exist")
        player = rows[0]
        await self._pipeline([
            _statement("BEGIN"),
            _statement(
                """INSERT INTO minecraft_links (
                    guild_id, discord_user_id, player_uuid, username, platform, xuid
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_user_id, player_uuid) DO UPDATE SET
                    username = excluded.username,
                    platform = excluded.platform,
                    xuid = excluded.xuid,
                    linked_at = CURRENT_TIMESTAMP""",
                (
                    int(guild_id), int(discord_user_id), str(player_uuid),
                    player.get("username"), player.get("platform") or "java", player.get("xuid"),
                ),
            ),
            _statement(
                "UPDATE minecraft_players SET discord_user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND player_uuid = ?",
                (int(discord_user_id), int(guild_id), str(player_uuid)),
            ),
            _statement("COMMIT"),
        ])


def aura_total_level(row: dict[str, Any]) -> int:
    skills = row.get("aura_skills") if isinstance(row.get("aura_skills"), dict) else {}
    return sum(
        max(0, int(value.get("level") or 0))
        for value in skills.values()
        if isinstance(value, dict)
    )


def metric_value(row: dict[str, Any], metric: str) -> int:
    metric = str(metric or "playtime").lower()
    if metric == "playtime":
        return max(0, int(row.get("playtime_ticks") or 0))
    if metric == "aura":
        return aura_total_level(row)
    key = {
        "kills": "player_kills",
        "mobs": "mob_kills",
        "deaths": "deaths",
        "jumps": "jumps",
    }.get(metric)
    if key is None:
        raise ValueError("metric must be playtime, kills, mobs, deaths, jumps, or aura")
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    return max(0, int(stats.get(key) or 0))


def sort_player_rows(rows: list[dict[str, Any]], metric: str):
    ranked = [(row, metric_value(row, metric)) for row in rows]
    ranked.sort(key=lambda item: (-item[1], str(item[0].get("username") or "").lower()))
    return ranked
