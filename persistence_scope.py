from dataclasses import dataclass
from typing import Any


GLOBAL_ACCOUNT_PREFIX = "account"
GUILD_PROFILE_PREFIX = "profile"
GUILD_WORLD_PREFIX = "world"


def _snowflake(value: Any, *, field: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a Discord snowflake")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a Discord snowflake") from exc
    if number <= 0:
        raise ValueError(f"{field} must be a positive Discord snowflake")
    return str(number)


@dataclass(frozen=True, slots=True)
class RecordKey:
    kind: str
    guild_id: str | None = None
    user_id: str | None = None

    @property
    def cache_key(self) -> str:
        if self.kind == GLOBAL_ACCOUNT_PREFIX and self.user_id:
            return f"{GLOBAL_ACCOUNT_PREFIX}:{self.user_id}"
        if self.kind == GUILD_PROFILE_PREFIX and self.guild_id and self.user_id:
            return f"{GUILD_PROFILE_PREFIX}:{self.guild_id}:{self.user_id}"
        if self.kind == GUILD_WORLD_PREFIX and self.guild_id:
            return f"{GUILD_WORLD_PREFIX}:{self.guild_id}"
        raise ValueError("record key is incomplete")


def global_account_key(user_id: Any) -> RecordKey:
    return RecordKey(kind=GLOBAL_ACCOUNT_PREFIX, user_id=_snowflake(user_id, field="user_id"))


def guild_profile_key(guild_id: Any, user_id: Any) -> RecordKey:
    return RecordKey(
        kind=GUILD_PROFILE_PREFIX,
        guild_id=_snowflake(guild_id, field="guild_id"),
        user_id=_snowflake(user_id, field="user_id"),
    )


def guild_world_key(guild_id: Any) -> RecordKey:
    return RecordKey(kind=GUILD_WORLD_PREFIX, guild_id=_snowflake(guild_id, field="guild_id"))


def parse_cache_key(value: str) -> RecordKey:
    parts = str(value).split(":")
    if len(parts) == 2 and parts[0] == GLOBAL_ACCOUNT_PREFIX:
        return global_account_key(parts[1])
    if len(parts) == 3 and parts[0] == GUILD_PROFILE_PREFIX:
        return guild_profile_key(parts[1], parts[2])
    if len(parts) == 2 and parts[0] == GUILD_WORLD_PREFIX:
        return guild_world_key(parts[1])
    raise ValueError("invalid persistence cache key")
