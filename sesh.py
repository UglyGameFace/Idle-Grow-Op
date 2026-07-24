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

logger = logging.getLogger(__name__)

SESSION_TYPES = {
    "SESH": {
        "title": "🌿 Smoke Sesh",
        "color": 0x2ECC71,
        "query_prefix": "weed smoke sesh stoner rotation",
        "fallbacks": [
            "https://media.tenor.com/2roX3uxz_68AAAAC/smoke-weed.gif",
            "https://media.tenor.com/8K2Q9Q5fQJkAAAAC/smoke-cloud.gif",
        ],
    },
    "MOVIE": {
        "title": "🎬 Movie Night",
        "color": 0x3498DB,
        "query_prefix": "movie night popcorn watching film",
        "fallbacks": [
            "https://media.tenor.com/2WZtOD6pQ6oAAAAC/movie-night.gif",
            "https://media.tenor.com/56k3Jw5j8hEAAAAC/popcorn-movie.gif",
        ],
    },
    "KARAOKE": {
        "title": "🎤 Karaoke Sesh",
        "color": 0x9B59B6,
        "query_prefix": "karaoke singing microphone party",
        "fallbacks": [
            "https://media.tenor.com/caRZ8Qw3JqkAAAAC/karaoke-singing.gif",
            "https://media.tenor.com/0Y4Y7TjQLxIAAAAC/sing-microphone.gif",
        ],
    },
}

WORD_RE = re.compile(r"[a-z0-9']+")
EMPTY_TIMEOUT_SECONDS = 10 * 60
PRIVATE_TTL_SECONDS = 15 * 60
PING_COOLDOWN_SECONDS = 10 * 60
UPDATE_INTERVAL_SECONDS = 20
XP_MIN_HUMANS = 2
SESH_XP_MAX_PER_USER = 160
SESH_XP_MAX_PER_INTERVAL = 8
SESH_XP_BASE_PER_INTERVAL = 2
SESH_XP_PER_EXTRA_MEMBER = 1
STREAK_MILESTONES = (10, 20, 30, 45, 60)
STREAK_BONUSES = (10, 14, 18, 25, 35)
ROTATION_BONUS_COOLDOWN_SECONDS = 120
ROTATION_BONUS_MAX_PER_SESSION = 6
VOICE_GRACE_SECONDS = 90
MEDIA_MIN_SCORE = 8


def _tokens(text: str | None) -> set[str]:
    return set(WORD_RE.findall((text or "").lower()))


def build_media_query(session_type: str, keywords: str | None) -> str:
    spec = SESSION_TYPES[session_type]
    clean = " ".join(sorted(_tokens(keywords)))
    return f"{spec['query_prefix']} {clean}".strip()


def _media_score(session_type: str, keywords: str | None, result: dict[str, Any]) -> int:
    session_tokens = _tokens(SESSION_TYPES[session_type]["query_prefix"])
    note_tokens = _tokens(keywords)
    title = str(result.get("content_description") or result.get("title") or "")
    tags = " ".join(str(x) for x in (result.get("tags") or []))
    haystack = _tokens(f"{title} {tags}")
    return len(session_tokens & haystack) * 3 + len(note_tokens & haystack) * 7


async def fetch_relevant_media(session_type: str, keywords: str | None) -> str | None:
    api_key = os.getenv("TENOR_API_KEY", "").strip()
    if not api_key:
        return None
    params = {
        "q": build_media_query(session_type, keywords),
        "key": api_key,
        "client_key": "idle_grow_op",
        "limit": "12",
        "media_filter": "gif,tinygif",
        "contentfilter": "medium",
        "random": "false",
    }
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://tenor.googleapis.com/v2/search", params=params) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None

    scored: list[tuple[int, str]] = []
    for result in payload.get("results", []):
        formats = result.get("media_formats") or {}
        media = formats.get("gif") or formats.get("tinygif") or {}
        url = str(media.get("url") or "").strip()
        if url:
            scored.append((_media_score(session_type, keywords, result), url))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < MEDIA_MIN_SCORE:
        return None
    return scored[0][1]


def curated_media(session_type: str, keywords: str | None) -> str | None:
    choices = list(SESSION_TYPES[session_type]["fallbacks"])
    return random.choice(choices) if choices else None


