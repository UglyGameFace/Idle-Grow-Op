"""Shared error handling for private player-facing Discord UI panels.

Component exceptions that escape callbacks do not go through on_command_error.
Always keep local traceback details and acknowledge the player promptly,
then attempt the configured guild reporter without delaying the acknowledgement.
"""

from __future__ import annotations

import logging

import discord


logger = logging.getLogger(__name__)


async def report_player_ui_error(
    bot,
    interaction: discord.Interaction,
    error: Exception,
    item: discord.ui.Item,
    *,
    surface: str,
) -> None:
    guild_id = getattr(interaction, "guild_id", None)
    user_id = getattr(getattr(interaction, "user", None), "id", None)
    control = str(
        getattr(item, "label", None)
        or getattr(item, "custom_id", None)
        or type(item).__name__
    )[:80]

    # on_error runs outside an exception handler, so pass the original traceback
    # explicitly rather than relying on the ambient sys.exc_info().
    logger.error(
        "Player UI callback failed surface=%s control=%s guild=%s user=%s",
        surface,
        control,
        guild_id,
        user_id,
        exc_info=(type(error), error, error.__traceback__),
    )

    message = "❌ This panel action failed. Please try again or reopen the panel."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        # The interaction token may already have expired or the message may
        # have been deleted. The original failure is logged above regardless.
        logger.warning(
            "Could not send player UI error feedback surface=%s guild=%s user=%s",
            surface,
            guild_id,
            user_id,
            exc_info=True,
        )

    reporter = getattr(bot, "report_command_error", None)
    if callable(reporter):
        try:
            await reporter(
                guild_id=guild_id,
                title=f"{surface} interaction failure",
                description=(
                    f"surface={surface} control={control} guild={guild_id} "
                    f"user={user_id} error_type={type(error).__name__}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to deliver player UI error report surface=%s guild=%s user=%s",
                surface,
                guild_id,
                user_id,
            )

