from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


MINECRAFT_TURSO_DATABASE_URL_ENV = "MINECRAFT_TURSO_DATABASE_URL"
MINECRAFT_TURSO_AUTH_TOKEN_ENV = "MINECRAFT_TURSO_AUTH_TOKEN"
MINECRAFT_SCHEMA_VERSION = "001_minecraft_companion"
MAX_PLAYER_QUERY = 500
MAX_ACTIVITY_QUERY = 50


class MinecraftStoreError(RuntimeError):
    """Base error for Minecraft companion persistence."""


class MinecraftStoreNotConfigured(MinecraftStoreError):
    """Raised when the dedicated Turso credentials are missing."""


class MinecraftSchemaError(MinecraftStoreError):
    """Raised when the Minecraft companion schema cannot be prepared."""


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
        if not url.startswith(("libsql://", "https://")):
            raise MinecraftStoreNotConfigured(
                f"{MINECRAFT_TURSO_DATABASE_URL_ENV} must be a Turso libsql:// or https:// URL"
            )
        return cls(database_url=url, auth_token=token)


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS minecraft_schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS minecraft_servers (
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS minecraft_players (
        guild_id INTEGER NOT NULL,
        player_uuid TEXT NOT NULL,
        username TEXT NOT NULL,
        edition TEXT NOT NULL DEFAULT 'java',
        xuid TEXT,
        discord_user_id INTEGER,
        online INTEGER NOT NULL DEFAULT 0,
        first_seen TEXT,
        last_seen TEXT,
        last_joined TEXT,
        last_left TEXT,
        playtime_ticks INTEGER NOT NULL DEFAULT 0,
        stats_json TEXT NOT NULL DEFAULT '{}',
        aura_skills_json TEXT NOT NULL DEFAULT '{}',
        last_world TEXT,
        last_x REAL,
        last_y REAL,
        last_z REAL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, player_uuid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_players_name
    ON minecraft_players (guild_id, username COLLATE NOCASE)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_players_discord
    ON minecraft_players (guild_id, discord_user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_players_online
    ON minecraft_players (guild_id, online)
    """,
    """
    CREATE TABLE IF NOT EXISTS minecraft_links (
        guild_id INTEGER NOT NULL,
        discord_user_id INTEGER NOT NULL,
        player_uuid TEXT NOT NULL,
        username TEXT NOT NULL,
        edition TEXT NOT NULL DEFAULT 'java',
        xuid TEXT,
        linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, discord_user_id, player_uuid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_links_player
    ON minecraft_links (guild_id, player_uuid)
    """,
    """
    CREATE TABLE IF NOT EXISTS minecraft_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        player_uuid TEXT,
        username TEXT,
        event_type TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_activity_recent
    ON minecraft_activity (guild_id, occurred_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS minecraft_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        sampled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        online_count INTEGER NOT NULL DEFAULT 0,
        max_players INTEGER NOT NULL DEFAULT 0,
        tps_1m REAL,
        tps_5m REAL,
        tps_15m REAL,
        mspt_avg REAL,
        memory_used_mb REAL,
        memory_max_mb REAL,
        bedrock_online INTEGER,
        paper_version TEXT,
        geyser_version TEXT,
        bridge_version TEXT,
        extra_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_minecraft_health_recent
    ON minecraft_health (guild_id, sampled_at DESC)
    """,
)


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _rows_from_cursor(cursor) -> list[dict[str, Any]]:
    description = getattr(cursor, "description", None) or []
    names = [str(column[0]) for column in description]
    rows = cursor.fetchall()
    if not names:
        return []
    output = []
    for row in rows:
        if hasattr(row, "keys"):
            output.append({name: row[name] for name in names})
        else:
            output.append(dict(zip(names, row)))
    return output


def _normalize_player(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["online"] = bool(normalized.get("online"))
    normalized["stats"] = _decode_json(normalized.pop("stats_json", "{}"))
    normalized["aura_skills"] = _decode_json(normalized.pop("aura_skills_json", "{}"))
    return normalized


def _normalize_activity(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["detail"] = _decode_json(normalized.pop("detail_json", "{}"))
    return normalized


def _normalize_health(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["extra"] = _decode_json(normalized.pop("extra_json", "{}"))
    return normalized


class MinecraftTursoStore:
    """Dedicated Turso storage for The Plug's Minecraft companion data.

    The existing Idle Grow Supabase database remains completely separate. This
    store opens short-lived Turso Cloud connections for commands and bridge
    updates, keeping blocking driver work off the Discord event loop.
    """

    def __init__(
        self,
        config: TursoConfig | None,
        *,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self._connect_factory = connect_factory
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "MinecraftTursoStore":
        return cls(TursoConfig.from_env())

    @property
    def configured(self) -> bool:
        return self.config is not None or self._connect_factory is not None

    def _connect(self):
        if self._connect_factory is not None:
            return self._connect_factory()
        if self.config is None:
            raise MinecraftStoreNotConfigured(
                "Minecraft Turso storage is not configured on the bot host"
            )
        try:
            import libsql
        except ImportError as exc:
            raise MinecraftStoreNotConfigured(
                "The libsql package is missing from the bot environment"
            ) from exc
        return libsql.connect(
            database=self.config.database_url,
            auth_token=self.config.auth_token,
        )

    async def _run(self, operation: Callable[[Any], Any]):
        if not self.configured:
            raise MinecraftStoreNotConfigured(
                "Minecraft Turso storage is not configured on the bot host"
            )

        def invoke():
            connection = self._connect()
            try:
                return operation(connection)
            finally:
                close = getattr(connection, "close", None)
                if callable(close):
                    close()

        return await asyncio.to_thread(invoke)

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return

            def migrate(connection):
                try:
                    for statement in SCHEMA_STATEMENTS:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO minecraft_schema_migrations (version) VALUES (?)",
                        (MINECRAFT_SCHEMA_VERSION,),
                    )
                    connection.commit()
                except Exception as exc:
                    raise MinecraftSchemaError(
                        "Could not prepare the Minecraft companion Turso schema"
                    ) from exc

            await self._run(migrate)
            self._schema_ready = True

    async def _ready(self) -> None:
        await self.ensure_schema()

    async def get_server(self, guild_id: int) -> dict[str, Any] | None:
        await self._ready()
        guild_id = int(guild_id)

        def query(connection):
            cursor = connection.execute(
                "SELECT * FROM minecraft_servers WHERE guild_id = ? LIMIT 1",
                (guild_id,),
            )
            rows = _rows_from_cursor(cursor)
            return rows[0] if rows else None

        return await self._run(query)

    async def upsert_server(
        self,
        guild_id: int,
        *,
        display_name: str,
        host: str,
        java_port: int,
        bedrock_port: int,
    ) -> dict[str, Any]:
        await self._ready()
        payload = (
            int(guild_id),
            str(display_name).strip()[:100],
            str(host).strip(),
            int(java_port),
            int(bedrock_port),
        )

        def write(connection):
            connection.execute(
                """
                INSERT INTO minecraft_servers (
                    guild_id, display_name, host, java_port, bedrock_port, enabled
                ) VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(guild_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    host = excluded.host,
                    java_port = excluded.java_port,
                    bedrock_port = excluded.bedrock_port,
                    enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                payload,
            )
            connection.commit()
            cursor = connection.execute(
                "SELECT * FROM minecraft_servers WHERE guild_id = ? LIMIT 1",
                (payload[0],),
            )
            rows = _rows_from_cursor(cursor)
            return rows[0]

        return await self._run(write)

    async def update_server_channels(
        self,
        guild_id: int,
        *,
        chat_channel_id: int | None = None,
        log_channel_id: int | None = None,
        proximity_lobby_id: int | None = None,
        linked_role_id: int | None = None,
    ) -> None:
        await self._ready()
        values = (
            chat_channel_id,
            log_channel_id,
            proximity_lobby_id,
            linked_role_id,
            int(guild_id),
        )

        def write(connection):
            connection.execute(
                """
                UPDATE minecraft_servers
                SET chat_channel_id = ?,
                    log_channel_id = ?,
                    proximity_lobby_id = ?,
                    linked_role_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                values,
            )
            connection.commit()

        await self._run(write)

    async def list_players(
        self,
        guild_id: int,
        *,
        online_only: bool = False,
        limit: int = MAX_PLAYER_QUERY,
    ) -> list[dict[str, Any]]:
        await self._ready()
        guild_id = int(guild_id)
        limit = max(1, min(int(limit), MAX_PLAYER_QUERY))

        def query(connection):
            sql = "SELECT * FROM minecraft_players WHERE guild_id = ?"
            params: list[Any] = [guild_id]
            if online_only:
                sql += " AND online = 1"
            sql += " ORDER BY username COLLATE NOCASE LIMIT ?"
            params.append(limit)
            return [
                _normalize_player(row)
                for row in _rows_from_cursor(connection.execute(sql, tuple(params)))
            ]

        return await self._run(query)

    async def get_player_by_name(
        self,
        guild_id: int,
        username: str,
    ) -> dict[str, Any] | None:
        await self._ready()
        clean = str(username).strip()
        if not clean:
            return None

        def query(connection):
            cursor = connection.execute(
                """
                SELECT * FROM minecraft_players
                WHERE guild_id = ? AND username = ? COLLATE NOCASE
                ORDER BY last_seen DESC LIMIT 1
                """,
                (int(guild_id), clean),
            )
            rows = _rows_from_cursor(cursor)
            return _normalize_player(rows[0]) if rows else None

        return await self._run(query)

    async def get_player_by_discord(
        self,
        guild_id: int,
        discord_user_id: int,
    ) -> dict[str, Any] | None:
        await self._ready()

        def query(connection):
            cursor = connection.execute(
                """
                SELECT p.*
                FROM minecraft_links AS l
                JOIN minecraft_players AS p
                  ON p.guild_id = l.guild_id AND p.player_uuid = l.player_uuid
                WHERE l.guild_id = ? AND l.discord_user_id = ?
                ORDER BY p.last_seen DESC LIMIT 1
                """,
                (int(guild_id), int(discord_user_id)),
            )
            rows = _rows_from_cursor(cursor)
            return _normalize_player(rows[0]) if rows else None

        return await self._run(query)

    async def recent_activity(
        self,
        guild_id: int,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        await self._ready()
        limit = max(1, min(int(limit), MAX_ACTIVITY_QUERY))

        def query(connection):
            cursor = connection.execute(
                """
                SELECT * FROM minecraft_activity
                WHERE guild_id = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (int(guild_id), limit),
            )
            return [_normalize_activity(row) for row in _rows_from_cursor(cursor)]

        return await self._run(query)

    async def latest_health(self, guild_id: int) -> dict[str, Any] | None:
        await self._ready()

        def query(connection):
            cursor = connection.execute(
                """
                SELECT * FROM minecraft_health
                WHERE guild_id = ?
                ORDER BY sampled_at DESC, id DESC
                LIMIT 1
                """,
                (int(guild_id),),
            )
            rows = _rows_from_cursor(cursor)
            return _normalize_health(rows[0]) if rows else None

        return await self._run(query)

    async def leaderboard_rows(self, guild_id: int) -> list[dict[str, Any]]:
        return await self.list_players(guild_id, online_only=False, limit=MAX_PLAYER_QUERY)

    async def upsert_player_snapshot(self, guild_id: int, snapshot: dict[str, Any]) -> None:
        """Canonical write path for the future Paper bridge ingestion layer."""
        await self._ready()
        player_uuid = str(snapshot.get("player_uuid") or "").strip()
        username = str(snapshot.get("username") or "").strip()
        if not player_uuid or not username:
            raise ValueError("player_uuid and username are required")
        stats = snapshot.get("stats") if isinstance(snapshot.get("stats"), dict) else {}
        aura = (
            snapshot.get("aura_skills")
            if isinstance(snapshot.get("aura_skills"), dict)
            else {}
        )
        values = (
            int(guild_id),
            player_uuid,
            username[:64],
            str(snapshot.get("edition") or "java")[:16],
            str(snapshot.get("xuid") or "") or None,
            int(bool(snapshot.get("online"))),
            snapshot.get("first_seen"),
            snapshot.get("last_seen"),
            snapshot.get("last_joined"),
            snapshot.get("last_left"),
            max(0, int(snapshot.get("playtime_ticks") or 0)),
            json.dumps(stats, separators=(",", ":"), sort_keys=True),
            json.dumps(aura, separators=(",", ":"), sort_keys=True),
            snapshot.get("last_world"),
            snapshot.get("last_x"),
            snapshot.get("last_y"),
            snapshot.get("last_z"),
        )

        def write(connection):
            connection.execute(
                """
                INSERT INTO minecraft_players (
                    guild_id, player_uuid, username, edition, xuid, online,
                    first_seen, last_seen, last_joined, last_left, playtime_ticks,
                    stats_json, aura_skills_json, last_world, last_x, last_y, last_z
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, player_uuid) DO UPDATE SET
                    username = excluded.username,
                    edition = excluded.edition,
                    xuid = COALESCE(excluded.xuid, minecraft_players.xuid),
                    online = excluded.online,
                    first_seen = COALESCE(minecraft_players.first_seen, excluded.first_seen),
                    last_seen = COALESCE(excluded.last_seen, minecraft_players.last_seen),
                    last_joined = COALESCE(excluded.last_joined, minecraft_players.last_joined),
                    last_left = COALESCE(excluded.last_left, minecraft_players.last_left),
                    playtime_ticks = excluded.playtime_ticks,
                    stats_json = excluded.stats_json,
                    aura_skills_json = excluded.aura_skills_json,
                    last_world = excluded.last_world,
                    last_x = excluded.last_x,
                    last_y = excluded.last_y,
                    last_z = excluded.last_z,
                    updated_at = CURRENT_TIMESTAMP
                """,
                values,
            )
            connection.commit()

        await self._run(write)

    async def append_activity(
        self,
        guild_id: int,
        *,
        event_type: str,
        player_uuid: str | None = None,
        username: str | None = None,
        detail: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> None:
        await self._ready()
        values = (
            int(guild_id),
            player_uuid,
            username,
            str(event_type).strip()[:64],
            json.dumps(detail or {}, separators=(",", ":"), sort_keys=True),
            occurred_at,
        )

        def write(connection):
            connection.execute(
                """
                INSERT INTO minecraft_activity (
                    guild_id, player_uuid, username, event_type, detail_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                values,
            )
            connection.commit()

        await self._run(write)

    async def write_health(self, guild_id: int, snapshot: dict[str, Any]) -> None:
        await self._ready()
        values = (
            int(guild_id),
            snapshot.get("sampled_at"),
            max(0, int(snapshot.get("online_count") or 0)),
            max(0, int(snapshot.get("max_players") or 0)),
            snapshot.get("tps_1m"),
            snapshot.get("tps_5m"),
            snapshot.get("tps_15m"),
            snapshot.get("mspt_avg"),
            snapshot.get("memory_used_mb"),
            snapshot.get("memory_max_mb"),
            snapshot.get("bedrock_online"),
            snapshot.get("paper_version"),
            snapshot.get("geyser_version"),
            snapshot.get("bridge_version"),
            json.dumps(snapshot.get("extra") or {}, separators=(",", ":"), sort_keys=True),
        )

        def write(connection):
            connection.execute(
                """
                INSERT INTO minecraft_health (
                    guild_id, sampled_at, online_count, max_players,
                    tps_1m, tps_5m, tps_15m, mspt_avg,
                    memory_used_mb, memory_max_mb, bedrock_online,
                    paper_version, geyser_version, bridge_version, extra_json
                ) VALUES (?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()

        await self._run(write)

    async def link_player(
        self,
        guild_id: int,
        *,
        discord_user_id: int,
        player_uuid: str,
    ) -> None:
        await self._ready()

        def write(connection):
            cursor = connection.execute(
                """
                SELECT username, edition, xuid FROM minecraft_players
                WHERE guild_id = ? AND player_uuid = ? LIMIT 1
                """,
                (int(guild_id), str(player_uuid)),
            )
            rows = _rows_from_cursor(cursor)
            if not rows:
                raise ValueError("Minecraft player does not exist")
            player = rows[0]
            connection.execute(
                """
                INSERT INTO minecraft_links (
                    guild_id, discord_user_id, player_uuid, username, edition, xuid
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_user_id, player_uuid) DO UPDATE SET
                    username = excluded.username,
                    edition = excluded.edition,
                    xuid = excluded.xuid,
                    linked_at = CURRENT_TIMESTAMP
                """,
                (
                    int(guild_id),
                    int(discord_user_id),
                    str(player_uuid),
                    player.get("username"),
                    player.get("edition") or "java",
                    player.get("xuid"),
                ),
            )
            connection.execute(
                """
                UPDATE minecraft_players
                SET discord_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND player_uuid = ?
                """,
                (int(discord_user_id), int(guild_id), str(player_uuid)),
            )
            connection.commit()

        await self._run(write)


def sort_player_rows(
    rows: Iterable[dict[str, Any]],
    metric: str,
) -> list[tuple[dict[str, Any], int]]:
    key = str(metric or "playtime").strip().lower()
    aliases = {
        "playtime": "playtime_ticks",
        "kills": "player_kills",
        "mobs": "mob_kills",
        "deaths": "deaths",
        "jumps": "jumps",
        "aura": "aura_total_level",
    }
    if key not in aliases:
        raise ValueError("metric must be playtime, kills, mobs, deaths, jumps, or aura")

    field = aliases[key]

    def value(row: dict[str, Any]) -> int:
        if field == "playtime_ticks":
            return max(0, int(row.get("playtime_ticks") or 0))
        if field == "aura_total_level":
            skills = row.get("aura_skills") if isinstance(row.get("aura_skills"), dict) else {}
            total = 0
            for skill in skills.values():
                if isinstance(skill, dict):
                    total += max(0, int(skill.get("level") or 0))
            return total
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        return max(0, int(stats.get(field) or 0))

    ranked = [(row, value(row)) for row in rows]
    ranked.sort(key=lambda item: (-item[1], str(item[0].get("username") or "").lower()))
    return ranked
