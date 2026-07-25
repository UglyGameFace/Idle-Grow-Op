from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id
from world_modes import mark_game_profile_dirty, resolve_game_scope


logger = logging.getLogger(__name__)

SESSION_TYPES = {
    "SESH": ("🌿 Smoke Sesh", 0x2ECC71, "weed smoke sesh stoner rotation"),
    "MOVIE": ("🎬 Movie Night", 0x3498DB, "movie night popcorn watching film"),
    "KARAOKE": ("🎤 Karaoke Sesh", 0x9B59B6, "karaoke singing microphone party"),
}
WORD_RE = re.compile(r"[a-z0-9']+")

EMPTY_TIMEOUT_SECONDS = 600
PRIVATE_TTL_SECONDS = 900
PING_COOLDOWN_SECONDS = 600
UPDATE_INTERVAL_SECONDS = 20
XP_INTERVAL_SECONDS = 60
XP_MIN_HUMANS = 2
SESH_XP_MAX_PER_USER = 160
SESH_XP_MAX_PER_INTERVAL = 8
STREAK_MILESTONES = (10, 20, 30, 45, 60)
STREAK_BONUSES = (10, 14, 18, 25, 35)
ROTATION_BONUS_COOLDOWN_SECONDS = 120
ROTATION_BONUS_MAX_PER_SESSION = 6
VOICE_GRACE_SECONDS = 90
MEDIA_MIN_SCORE = 8

SESH_ENABLED_KEY = "enabled"
ALLOW_ALL_VOICE_ROOMS_KEY = "allow_all_voice_rooms"
VOICE_CHANNELS_KEY = "voice_channels"
PING_ROLE_ID_KEY = "ping_role_id"
PRIVATE_CATEGORY_ID_KEY = "private_category_id"
TEMP_CHANNEL_MARKER = "idle-grow-temp-sesh"


def _tokens(text: str | None) -> set[str]:
    return set(WORD_RE.findall((text or "").lower()))


def build_media_query(session_type: str, keywords: str | None) -> str:
    return f"{SESSION_TYPES[session_type][2]} {' '.join(sorted(_tokens(keywords)))}".strip()


def _media_score(session_type: str, keywords: str | None, result: dict[str, Any]) -> int:
    hay = _tokens(
        f"{result.get('content_description', '')} {' '.join(result.get('tags') or [])}"
    )
    return (
        3 * len(_tokens(SESSION_TYPES[session_type][2]) & hay)
        + 7 * len(_tokens(keywords) & hay)
    )