def _voice_like(channel: Any) -> bool:
    stage = getattr(discord, "StageChannel", None)
    allowed = (discord.VoiceChannel,) if stage is None else (discord.VoiceChannel, stage)
    return isinstance(channel, allowed)


def _humans(channel: Any) -> list[discord.Member]:
    return [member for member in getattr(channel, "members", []) if not member.bot]


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
    active: bool = True


class SeshView(discord.ui.View):
    def __init__(self, cog: "Sesh", session_key: tuple[int, int]):
        super().__init__(timeout=None)
        self.cog = cog
        self.session_key = session_key

    @discord.ui.button(label="Puff & Pass", emoji="🔥", style=discord.ButtonStyle.success)
    async def puff_pass(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.handle_puff_pass(interaction, self.session_key)

    @discord.ui.button(label="End Sesh", emoji="🛑", style=discord.ButtonStyle.danger)
    async def end_session(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self.cog.can_manage_session(interaction.user, self.session_key):
            return await interaction.response.send_message(
                "❌ Only the host, an active participant after host departure, or a moderator can end this Sesh.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        await self.cog._end_sesh_session(self.session_key, reason="manual")
        await interaction.followup.send("🛑 Sesh ended and cleaned up.", ephemeral=True)

    @discord.ui.button(label="Private Room", emoji="🔒", style=discord.ButtonStyle.secondary)
    async def private_room(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.create_private_room(interaction, self.session_key)


class Sesh(commands.Cog):
    """Live voice sessions. One active session per voice channel, not per guild."""

    def __init__(self, bot: commands.Bot):
        # Canonical identity is (guild_id, voice_channel_id).
        self.bot = bot
        self._sesh_sessions: dict[tuple[int, int], SeshSession] = {}
        self._ping_cooldowns: dict[tuple[int, int, str], float] = {}
        self._private_cleanup_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._reconcile_task: asyncio.Task | None = None

    async def cog_load(self):
        self._reconcile_task = asyncio.create_task(self._reconcile_stale_sessions(), name="sesh-reconcile")

    def cog_unload(self):
        if self._reconcile_task and not self._reconcile_task.done():
            self._reconcile_task.cancel()
        for session in list(self._sesh_sessions.values()):
            if session.task and not session.task.done():
                session.task.cancel()
        for task in list(self._private_cleanup_tasks.values()):
            if not task.done():
                task.cancel()
        self._sesh_sessions.clear()
        self._private_cleanup_tasks.clear()

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    def _session_key(self, guild_id: int, voice_channel_id: int) -> tuple[int, int]:
        return int(guild_id), int(voice_channel_id)

    async def _guild_config(self, guild_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        world = await self.bot.db.get_world(guild_id)
        config = world.setdefault("sesh_config", {})
        return world, config

    async def _persist_descriptor(self, session: SeshSession | None, key: tuple[int, int]):
        guild_id, vc_id = key
        world = await self.bot.db.get_world(guild_id)
        descriptors = world.setdefault("active_sesh_sessions", {})
        if session is None:
            descriptors.pop(str(vc_id), None)
        else:
            descriptors[str(vc_id)] = {
                "voice_channel_id": vc_id,
                "text_channel_id": session.text_channel_id,
                "message_id": session.message_id,
                "host_id": session.host_id,
                "session_type": session.session_type,
                "started_at": session.started_at,
                "temporary_voice_channel_id": session.temporary_voice_channel_id,
            }
        self.bot.db.mark_world_dirty(guild_id)

    async def _reconcile_stale_sessions(self):
        await self.bot.wait_until_ready()
        # Restart cannot safely resume in-memory XP timers. Clear stale descriptors
        # and disable old controls so users never need a force-start workaround.
        for guild in list(self.bot.guilds):
            try:
                world = await self.bot.db.get_world(guild.id)
                descriptors = dict(world.get("active_sesh_sessions") or {})
                for descriptor in descriptors.values():
                    text = guild.get_channel(int(descriptor.get("text_channel_id") or 0))
                    message_id = int(descriptor.get("message_id") or 0)
                    if text and message_id:
                        try:
                            message = await text.fetch_message(message_id)
                            await message.edit(content="⚠️ This Sesh ended during a bot restart.", view=None)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                    temp_id = int(descriptor.get("temporary_voice_channel_id") or 0)
                    temp = guild.get_channel(temp_id) if temp_id else None
                    if temp and _voice_like(temp) and not _humans(temp):
                        await self._delete_channel_with_fallback(temp, reason="stale Sesh restart cleanup")
                if descriptors:
                    world["active_sesh_sessions"] = {}
                    self.bot.db.mark_world_dirty(guild.id)
            except Exception:
                logger.exception("Sesh stale-session reconciliation failed for guild %s", guild.id)

    def _configured_voice_channel(self, ctx, config: dict[str, Any]):
        current = getattr(getattr(ctx.author, "voice", None), "channel", None)
        if current and _voice_like(current):
            return current
        allowed = [int(value) for value in config.get("voice_channels", []) if str(value).isdigit()]
        candidates = [ctx.guild.get_channel(channel_id) for channel_id in allowed]
        candidates = [channel for channel in candidates if channel and _voice_like(channel)]
        if not candidates:
            candidates = list(ctx.guild.voice_channels)
        return max(candidates, key=lambda channel: len(_humans(channel))) if candidates else None

    async def _resolve_role_ping(self, guild: discord.Guild, config: dict[str, Any]) -> str:
        role_id = int(config.get("ping_role_id") or 0)
        role = guild.get_role(role_id) if role_id else None
        return role.mention if role else "@here"

    def _embed(self, guild: discord.Guild, session: SeshSession) -> discord.Embed:
        spec = SESSION_TYPES[session.session_type]
        channel = guild.get_channel(session.voice_channel_id)
        humans = _humans(channel) if channel else []
        names = ", ".join(member.display_name for member in humans[:12]) or "Waiting for the rotation…"
        embed = discord.Embed(
            title=spec["title"],
            description=session.note or "Pull up and join the room.",
            color=spec["color"],
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Voice Room", value=channel.mention if channel else "Room unavailable", inline=False)
        embed.add_field(name="Live Participants", value=names, inline=False)
        embed.add_field(name="Session Time", value=f"<t:{int(session.started_at)}:R>", inline=True)
        embed.add_field(name="Rewards", value=f"XP begins at {XP_MIN_HUMANS}+ active people", inline=True)
        if session.media_url:
            embed.set_image(url=session.media_url)
        embed.set_footer(text="Puff & Pass rewards require real presence in this voice room.")
        return embed

    async def _safe_edit_session_message(self, session: SeshSession, **kwargs) -> bool:
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

    async def _delete_channel_with_fallback(self, channel, *, reason: str) -> bool:
        for attempt in range(3):
            try:
                await channel.delete(reason=reason)
                return True
            except discord.NotFound:
                return True
            except (discord.Forbidden, discord.HTTPException):
                if attempt == 2:
                    logger.warning("Unable to delete temporary Sesh channel %s", channel.id)
                    return False
                await asyncio.sleep(2 ** attempt)
        return False

    async def can_manage_session(self, member, key: tuple[int, int]) -> bool:
        session = self._sesh_sessions.get(key)
        if not session:
            return False
        if int(member.id) == session.host_id:
            return True
        if getattr(member.guild_permissions, "manage_channels", False):
            return True
        guild = self.bot.get_guild(session.guild_id)
        host = guild.get_member(session.host_id) if guild else None
        host_present = bool(host and host.voice and host.voice.channel and host.voice.channel.id == session.voice_channel_id)
        member_present = bool(member.voice and member.voice.channel and member.voice.channel.id == session.voice_channel_id)
        return not host_present and member_present

    async def _end_sesh_session(self, key: tuple[int, int], *, reason: str):
        session = self._sesh_sessions.pop(key, None)
        if not session:
            return
        session.active = False
        try:
            if session.task and session.task is not asyncio.current_task() and not session.task.done():
                session.task.cancel()
            await self._persist_descriptor(None, key)
            ended = discord.Embed(
                title="🛑 Sesh Ended",
                description=f"Reason: `{reason.replace('_', ' ')}`",
                color=discord.Color.dark_grey(),
            )
            await self._safe_edit_session_message(session, embed=ended, view=None)
            if session.temporary_voice_channel_id:
                guild = self.bot.get_guild(session.guild_id)
                temp = guild.get_channel(session.temporary_voice_channel_id) if guild else None
                if temp and _voice_like(temp) and not _humans(temp):
                    await self._delete_channel_with_fallback(temp, reason="Sesh ended")
        finally:
            cleanup = self._private_cleanup_tasks.pop(key, None)
            if cleanup and cleanup is not asyncio.current_task() and not cleanup.done():
                cleanup.cancel()

    async def _session_loop(self, key: tuple[int, int]):
        try:
            while key in self._sesh_sessions:
                await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
                session = self._sesh_sessions.get(key)
                if not session or not session.active:
                    return
                guild = self.bot.get_guild(session.guild_id)
                channel = guild.get_channel(session.voice_channel_id) if guild else None
                if not channel or not _voice_like(channel):
                    await self._end_sesh_session(key, reason="voice_channel_deleted")
                    return
                humans = _humans(channel)
                now = time.time()
                if humans:
                    session.empty_since = None
                elif session.empty_since is None:
                    session.empty_since = now
                elif now - session.empty_since >= EMPTY_TIMEOUT_SECONDS:
                    await self._end_sesh_session(key, reason="empty_timeout")
                    return
                if not await self._safe_edit_session_message(session, embed=self._embed(guild, session)):
                    await self._end_sesh_session(key, reason="announcement_missing")
                    return
                await self._award_interval_xp(session, humans, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sesh loop failed for %s", key)
            await self._end_sesh_session(key, reason="loop_failure")
        finally:
            if key in self._sesh_sessions and not self._sesh_sessions[key].active:
                self._sesh_sessions.pop(key, None)

    async def _award_interval_xp(self, session: SeshSession, humans: list[discord.Member], now: float):
        if len(humans) < XP_MIN_HUMANS:
            for state in session.participants.values():
                state.left_at = now
            return
        rate = min(SESH_XP_MAX_PER_INTERVAL, SESH_XP_BASE_PER_INTERVAL + max(0, len(humans) - 1) * SESH_XP_PER_EXTRA_MEMBER)
        present_ids = {member.id for member in humans}
        async with self.bot.db.lock:
            for member in humans:
                state = session.participants.setdefault(member.id, ParticipantState(now, now))
                if state.left_at and now - state.left_at > VOICE_GRACE_SECONDS:
                    state.joined_at = now
                    state.streak_awarded.clear()
                state.left_at = None
                state.last_seen = now
                voice = member.voice
                multiplier = 0.25 if voice and (voice.self_deaf or voice.deaf) else 0.5 if voice and (voice.self_mute or voice.mute) else 1.0
                remaining = SESH_XP_MAX_PER_USER - state.total_awarded
                gain = min(remaining, max(0, int(round(rate * multiplier))))
                profile = await self.bot.db.get_profile(session.guild_id, member.id)
                if gain:
                    profile["xp"] = int(profile.get("xp", 0)) + gain
                    stats = profile.setdefault("social_stats", {})
                    stats["sesh_xp"] = int(stats.get("sesh_xp", 0)) + gain
                    state.total_awarded += gain
                    self.bot.db.mark_profile_dirty(session.guild_id, member.id)
                minutes = int((now - state.joined_at) // 60)
                for milestone, bonus in zip(STREAK_MILESTONES, STREAK_BONUSES):
                    if minutes >= milestone and milestone not in state.streak_awarded and state.total_awarded < SESH_XP_MAX_PER_USER:
                        reward = min(bonus, SESH_XP_MAX_PER_USER - state.total_awarded)
                        profile["xp"] = int(profile.get("xp", 0)) + reward
                        state.total_awarded += reward
                        state.streak_awarded.add(milestone)
                        self.bot.db.mark_profile_dirty(session.guild_id, member.id)
            for user_id, state in session.participants.items():
                if user_id not in present_ids and state.left_at is None:
                    state.left_at = now

    async def handle_puff_pass(self, interaction: discord.Interaction, key: tuple[int, int]):
        session = self._sesh_sessions.get(key)
        if not session or not session.active:
            return await interaction.response.send_message("❌ This Sesh is no longer active.", ephemeral=True)
        member = interaction.user
        if not member.voice or not member.voice.channel or member.voice.channel.id != session.voice_channel_id:
            return await interaction.response.send_message("❌ Join the active voice room before using Puff & Pass.", ephemeral=True)
        humans = _humans(member.voice.channel)
        if len(humans) < XP_MIN_HUMANS:
            return await interaction.response.send_message("❌ Puff & Pass needs at least two active people.", ephemeral=True)
        now = time.time()
        state = session.participants.setdefault(member.id, ParticipantState(now, now))
        if state.rotation_awarded >= ROTATION_BONUS_MAX_PER_SESSION:
            return await interaction.response.send_message("⏳ You reached this session's Puff & Pass bonus cap.", ephemeral=True)
        if now - state.last_rotation_at < ROTATION_BONUS_COOLDOWN_SECONDS:
            remaining = int(ROTATION_BONUS_COOLDOWN_SECONDS - (now - state.last_rotation_at))
            return await interaction.response.send_message(f"⏳ Pass it around first—try again in {remaining}s.", ephemeral=True)
        next_member = random.choice([candidate for candidate in humans if candidate.id != member.id])
        reward = min(5, SESH_XP_MAX_PER_USER - state.total_awarded)
        async with self.bot.db.lock:
            if reward > 0:
                profile = await self.bot.db.get_profile(session.guild_id, member.id)
                profile["xp"] = int(profile.get("xp", 0)) + reward
                self.bot.db.mark_profile_dirty(session.guild_id, member.id)
                state.total_awarded += reward
            state.rotation_awarded += 1
            state.last_rotation_at = now
        await interaction.response.send_message(
            f"💨 **{member.display_name}** takes a rip and passes to **{next_member.display_name}**! (+{reward} XP)"
        )

    async def create_private_room(self, interaction: discord.Interaction, key: tuple[int, int]):
        session = self._sesh_sessions.get(key)
        if not session:
            return await interaction.response.send_message("❌ This Sesh is no longer active.", ephemeral=True)
        guild = interaction.guild
        _world, config = await self._guild_config(guild.id)
        category = guild.get_channel(int(config.get("private_category_id") or 0))
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("❌ A private Sesh category has not been configured.", ephemeral=True)
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
            }
            name = f"private-sesh-{interaction.user.display_name}".lower().replace(" ", "-")[:90]
            channel = await guild.create_voice_channel(name=name, category=category, overwrites=overwrites, reason="Temporary private Sesh")
        except (discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"❌ Could not create the private room: `{exc}`", ephemeral=True)
        session.temporary_voice_channel_id = channel.id
        await self._persist_descriptor(session, key)
        task = asyncio.create_task(self._private_room_cleanup(key, channel.id), name=f"sesh-private-{guild.id}-{channel.id}")
        old = self._private_cleanup_tasks.get(key)
        if old and not old.done():
            old.cancel()
        self._private_cleanup_tasks[key] = task
        await interaction.response.send_message(f"✅ Private room created: {channel.mention}", ephemeral=True)

    async def _private_room_cleanup(self, key: tuple[int, int], channel_id: int):
        try:
            await asyncio.sleep(PRIVATE_TTL_SECONDS)
            session = self._sesh_sessions.get(key)
            guild = self.bot.get_guild(key[0])
            channel = guild.get_channel(channel_id) if guild else None
            if channel and _voice_like(channel):
                if _humans(channel):
                    await asyncio.sleep(5 * 60)
                if not _humans(channel):
                    await self._delete_channel_with_fallback(channel, reason="Private Sesh expired")
            if session and session.temporary_voice_channel_id == channel_id:
                session.temporary_voice_channel_id = None
                await self._persist_descriptor(session, key)
        except asyncio.CancelledError:
            raise
        finally:
            self._private_cleanup_tasks.pop(key, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        now = time.time()
        for channel in (before.channel, after.channel):
            if not channel:
                continue
            key = self._session_key(member.guild.id, channel.id)
            session = self._sesh_sessions.get(key)
            if not session:
                continue
            state = session.participants.setdefault(member.id, ParticipantState(now, now))
            if after.channel and after.channel.id == channel.id:
                state.last_seen = now
                if state.left_at and now - state.left_at > VOICE_GRACE_SECONDS:
                    state.joined_at = now
                    state.streak_awarded.clear()
                state.left_at = None
                session.empty_since = None
            elif before.channel and before.channel.id == channel.id:
                state.left_at = now
                if not _humans(channel):
                    session.empty_since = now

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        key = self._session_key(channel.guild.id, channel.id)
        if key in self._sesh_sessions:
            await self._end_sesh_session(key, reason="voice_channel_deleted")
        for session_key, session in list(self._sesh_sessions.items()):
            if session.text_channel_id == channel.id:
                await self._end_sesh_session(session_key, reason="announcement_channel_deleted")

    async def _start_session(self, ctx, session_type: str, note: str | None):
        guild_id = require_guild_id(ctx)
        _world, config = await self._guild_config(guild_id)
        voice = self._configured_voice_channel(ctx, config)
        if not voice:
            return await ctx.send("❌ Join a voice channel or configure an approved Sesh voice room first.")
        key = self._session_key(guild_id, voice.id)
        current = self._sesh_sessions.get(key)
        if current and current.active:
            jump = f"https://discord.com/channels/{guild_id}/{current.text_channel_id}/{current.message_id}"
            return await ctx.send(f"⚠️ A Sesh is already active in {voice.mention}: {jump}")
        cooldown_key = (guild_id, voice.id, session_type)
        now = time.time()
        remaining = PING_COOLDOWN_SECONDS - (now - self._ping_cooldowns.get(cooldown_key, 0))
        if remaining > 0:
            return await ctx.send(f"⏳ This room can ping again in {int(remaining)}s.")
        self._ping_cooldowns[cooldown_key] = now
        media_url = await fetch_relevant_media(session_type, note) or curated_media(session_type, note)
        role_ping = await self._resolve_role_ping(ctx.guild, config)
        provisional = SeshSession(guild_id, voice.id, ctx.channel.id, 0, ctx.author.id, session_type, note, media_url, now)
        view = SeshView(self, key)
        try:
            message = await ctx.send(
                content=f"{role_ping} — {ctx.author.mention} started a {SESSION_TYPES[session_type]['title']} in {voice.mention}!",
                embed=self._embed(ctx.guild, provisional),
                view=view,
            )
        except discord.Forbidden:
            return await ctx.send("❌ I need Send Messages and Embed Links in this channel.")
        provisional.message_id = message.id
        self._sesh_sessions[key] = provisional
        await self._persist_descriptor(provisional, key)
        provisional.task = asyncio.create_task(self._session_loop(key), name=f"sesh-{guild_id}-{voice.id}")

    @commands.hybrid_command(name="sesh", aliases=["cheers", "smoke", "blaze"])
    async def sesh(self, ctx, *, note: str | None = None):
        await self._start_session(ctx, "SESH", note)

    @commands.hybrid_command(name="movie")
    async def movie(self, ctx, *, note: str | None = None):
        await self._start_session(ctx, "MOVIE", note)

    @commands.hybrid_command(name="karaoke")
    async def karaoke(self, ctx, *, note: str | None = None):
        await self._start_session(ctx, "KARAOKE", note)

    @commands.hybrid_group(name="seshconfig", aliases=["seshcfg"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def seshconfig(self, ctx):
        _world, config = await self._guild_config(ctx.guild.id)
        channels = [f"<#{channel_id}>" for channel_id in config.get("voice_channels", [])]
        await ctx.send(
            f"**Sesh configuration**\nPing role: <@&{config.get('ping_role_id')}>\n"
            f"Voice rooms: {', '.join(channels) or 'auto-detect'}\n"
            f"Private category: <#{config.get('private_category_id')}>"
        )

    @seshconfig.command(name="role")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_role(self, ctx, role: discord.Role):
        _world, config = await self._guild_config(ctx.guild.id)
        config["ping_role_id"] = role.id
        self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Sesh ping role set to {role.mention}.")

    @seshconfig.command(name="addvc")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_addvc(self, ctx, voice_channel: discord.VoiceChannel):
        _world, config = await self._guild_config(ctx.guild.id)
        channels = config.setdefault("voice_channels", [])
        if voice_channel.id not in channels:
            channels.append(voice_channel.id)
            self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Added {voice_channel.mention} as an approved Sesh room.")

    @seshconfig.command(name="rmvc")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_rmvc(self, ctx, voice_channel: discord.VoiceChannel):
        _world, config = await self._guild_config(ctx.guild.id)
        channels = config.setdefault("voice_channels", [])
        if voice_channel.id in channels:
            channels.remove(voice_channel.id)
            self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Removed {voice_channel.mention} from approved Sesh rooms.")

    @seshconfig.command(name="privatecat")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_privatecat(self, ctx, category: discord.CategoryChannel):
        _world, config = await self._guild_config(ctx.guild.id)
        config["private_category_id"] = category.id
        self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Private Sesh category set to **{category.name}**.")


async def setup(bot):
    await bot.add_cog(Sesh(bot))
