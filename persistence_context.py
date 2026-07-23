from typing import Any


class GuildContextRequired(RuntimeError):
    """Raised when guild-scoped game state is requested outside a guild."""


def require_guild_id(context: Any) -> int:
    guild = getattr(context, "guild", None)
    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        raise GuildContextRequired("Idle Grow game commands can only be used inside a server")

    try:
        resolved = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise GuildContextRequired("Discord guild context is invalid") from exc
    if resolved <= 0:
        raise GuildContextRequired("Discord guild context is invalid")
    return resolved


async def get_context_profile(database, context: Any, user_id: Any | None = None):
    guild_id = require_guild_id(context)
    resolved_user_id = user_id
    if resolved_user_id is None:
        author = getattr(context, "author", None)
        resolved_user_id = getattr(author, "id", None)
    if resolved_user_id is None:
        raise ValueError("user_id is required when context has no author")
    return await database.get_profile(guild_id, resolved_user_id)


async def get_context_world(database, context: Any):
    return await database.get_world(require_guild_id(context))


def mark_context_profile_dirty(database, context: Any, user_id: Any | None = None) -> None:
    guild_id = require_guild_id(context)
    resolved_user_id = user_id
    if resolved_user_id is None:
        author = getattr(context, "author", None)
        resolved_user_id = getattr(author, "id", None)
    if resolved_user_id is None:
        raise ValueError("user_id is required when context has no author")
    database.mark_profile_dirty(guild_id, resolved_user_id)


def mark_context_world_dirty(database, context: Any) -> None:
    database.mark_world_dirty(require_guild_id(context))
