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