async def fetch_relevant_media(session_type: str, keywords: str | None) -> str | None:
    key = os.getenv("TENOR_API_KEY", "").strip()
    if not key:
        return None

    params = {
        "q": build_media_query(session_type, keywords),
        "key": key,
        "client_key": "idle_grow_op",
        "limit": 12,
        "media_filter": "gif,tinygif",
        "contentfilter": "medium",
        "random": "false",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(
                "https://tenor.googleapis.com/v2/search",
                params=params,
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None

    scored: list[tuple[int, str]] = []
    for result in payload.get("results", []):
        formats = result.get("media_formats") or {}
        media = formats.get("gif") or formats.get("tinygif") or {}
        if media.get("url"):
            scored.append((_media_score(session_type, keywords, result), media["url"]))

    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0] >= MEDIA_MIN_SCORE else None


def curated_media(session_type: str, keywords: str | None) -> str | None:
    # A wrong GIF is worse than no GIF; specific keywords require a verified match.
    return None


def _voice_like(ch: Any) -> bool:
    channel_types = tuple(
        channel_type
        for channel_type in (
            discord.VoiceChannel,
            getattr(discord, "StageChannel", None),
        )
        if channel_type
    )
    return isinstance(ch, channel_types)


def _humans(ch: Any) -> list[discord.Member]:
    return [m for m in getattr(ch, "members", []) if not m.bot]


@dataclass
class ParticipantState:
    joined_at: float
    last_seen: float
    left_at: float | None = None
    total_awarded: int = 0
    streak_awarded: set[int] = field(default_factory=set)
    rotation_awarded: int = 0
    last_rotation_at: float = 0.0


@dataclass
class SeshSession:
    guild_id: int
    voice_channel_id: int
    text_channel_id: int
    message_id: int
    host_id: int
    session_type: str
    note: str | None
    media_url: str | None
    started_at: float
    empty_since: float | None = None
    participants: dict[int, ParticipantState] = field(default_factory=dict)
    task: asyncio.Task | None = None
    temporary_voice_channel_id: int | None = None
    temporary_expires_at: float | None = None
    active: bool = True
    last_xp_award_at: float = 0.0


class SeshView(discord.ui.View):
    def __init__(self, cog: "Sesh", session_key: tuple[int, int]) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.session_key = session_key

    @discord.ui.button(
        label="Puff & Pass",
        emoji="🔥",
        style=discord.ButtonStyle.success,
    )
    async def puff_pass(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.cog.handle_puff_pass(interaction, self.session_key)

    @discord.ui.button(
        label="End Sesh",
        emoji="🛑",
        style=discord.ButtonStyle.danger,
    )
    async def end_session(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if not await self.cog.can_manage_session(interaction.user, self.session_key):
            await interaction.response.send_message(
                "❌ Host, active successor, or moderator only.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog._end_sesh_session(self.session_key, reason="manual")
        await interaction.followup.send(
            "🛑 Sesh ended and cleaned up.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Private Room",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
    )
    async def private_room(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.cog.create_private_room(interaction, self.session_key)


class Sesh(commands.Cog):
    """Optional live voice sessions: one active session per voice channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sesh_sessions: dict[tuple[int, int], SeshSession] = {}
        self._ping_cooldowns: dict[tuple[int, int, str], float] = {}
        self._private_cleanup_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._reconcile_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._reconcile_task = asyncio.create_task(
            self._reconcile_stale_sessions(),
            name="sesh-reconcile",
        )

    def cog_unload(self) -> None:
        tasks = [
            self._reconcile_task,
            *[session.task for session in self._sesh_sessions.values()],
            *self._private_cleanup_tasks.values(),
        ]
        for task in tasks:
            if task and not task.done():
                task.cancel()
        self._sesh_sessions.clear()
        self._private_cleanup_tasks.clear()

    async def cog_check(self, ctx: commands.Context) -> bool:
        try:
            require_guild_id(ctx)
            return True
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False

    def _session_key(self, guild_id, voice_channel_id):
        return int(guild_id), int(voice_channel_id)

    async def _guild_config(self, guild_id: int) -> tuple[dict, dict]:
        world = await self.bot.db.get_world(guild_id)
        return world, world.setdefault("sesh_config", {})

    async def _persist_descriptor(
        self,
        session: SeshSession | None,
        key: tuple[int, int],
    ) -> None:
        world = await self.bot.db.get_world(key[0])
        active = world.setdefault("active_sesh_sessions", {})
        if session is None:
            active.pop(str(key[1]), None)
        else:
            active[str(key[1])] = {
                "voice_channel_id": key[1],
                "text_channel_id": session.text_channel_id,
                "message_id": session.message_id,
                "host_id": session.host_id,
                "session_type": session.session_type,
                "started_at": session.started_at,
                "temporary_voice_channel_id": session.temporary_voice_channel_id,
                "temporary_expires_at": session.temporary_expires_at,
            }
        self.bot.db.mark_world_dirty(key[0])

    async def _reconcile_stale_sessions(self) -> None:
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                world = await self.bot.db.get_world(guild.id)
                stale = dict(world.get("active_sesh_sessions") or {})
                tracked_temp_ids = {
                    int(item.get("temporary_voice_channel_id") or 0)
                    for item in stale.values()
                    if item.get("temporary_voice_channel_id")
                }
                for item in stale.values():
                    channel = guild.get_channel(int(item.get("text_channel_id") or 0))
                    message_id = int(item.get("message_id") or 0)
                    if channel and message_id:
                        try:
                            message = await channel.fetch_message(message_id)
                            await message.edit(
                                content="⚠️ This Sesh ended during a bot restart.",
                                view=None,
                            )
                        except (
                            discord.NotFound,
                            discord.Forbidden,
                            discord.HTTPException,
                        ):
                            pass

                    temp = guild.get_channel(
                        int(item.get("temporary_voice_channel_id") or 0)
                    )
                    if temp and _voice_like(temp):
                        await self._evacuate_and_delete_temp_channel(
                            temp,
                            reason="stale restart cleanup",
                        )

                # Also remove clearly marked orphan rooms even when a descriptor write
                # was interrupted before shutdown.
                for channel in guild.voice_channels:
                    if channel.id in tracked_temp_ids:
                        continue
                    if channel.name.startswith(TEMP_CHANNEL_MARKER):
                        await self._evacuate_and_delete_temp_channel(
                            channel,
                            reason="orphaned temporary Sesh cleanup",
                        )

                if stale:
                    world["active_sesh_sessions"] = {}
                    self.bot.db.mark_world_dirty(guild.id)
            except Exception:
                logger.exception(
                    "Sesh stale reconciliation failed for guild %s",
                    guild.id,
                )

    def _configured_voice_channel(
        self,
        ctx: commands.Context,
        config: dict,
    ) -> discord.abc.GuildChannel | None:
        current = getattr(getattr(ctx.author, "voice", None), "channel", None)
        allowed_ids = {
            int(value)
            for value in config.get(VOICE_CHANNELS_KEY, [])
            if str(value).isdigit()
        }
        allow_all = bool(config.get(ALLOW_ALL_VOICE_ROOMS_KEY, False))

        if current and _voice_like(current):
            if allow_all or current.id in allowed_ids:
                return current
            return None

        if allow_all:
            choices = list(ctx.guild.voice_channels)
        else:
            choices = [
                ctx.guild.get_channel(channel_id)
                for channel_id in allowed_ids
            ]
            choices = [channel for channel in choices if _voice_like(channel)]

        return max(choices, key=lambda c: len(_humans(c))) if choices else None

    def _embed(self, guild: discord.Guild, session: SeshSession) -> discord.Embed:
        title, color, _ = SESSION_TYPES[session.session_type]
        channel = guild.get_channel(session.voice_channel_id)
        people = _humans(channel) if channel else []
        embed = discord.Embed(
            title=title,
            description=session.note or "Pull up and grow the community together.",
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Voice Room",
            value=channel.mention if channel else "Unavailable",
            inline=False,
        )
        embed.add_field(
            name="Live Participants",
            value=", ".join(member.display_name for member in people[:12]) or "Waiting…",
            inline=False,
        )
        embed.add_field(
            name="Idle Grow Rewards",
            value=f"Presence XP begins at {XP_MIN_HUMANS}+ active people",
            inline=True,
        )
        if session.media_url:
            embed.set_image(url=session.media_url)
        embed.set_footer(
            text="Puff & Pass requires real presence in this voice room."
        )
        return embed

    async def _safe_edit_session_message(
        self,
        session: SeshSession,
        **kwargs: Any,
    ) -> bool:
        guild = self.bot.get_guild(session.guild_id)
        channel = guild.get_channel(session.text_channel_id) if guild else None
        if not channel:
            return False
        try:
            message = await channel.fetch_message(session.message_id)
            await message.edit(**kwargs)
            return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

    async def _delete_channel_with_fallback(
        self,
        channel: discord.abc.GuildChannel,
        *,
        reason: str,
    ) -> bool:
        for attempt in range(3):
            try:
                await channel.delete(reason=reason)
                return True
            except discord.NotFound:
                return True
            except (discord.Forbidden, discord.HTTPException) as exc:
                if attempt == 2:
                    logger.warning(
                        "Could not delete temporary Sesh channel %s after retries: %s",
                        channel.id,
                        exc,
                    )
                    return False
                await asyncio.sleep(2**attempt)
        return False

    async def _evacuate_and_delete_temp_channel(
        self,
        channel: discord.VoiceChannel,
        *,
        reason: str,
    ) -> bool:
        for member in list(_humans(channel)):
            try:
                await member.move_to(
                    None,
                    reason=f"{reason}; temporary Idle Grow Sesh room cleanup",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Could not disconnect member %s from temporary Sesh channel %s",
                    member.id,
                    channel.id,
                )
        return await self._delete_channel_with_fallback(channel, reason=reason)

    async def can_manage_session(
        self,
        member: discord.Member,
        key: tuple[int, int],
    ) -> bool:
        session = self._sesh_sessions.get(key)
        if not session:
            return False
        if member.id == session.host_id or member.guild_permissions.manage_channels:
            return True
        guild = self.bot.get_guild(session.guild_id)
        host = guild.get_member(session.host_id) if guild else None
        host_present = bool(
            host
            and host.voice
            and host.voice.channel
            and host.voice.channel.id == session.voice_channel_id
        )
        member_present = bool(
            member.voice
            and member.voice.channel
            and member.voice.channel.id == session.voice_channel_id
        )
        return not host_present and member_present

    async def end_guild_sessions(self, guild_id: int, *, reason: str) -> int:
        keys = [key for key in self._sesh_sessions if key[0] == int(guild_id)]
        for key in keys:
            await self._end_sesh_session(key, reason=reason)
        return len(keys)

    async def _end_sesh_session(
        self,
        key: tuple[int, int],
        *,
        reason: str,
    ) -> None:
        session = self._sesh_sessions.pop(key, None)
        if not session:
            return

        session.active = False
        cleanup = self._private_cleanup_tasks.pop(key, None)
        try:
            if (
                session.task
                and session.task is not asyncio.current_task()
                and not session.task.done()
            ):
                session.task.cancel()

            await self._persist_descriptor(None, key)
            await self._safe_edit_session_message(
                session,
                embed=discord.Embed(
                    title="🛑 Sesh Ended",
                    description=reason.replace("_", " "),
                    color=discord.Color.dark_grey(),
                ),
                view=None,
            )

            guild = self.bot.get_guild(session.guild_id)
            temp = (
                guild.get_channel(session.temporary_voice_channel_id)
                if guild and session.temporary_voice_channel_id
                else None
            )
            if isinstance(temp, discord.VoiceChannel):
                await self._evacuate_and_delete_temp_channel(
                    temp,
                    reason=f"Sesh ended: {reason}",
                )
        finally:
            if (
                cleanup
                and cleanup is not asyncio.current_task()
                and not cleanup.done()
            ):
                cleanup.cancel()

    async def _session_loop(self, key: tuple[int, int]) -> None:
        try:
            while key in self._sesh_sessions:
                await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
                session = self._sesh_sessions.get(key)
                if not session or not session.active:
                    return

                guild = self.bot.get_guild(session.guild_id)
                channel = (
                    guild.get_channel(session.voice_channel_id)
                    if guild
                    else None
                )
                if not channel or not _voice_like(channel):
                    await self._end_sesh_session(
                        key,
                        reason="voice_channel_deleted",
                    )
                    return

                people = _humans(channel)
                now = time.time()
                if people:
                    session.empty_since = None
                elif session.empty_since is None:
                    session.empty_since = now
                elif now - session.empty_since >= EMPTY_TIMEOUT_SECONDS:
                    await self._end_sesh_session(key, reason="empty_timeout")
                    return

                if (
                    session.temporary_expires_at is not None
                    and now >= session.temporary_expires_at
                ):
                    await self._end_sesh_session(
                        key,
                        reason="private_room_expired",
                    )
                    return

                if not await self._safe_edit_session_message(
                    session,
                    embed=self._embed(guild, session),
                ):
                    await self._end_sesh_session(
                        key,
                        reason="announcement_missing",
                    )
                    return

                if now - session.last_xp_award_at >= XP_INTERVAL_SECONDS:
                    await self._award_interval_xp(session, people, now)
                    session.last_xp_award_at = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sesh loop failed for %s", key)
            await self._end_sesh_session(key, reason="loop_failure")
        finally:
            if key in self._sesh_sessions and not self._sesh_sessions[key].active:
                self._sesh_sessions.pop(key, None)

    async def _award_interval_xp(
        self,
        session: SeshSession,
        people: list[discord.Member],
        now: float,
    ) -> None:
        if len(people) < XP_MIN_HUMANS:
            return

        rate = min(SESH_XP_MAX_PER_INTERVAL, 2 + len(people) - 1)
        present = {member.id for member in people}
        async with self.bot.db.lock:
            for member in people:
                state = session.participants.setdefault(
                    member.id,
                    ParticipantState(now, now),
                )
                if (
                    state.left_at
                    and now - state.left_at > VOICE_GRACE_SECONDS
                ):
                    state.joined_at = now
                    state.streak_awarded.clear()

                state.left_at = None
                state.last_seen = now
                voice = member.voice
                multiplier = (
                    0.25
                    if voice and (voice.self_deaf or voice.deaf)
                    else 0.5
                    if voice and (voice.self_mute or voice.mute)
                    else 1
                )
                scope = await resolve_game_scope(
                    self.bot.db, session.guild_id, member.id
                )
                profile = await self.bot.db.get_profile(
                    scope.scope_id,
                    member.id,
                )
                gain = min(
                    SESH_XP_MAX_PER_USER - state.total_awarded,
                    max(0, round(rate * multiplier)),
                )
                if gain:
                    profile["xp"] = int(profile.get("xp", 0)) + gain
                    social_stats = profile.setdefault("social_stats", {})
                    social_stats["sesh_xp"] = (
                        int(social_stats.get("sesh_xp", 0)) + gain
                    )
                    state.total_awarded += gain
                    mark_game_profile_dirty(self.bot.db, scope, member.id)

                minutes = int((now - state.joined_at) // 60)
                for milestone, bonus in zip(
                    STREAK_MILESTONES,
                    STREAK_BONUSES,
                ):
                    if (
                        minutes >= milestone
                        and milestone not in state.streak_awarded
                        and state.total_awarded < SESH_XP_MAX_PER_USER
                    ):
                        reward = min(
                            bonus,
                            SESH_XP_MAX_PER_USER - state.total_awarded,
                        )
                        profile["xp"] += reward
                        state.total_awarded += reward
                        state.streak_awarded.add(milestone)
                        mark_game_profile_dirty(self.bot.db, scope, member.id)

            for user_id, state in session.participants.items():
                if user_id not in present and state.left_at is None:
                    state.left_at = now

    async def handle_puff_pass(
        self,
        interaction: discord.Interaction,
        key: tuple[int, int],
    ) -> None:
        session = self._sesh_sessions.get(key)
        member = interaction.user
        if not session or not session.active:
            await interaction.response.send_message(
                "❌ This Sesh is no longer active.",
                ephemeral=True,
            )
            return
        if (
            not member.voice
            or not member.voice.channel
            or member.voice.channel.id != session.voice_channel_id
        ):
            await interaction.response.send_message(
                "❌ Join the active voice room first.",
                ephemeral=True,
            )
            return

        people = _humans(member.voice.channel)
        if len(people) < XP_MIN_HUMANS:
            await interaction.response.send_message(
                "❌ Puff & Pass needs at least two people.",
                ephemeral=True,
            )
            return

        now = time.time()
        state = session.participants.setdefault(
            member.id,
            ParticipantState(now, now),
        )
        if state.rotation_awarded >= ROTATION_BONUS_MAX_PER_SESSION:
            await interaction.response.send_message(
                "⏳ Session bonus cap reached.",
                ephemeral=True,
            )
            return
        if now - state.last_rotation_at < ROTATION_BONUS_COOLDOWN_SECONDS:
            await interaction.response.send_message(
                "⏳ Pass it around first.",
                ephemeral=True,
            )
            return

        next_member = random.choice(
            [person for person in people if person.id != member.id]
        )
        reward = min(5, SESH_XP_MAX_PER_USER - state.total_awarded)
        async with self.bot.db.lock:
            if reward:
                scope = await resolve_game_scope(
                    self.bot.db, session.guild_id, member.id
                )
                profile = await self.bot.db.get_profile(
                    scope.scope_id,
                    member.id,
                )
                profile["xp"] = int(profile.get("xp", 0)) + reward
                mark_game_profile_dirty(self.bot.db, scope, member.id)
                state.total_awarded += reward
            state.rotation_awarded += 1
            state.last_rotation_at = now

        await interaction.response.send_message(
            f"💨 **{member.display_name}** passes to "
            f"**{next_member.display_name}**! (+{reward} XP)"
        )

    async def _switch_session_voice_channel(
        self,
        old_key: tuple[int, int],
        new_channel: discord.VoiceChannel,
    ) -> tuple[int, int] | None:
        session = self._sesh_sessions.get(old_key)
        new_key = self._session_key(old_key[0], new_channel.id)
        if (
            not session
            or not _voice_like(new_channel)
            or (new_key in self._sesh_sessions and new_key != old_key)
        ):
            return None

        old_task = session.task
        self._sesh_sessions.pop(old_key)
        await self._persist_descriptor(None, old_key)
        session.voice_channel_id = new_channel.id
        session.empty_since = None
        self._sesh_sessions[new_key] = session
        await self._persist_descriptor(session, new_key)

        if (
            old_task
            and old_task is not asyncio.current_task()
            and not old_task.done()
        ):
            old_task.cancel()

        session.task = asyncio.create_task(
            self._session_loop(new_key),
            name=f"sesh-{session.guild_id}-{new_channel.id}",
        )
        await self._safe_edit_session_message(
            session,
            embed=self._embed(new_channel.guild, session),
            view=SeshView(self, new_key),
        )
        return new_key

    async def create_private_room(
        self,
        interaction: discord.Interaction,
        key: tuple[int, int],
    ) -> None:
        session = self._sesh_sessions.get(key)
        if not session:
            await interaction.response.send_message(
                "❌ This Sesh ended.",
                ephemeral=True,
            )
            return

        _, config = await self._guild_config(interaction.guild.id)
        if not bool(config.get(SESH_ENABLED_KEY, False)):
            await interaction.response.send_message(
                "❌ Optional Sesh features are disabled for this server.",
                ephemeral=True,
            )
            return

        category = interaction.guild.get_channel(
            int(config.get(PRIVATE_CATEGORY_ID_KEY) or 0)
        )
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ Configure an optional private Sesh category first.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "❌ I need **Manage Channels** to create and clean up private rooms.",
                ephemeral=True,
            )
            return

        try:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                    connect=False,
                ),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                ),
                bot_member: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                ),
            }
            channel = await interaction.guild.create_voice_channel(
                name=(
                    f"{TEMP_CHANNEL_MARKER}-{interaction.user.display_name}"
                    .lower()
                    .replace(" ", "-")[:90]
                ),
                category=category,
                overwrites=overwrites,
                reason=f"Temporary Idle Grow Sesh room for {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(
                f"❌ Could not create room: `{exc}`",
                ephemeral=True,
            )
            return

        session.temporary_voice_channel_id = channel.id
        session.temporary_expires_at = time.time() + PRIVATE_TTL_SECONDS
        new_key = await self._switch_session_voice_channel(key, channel)
        if not new_key:
            await self._delete_channel_with_fallback(
                channel,
                reason="Temporary Sesh activation failed",
            )
            await interaction.response.send_message(
                "❌ Could not activate that room.",
                ephemeral=True,
            )
            return

        task = asyncio.create_task(
            self._private_room_cleanup(
                new_key,
                channel.id,
                session.temporary_expires_at,
            ),
            name=f"sesh-private-cleanup-{interaction.guild.id}-{channel.id}",
        )
        self._private_cleanup_tasks[new_key] = task
        await interaction.response.send_message(
            f"✅ Private room created and set active: {channel.mention}",
            ephemeral=True,
        )

    async def _private_room_cleanup(
        self,
        key: tuple[int, int],
        channel_id: int,
        expires_at: float,
    ) -> None:
        try:
            delay = max(0.0, expires_at - time.time())
            await asyncio.sleep(delay)
            if key in self._sesh_sessions:
                await self._end_sesh_session(
                    key,
                    reason="private_room_expired",
                )
                return

            guild = self.bot.get_guild(key[0])
            channel = guild.get_channel(channel_id) if guild else None
            if isinstance(channel, discord.VoiceChannel):
                await self._evacuate_and_delete_temp_channel(
                    channel,
                    reason="Private Sesh expired",
                )
        except asyncio.CancelledError:
            raise
        finally:
            self._private_cleanup_tasks.pop(key, None)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        now = time.time()
        for channel in (before.channel, after.channel):
            if not channel:
                continue
            session = self._sesh_sessions.get(
                self._session_key(member.guild.id, channel.id)
            )
            if not session:
                continue
            state = session.participants.setdefault(
                member.id,
                ParticipantState(now, now),
            )
            if after.channel and after.channel.id == channel.id:
                if (
                    state.left_at
                    and now - state.left_at > VOICE_GRACE_SECONDS
                ):
                    state.joined_at = now
                    state.streak_awarded.clear()
                state.last_seen = now
                state.left_at = None
                session.empty_since = None
            elif before.channel and before.channel.id == channel.id:
                state.left_at = now
                if not _humans(channel):
                    session.empty_since = now

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        key = self._session_key(channel.guild.id, channel.id)
        if key in self._sesh_sessions:
            await self._end_sesh_session(
                key,
                reason="voice_channel_deleted",
            )
        for session_key, session in list(self._sesh_sessions.items()):
            if session.text_channel_id == channel.id:
                await self._end_sesh_session(
                    session_key,
                    reason="announcement_channel_deleted",
                )

    async def _start_session(
        self,
        ctx: commands.Context,
        session_type: str,
        note: str | None,
    ) -> None:
        guild_id = require_guild_id(ctx)
        _, config = await self._guild_config(guild_id)
        if not bool(config.get(SESH_ENABLED_KEY, False)):
            await ctx.send(
                "ℹ️ Sesh is an optional Idle Grow community feature and is "
                "disabled for this server. A server manager can enable it in `/setup`."
            )
            return

        voice = self._configured_voice_channel(ctx, config)
        if not voice:
            await ctx.send(
                "❌ Join an allowed Sesh voice room, or ask a server manager "
                "to choose specific rooms or enable **All Voice Rooms** in `/setup`."
            )
            return

        key = self._session_key(guild_id, voice.id)
        if key in self._sesh_sessions:
            await ctx.send(f"⚠️ A Sesh is already active in {voice.mention}.")
            return

        cooldown = (guild_id, voice.id, session_type)
        now = time.time()
        remaining = PING_COOLDOWN_SECONDS - (
            now - self._ping_cooldowns.get(cooldown, 0)
        )
        if remaining > 0:
            await ctx.send(f"⏳ This room can announce again in {int(remaining)}s.")
            return

        self._ping_cooldowns[cooldown] = now
        media = await fetch_relevant_media(session_type, note) or curated_media(
            session_type,
            note,
        )
        role = ctx.guild.get_role(int(config.get(PING_ROLE_ID_KEY) or 0))
        content_parts = []
        if role is not None:
            content_parts.append(role.mention)
        content_parts.append(
            f"{ctx.author.mention} started {SESSION_TYPES[session_type][0]} "
            f"in {voice.mention}!"
        )
        content = " — ".join(content_parts)

        session = SeshSession(
            guild_id,
            voice.id,
            ctx.channel.id,
            0,
            ctx.author.id,
            session_type,
            note,
            media,
            now,
        )
        view = SeshView(self, key)
        try:
            message = await ctx.send(
                content=content,
                embed=self._embed(ctx.guild, session),
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=True,
                    roles=[role] if role is not None else False,
                    replied_user=False,
                ),
            )
        except discord.Forbidden:
            await ctx.send(
                "❌ I need Send Messages and Embed Links here."
            )
            return

        session.message_id = message.id
        session.last_xp_award_at = now
        self._sesh_sessions[key] = session
        await self._persist_descriptor(session, key)
        session.task = asyncio.create_task(
            self._session_loop(key),
            name=f"sesh-{guild_id}-{voice.id}",
        )

    @commands.hybrid_command(
        name="sesh",
        aliases=["cheers", "smoke", "blaze"],
    )
    async def sesh(
        self,
        ctx: commands.Context,
        *,
        note: str | None = None,
    ) -> None:
        await self._start_session(ctx, "SESH", note)

    @commands.hybrid_command(name="movie")
    async def movie(
        self,
        ctx: commands.Context,
        *,
        note: str | None = None,
    ) -> None:
        await self._start_session(ctx, "MOVIE", note)

    @commands.hybrid_command(name="karaoke")
    async def karaoke(
        self,
        ctx: commands.Context,
        *,
        note: str | None = None,
    ) -> None:
        await self._start_session(ctx, "KARAOKE", note)

    @commands.hybrid_command(
        name="seshmove",
        aliases=["movesesh", "switchsesh"],
    )
    @commands.has_permissions(manage_channels=True)
    async def seshmove(
        self,
        ctx: commands.Context,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        _, config = await self._guild_config(ctx.guild.id)
        allowed_ids = {
            int(value)
            for value in config.get(VOICE_CHANNELS_KEY, [])
            if str(value).isdigit()
        }
        if not (
            config.get(ALLOW_ALL_VOICE_ROOMS_KEY, False)
            or voice_channel.id in allowed_ids
        ):
            await ctx.send(
                "❌ That destination is not an allowed Sesh voice room."
            )
            return

        current = getattr(getattr(ctx.author, "voice", None), "channel", None)
        if not current:
            await ctx.send("❌ Join the current Sesh room first.")
            return

        new = await self._switch_session_voice_channel(
            self._session_key(ctx.guild.id, current.id),
            voice_channel,
        )
        await ctx.send(
            f"✅ Sesh moved to {voice_channel.mention}."
            if new
            else "❌ Destination unavailable or already active."
        )

    @commands.hybrid_group(
        name="seshconfig",
        aliases=["seshcfg"],
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def seshconfig(self, ctx: commands.Context) -> None:
        _, config = await self._guild_config(ctx.guild.id)
        await ctx.send(
            "Use `/setup` for the Discord-native Sesh controls.\n"
            f"Enabled: **{bool(config.get(SESH_ENABLED_KEY, False))}** | "
            f"All VCs: **{bool(config.get(ALLOW_ALL_VOICE_ROOMS_KEY, False))}** | "
            f"Selected VCs: **{len(config.get(VOICE_CHANNELS_KEY, []))}** | "
            f"Ping role: **{'configured' if config.get(PING_ROLE_ID_KEY) else 'none'}** | "
            f"Private category: **{'configured' if config.get(PRIVATE_CATEGORY_ID_KEY) else 'none'}**"
        )

    @seshconfig.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_disable(self, ctx: commands.Context) -> None:
        async with self.bot.db.lock:
            _, config = await self._guild_config(ctx.guild.id)
            config[SESH_ENABLED_KEY] = False
            self.bot.db.mark_world_dirty(ctx.guild.id)
        ended = await self.end_guild_sessions(
            ctx.guild.id,
            reason="feature_disabled",
        )
        await ctx.send(
            f"✅ Optional Sesh disabled. Cleaned up **{ended}** active session(s)."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sesh(bot))
