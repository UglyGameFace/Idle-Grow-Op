import asyncio
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from persistence_scope import (
    GLOBAL_ACCOUNT_PREFIX,
    GUILD_PROFILE_PREFIX,
    GUILD_WORLD_PREFIX,
    RecordKey,
)


class SupabaseScopedBackend:
    """Persist scoped records in the normalized Supabase tables."""

    def __init__(self, client):
        if client is None:
            raise ValueError("Supabase client is required")
        self.client = client

    async def load(self, key: RecordKey) -> Mapping[str, Any] | None:
        return await asyncio.to_thread(self._load_sync, key)

    def _load_sync(self, key: RecordKey) -> Mapping[str, Any] | None:
        table_name, filters = self._table_and_filters(key)
        query = self.client.table(table_name).select("data")
        for column, value in filters.items():
            query = query.eq(column, value)
        response = query.limit(1).execute()
        if not response.data:
            return None
        return dict(response.data[0].get("data") or {})

    async def save_many(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        if not records:
            return
        await asyncio.to_thread(self._save_many_sync, records)

    def _save_many_sync(self, records: Mapping[RecordKey, Mapping[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for key, data in records.items():
            table_name, filters = self._table_and_filters(key)
            grouped[table_name].append({**filters, "data": dict(data)})

        for table_name, payload in grouped.items():
            self.client.table(table_name).upsert(payload).execute()

    @staticmethod
    def _table_and_filters(key: RecordKey) -> tuple[str, dict[str, int]]:
        if key.kind == GLOBAL_ACCOUNT_PREFIX and key.user_id:
            return "global_accounts", {"user_id": int(key.user_id)}
        if key.kind == GUILD_PROFILE_PREFIX and key.guild_id and key.user_id:
            return "guild_profiles", {
                "guild_id": int(key.guild_id),
                "user_id": int(key.user_id),
            }
        if key.kind == GUILD_WORLD_PREFIX and key.guild_id:
            return "guild_worlds", {"guild_id": int(key.guild_id)}
        raise ValueError("unsupported or incomplete record key")
