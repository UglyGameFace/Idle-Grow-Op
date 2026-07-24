from __future__ import annotations

import asyncio, logging, os, random, re, time
from dataclasses import dataclass, field
from typing import Any

import aiohttp, discord
from discord.ext import commands
from persistence_context import GuildContextRequired, require_guild_id

logger = logging.getLogger(__name__)
SESSION_TYPES = {
    "SESH": ("🌿 Smoke Sesh", 0x2ECC71, "weed smoke sesh stoner rotation"),
    "MOVIE": ("🎬 Movie Night", 0x3498DB, "movie night popcorn watching film"),
    "KARAOKE": ("🎤 Karaoke Sesh", 0x9B59B6, "karaoke singing microphone party"),
}
WORD_RE = re.compile(r"[a-z0-9']+")
EMPTY_TIMEOUT_SECONDS, PRIVATE_TTL_SECONDS, PING_COOLDOWN_SECONDS = 600, 900, 600
UPDATE_INTERVAL_SECONDS, XP_INTERVAL_SECONDS, XP_MIN_HUMANS = 20, 60, 2
SESH_XP_MAX_PER_USER, SESH_XP_MAX_PER_INTERVAL = 160, 8
STREAK_MILESTONES, STREAK_BONUSES = (10, 20, 30, 45, 60), (10, 14, 18, 25, 35)
ROTATION_BONUS_COOLDOWN_SECONDS, ROTATION_BONUS_MAX_PER_SESSION = 120, 6
VOICE_GRACE_SECONDS, MEDIA_MIN_SCORE = 90, 8


def _tokens(text: str | None) -> set[str]: return set(WORD_RE.findall((text or "").lower()))
def build_media_query(session_type: str, keywords: str | None) -> str:
    return f"{SESSION_TYPES[session_type][2]} {' '.join(sorted(_tokens(keywords)))}".strip()
def _media_score(session_type: str, keywords: str | None, result: dict[str, Any]) -> int:
    hay = _tokens(f"{result.get('content_description','')} {' '.join(result.get('tags') or [])}")
    return 3 * len(_tokens(SESSION_TYPES[session_type][2]) & hay) + 7 * len(_tokens(keywords) & hay)


async def fetch_relevant_media(session_type: str, keywords: str | None) -> str | None:
    key = os.getenv("TENOR_API_KEY", "").strip()
    if not key: return None
    params = {"q": build_media_query(session_type, keywords), "key": key, "client_key": "idle_grow_op", "limit": 12, "media_filter": "gif,tinygif", "contentfilter": "medium", "random": "false"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client:
            async with client.get("https://tenor.googleapis.com/v2/search", params=params) as response:
                if response.status != 200: return None
                payload = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError): return None
    scored = []
    for result in payload.get("results", []):
        formats = result.get("media_formats") or {}; media = formats.get("gif") or formats.get("tinygif") or {}
        if media.get("url"): scored.append((_media_score(session_type, keywords, result), media["url"]))
    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0] >= MEDIA_MIN_SCORE else None


def curated_media(session_type: str, keywords: str | None) -> str | None:
    # A wrong GIF is worse than no GIF; specific keywords require a verified match.
    return None
def _voice_like(ch): return isinstance(ch, tuple(x for x in (discord.VoiceChannel, getattr(discord, "StageChannel", None)) if x))
def _humans(ch): return [m for m in getattr(ch, "members", []) if not m.bot]


@dataclass
class ParticipantState:
    joined_at: float; last_seen: float; left_at: float | None = None; total_awarded: int = 0
    streak_awarded: set[int] = field(default_factory=set); rotation_awarded: int = 0; last_rotation_at: float = 0.0


@dataclass
class SeshSession:
    guild_id: int; voice_channel_id: int; text_channel_id: int; message_id: int; host_id: int
    session_type: str; note: str | None; media_url: str | None; started_at: float
    empty_since: float | None = None; participants: dict[int, ParticipantState] = field(default_factory=dict)
    task: asyncio.Task | None = None; temporary_voice_channel_id: int | None = None
    active: bool = True; last_xp_award_at: float = 0.0


class SeshView(discord.ui.View):
    def __init__(self, cog: "Sesh", session_key: tuple[int, int]): super().__init__(timeout=None); self.cog, self.session_key = cog, session_key
    @discord.ui.button(label="Puff & Pass", emoji="🔥", style=discord.ButtonStyle.success)
    async def puff_pass(self, interaction, _button): await self.cog.handle_puff_pass(interaction, self.session_key)
    @discord.ui.button(label="End Sesh", emoji="🛑", style=discord.ButtonStyle.danger)
    async def end_session(self, interaction, _button):
        if not await self.cog.can_manage_session(interaction.user, self.session_key): return await interaction.response.send_message("❌ Host, active successor, or moderator only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True); await self.cog._end_sesh_session(self.session_key, reason="manual"); await interaction.followup.send("🛑 Sesh ended and cleaned up.", ephemeral=True)
    @discord.ui.button(label="Private Room", emoji="🔒", style=discord.ButtonStyle.secondary)
    async def private_room(self, interaction, _button): await self.cog.create_private_room(interaction, self.session_key)


class Sesh(commands.Cog):
    """Live voice sessions: one active session per voice channel, not per guild."""
    def __init__(self, bot):
        self.bot = bot; self._sesh_sessions: dict[tuple[int, int], SeshSession] = {}; self._ping_cooldowns = {}; self._private_cleanup_tasks = {}; self._reconcile_task = None
    async def cog_load(self): self._reconcile_task = asyncio.create_task(self._reconcile_stale_sessions(), name="sesh-reconcile")
    def cog_unload(self):
        for task in [self._reconcile_task, *[s.task for s in self._sesh_sessions.values()], *self._private_cleanup_tasks.values()]:
            if task and not task.done(): task.cancel()
        self._sesh_sessions.clear(); self._private_cleanup_tasks.clear()
    async def cog_check(self, ctx):
        try: require_guild_id(ctx); return True
        except GuildContextRequired as exc: await ctx.send(f"❌ {exc}."); return False
    def _session_key(self, guild_id, voice_channel_id): return int(guild_id), int(voice_channel_id)
    async def _guild_config(self, guild_id):
        world = await self.bot.db.get_world(guild_id); return world, world.setdefault("sesh_config", {})
    async def _persist_descriptor(self, session, key):
        world = await self.bot.db.get_world(key[0]); active = world.setdefault("active_sesh_sessions", {})
        if session is None: active.pop(str(key[1]), None)
        else: active[str(key[1])] = {"voice_channel_id": key[1], "text_channel_id": session.text_channel_id, "message_id": session.message_id, "host_id": session.host_id, "session_type": session.session_type, "started_at": session.started_at, "temporary_voice_channel_id": session.temporary_voice_channel_id}
        self.bot.db.mark_world_dirty(key[0])
    async def _reconcile_stale_sessions(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                world = await self.bot.db.get_world(guild.id); stale = dict(world.get("active_sesh_sessions") or {})
                for item in stale.values():
                    channel = guild.get_channel(int(item.get("text_channel_id") or 0)); mid = int(item.get("message_id") or 0)
                    if channel and mid:
                        try: await (await channel.fetch_message(mid)).edit(content="⚠️ This Sesh ended during a bot restart.", view=None)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass
                    temp = guild.get_channel(int(item.get("temporary_voice_channel_id") or 0))
                    if temp and _voice_like(temp) and not _humans(temp): await self._delete_channel_with_fallback(temp, reason="stale restart cleanup")
                if stale: world["active_sesh_sessions"] = {}; self.bot.db.mark_world_dirty(guild.id)
            except Exception: logger.exception("Sesh stale reconciliation failed for guild %s", guild.id)
    def _configured_voice_channel(self, ctx, config):
        current = getattr(getattr(ctx.author, "voice", None), "channel", None)
        if current and _voice_like(current): return current
        allowed = [ctx.guild.get_channel(int(x)) for x in config.get("voice_channels", []) if str(x).isdigit()]
        choices = [x for x in allowed if x and _voice_like(x)] or list(ctx.guild.voice_channels)
        return max(choices, key=lambda c: len(_humans(c))) if choices else None
    def _embed(self, guild, session):
        title, color, _ = SESSION_TYPES[session.session_type]; channel = guild.get_channel(session.voice_channel_id); people = _humans(channel) if channel else []
        embed = discord.Embed(title=title, description=session.note or "Pull up and join the room.", color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="Voice Room", value=channel.mention if channel else "Unavailable", inline=False)
        embed.add_field(name="Live Participants", value=", ".join(m.display_name for m in people[:12]) or "Waiting…", inline=False)
        embed.add_field(name="Rewards", value=f"XP begins at {XP_MIN_HUMANS}+ active people", inline=True)
        if session.media_url: embed.set_image(url=session.media_url)
        embed.set_footer(text="Puff & Pass requires real presence in this voice room."); return embed
    async def _safe_edit_session_message(self, session, **kwargs):
        guild = self.bot.get_guild(session.guild_id); channel = guild.get_channel(session.text_channel_id) if guild else None
        if not channel: return False
        try: await (await channel.fetch_message(session.message_id)).edit(**kwargs); return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException): return False
    async def _delete_channel_with_fallback(self, channel, *, reason):
        for attempt in range(3):
            try: await channel.delete(reason=reason); return True
            except discord.NotFound: return True
            except (discord.Forbidden, discord.HTTPException):
                if attempt == 2: logger.warning("Could not delete temporary Sesh channel %s", channel.id); return False
                await asyncio.sleep(2 ** attempt)
    async def can_manage_session(self, member, key):
        session = self._sesh_sessions.get(key)
        if not session: return False
        if member.id == session.host_id or member.guild_permissions.manage_channels: return True
        guild = self.bot.get_guild(session.guild_id); host = guild.get_member(session.host_id) if guild else None
        host_present = bool(host and host.voice and host.voice.channel and host.voice.channel.id == session.voice_channel_id)
        member_present = bool(member.voice and member.voice.channel and member.voice.channel.id == session.voice_channel_id)
        return not host_present and member_present
    async def _end_sesh_session(self, key, *, reason):
        session = self._sesh_sessions.pop(key, None)
        if not session: return
        session.active = False
        try:
            if session.task and session.task is not asyncio.current_task() and not session.task.done(): session.task.cancel()
            await self._persist_descriptor(None, key)
            await self._safe_edit_session_message(session, embed=discord.Embed(title="🛑 Sesh Ended", description=reason.replace("_", " "), color=discord.Color.dark_grey()), view=None)
            temp = self.bot.get_guild(session.guild_id).get_channel(session.temporary_voice_channel_id) if session.temporary_voice_channel_id else None
            if temp and _voice_like(temp) and not _humans(temp): await self._delete_channel_with_fallback(temp, reason="Sesh ended")
        finally:
            cleanup = self._private_cleanup_tasks.pop(key, None)
            if cleanup and cleanup is not asyncio.current_task() and not cleanup.done(): cleanup.cancel()
    async def _session_loop(self, key):
        try:
            while key in self._sesh_sessions:
                await asyncio.sleep(UPDATE_INTERVAL_SECONDS); session = self._sesh_sessions.get(key)
                if not session or not session.active: return
                guild = self.bot.get_guild(session.guild_id); channel = guild.get_channel(session.voice_channel_id) if guild else None
                if not channel or not _voice_like(channel): await self._end_sesh_session(key, reason="voice_channel_deleted"); return
                people, now = _humans(channel), time.time()
                if people: session.empty_since = None
                elif session.empty_since is None: session.empty_since = now
                elif now - session.empty_since >= EMPTY_TIMEOUT_SECONDS: await self._end_sesh_session(key, reason="empty_timeout"); return
                if not await self._safe_edit_session_message(session, embed=self._embed(guild, session)): await self._end_sesh_session(key, reason="announcement_missing"); return
                if now - session.last_xp_award_at >= XP_INTERVAL_SECONDS: await self._award_interval_xp(session, people, now); session.last_xp_award_at = now
        except asyncio.CancelledError: raise
        except Exception: logger.exception("Sesh loop failed for %s", key); await self._end_sesh_session(key, reason="loop_failure")
        finally:
            if key in self._sesh_sessions and not self._sesh_sessions[key].active: self._sesh_sessions.pop(key, None)
    async def _award_interval_xp(self, session, people, now):
        if len(people) < XP_MIN_HUMANS: return
        rate = min(SESH_XP_MAX_PER_INTERVAL, 2 + len(people) - 1); present = {m.id for m in people}
        async with self.bot.db.lock:
            for member in people:
                state = session.participants.setdefault(member.id, ParticipantState(now, now))
                if state.left_at and now - state.left_at > VOICE_GRACE_SECONDS: state.joined_at = now; state.streak_awarded.clear()
                state.left_at, state.last_seen = None, now; voice = member.voice
                mult = .25 if voice and (voice.self_deaf or voice.deaf) else .5 if voice and (voice.self_mute or voice.mute) else 1
                profile = await self.bot.db.get_profile(session.guild_id, member.id); gain = min(SESH_XP_MAX_PER_USER - state.total_awarded, max(0, round(rate * mult)))
                if gain: profile["xp"] = int(profile.get("xp", 0)) + gain; profile.setdefault("social_stats", {})["sesh_xp"] = int(profile.setdefault("social_stats", {}).get("sesh_xp", 0)) + gain; state.total_awarded += gain; self.bot.db.mark_profile_dirty(session.guild_id, member.id)
                minutes = int((now - state.joined_at) // 60)
                for milestone, bonus in zip(STREAK_MILESTONES, STREAK_BONUSES):
                    if minutes >= milestone and milestone not in state.streak_awarded and state.total_awarded < SESH_XP_MAX_PER_USER:
                        reward = min(bonus, SESH_XP_MAX_PER_USER - state.total_awarded); profile["xp"] += reward; state.total_awarded += reward; state.streak_awarded.add(milestone); self.bot.db.mark_profile_dirty(session.guild_id, member.id)
            for uid, state in session.participants.items():
                if uid not in present and state.left_at is None: state.left_at = now
    async def handle_puff_pass(self, interaction, key):
        session = self._sesh_sessions.get(key); member = interaction.user
        if not session or not session.active: return await interaction.response.send_message("❌ This Sesh is no longer active.", ephemeral=True)
        if not member.voice or not member.voice.channel or member.voice.channel.id != session.voice_channel_id: return await interaction.response.send_message("❌ Join the active voice room first.", ephemeral=True)
        people = _humans(member.voice.channel)
        if len(people) < XP_MIN_HUMANS: return await interaction.response.send_message("❌ Puff & Pass needs at least two people.", ephemeral=True)
        now = time.time(); state = session.participants.setdefault(member.id, ParticipantState(now, now))
        if state.rotation_awarded >= ROTATION_BONUS_MAX_PER_SESSION: return await interaction.response.send_message("⏳ Session bonus cap reached.", ephemeral=True)
        if now - state.last_rotation_at < ROTATION_BONUS_COOLDOWN_SECONDS: return await interaction.response.send_message("⏳ Pass it around first.", ephemeral=True)
        next_member = random.choice([x for x in people if x.id != member.id]); reward = min(5, SESH_XP_MAX_PER_USER - state.total_awarded)
        async with self.bot.db.lock:
            if reward: profile = await self.bot.db.get_profile(session.guild_id, member.id); profile["xp"] = int(profile.get("xp", 0)) + reward; self.bot.db.mark_profile_dirty(session.guild_id, member.id); state.total_awarded += reward
            state.rotation_awarded += 1; state.last_rotation_at = now
        await interaction.response.send_message(f"💨 **{member.display_name}** passes to **{next_member.display_name}**! (+{reward} XP)")
    async def _switch_session_voice_channel(self, old_key, new_channel):
        session = self._sesh_sessions.get(old_key); new_key = self._session_key(old_key[0], new_channel.id)
        if not session or not _voice_like(new_channel) or (new_key in self._sesh_sessions and new_key != old_key): return None
        old_task = session.task
        self._sesh_sessions.pop(old_key); await self._persist_descriptor(None, old_key); session.voice_channel_id = new_channel.id; session.empty_since = None; self._sesh_sessions[new_key] = session; await self._persist_descriptor(session, new_key)
        if old_task and old_task is not asyncio.current_task() and not old_task.done(): old_task.cancel()
        session.task = asyncio.create_task(self._session_loop(new_key), name=f"sesh-{session.guild_id}-{new_channel.id}")
        await self._safe_edit_session_message(session, embed=self._embed(new_channel.guild, session), view=SeshView(self, new_key)); return new_key
    async def create_private_room(self, interaction, key):
        session = self._sesh_sessions.get(key)
        if not session: return await interaction.response.send_message("❌ This Sesh ended.", ephemeral=True)
        _, config = await self._guild_config(interaction.guild.id); category = interaction.guild.get_channel(int(config.get("private_category_id") or 0))
        if not isinstance(category, discord.CategoryChannel): return await interaction.response.send_message("❌ Configure a private Sesh category first.", ephemeral=True)
        try:
            overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False), interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True), interaction.guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True)}
            channel = await interaction.guild.create_voice_channel(name=f"private-sesh-{interaction.user.display_name}".lower().replace(" ", "-")[:90], category=category, overwrites=overwrites)
        except (discord.Forbidden, discord.HTTPException) as exc: return await interaction.response.send_message(f"❌ Could not create room: `{exc}`", ephemeral=True)
        session.temporary_voice_channel_id = channel.id; new_key = await self._switch_session_voice_channel(key, channel)
        if not new_key: await self._delete_channel_with_fallback(channel, reason="switch failed"); return await interaction.response.send_message("❌ Could not activate that room.", ephemeral=True)
        task = asyncio.create_task(self._private_room_cleanup(new_key, channel.id)); self._private_cleanup_tasks[new_key] = task
        await interaction.response.send_message(f"✅ Private room created and set active: {channel.mention}", ephemeral=True)
    async def _private_room_cleanup(self, key, channel_id):
        try:
            await asyncio.sleep(PRIVATE_TTL_SECONDS)
            while True:
                guild = self.bot.get_guild(key[0]); channel = guild.get_channel(channel_id) if guild else None
                if not channel: return
                if _voice_like(channel) and not _humans(channel): await self._delete_channel_with_fallback(channel, reason="Private Sesh expired"); return
                await asyncio.sleep(60)
        except asyncio.CancelledError: raise
        finally: self._private_cleanup_tasks.pop(key, None)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        now = time.time()
        for channel in (before.channel, after.channel):
            if not channel: continue
            session = self._sesh_sessions.get(self._session_key(member.guild.id, channel.id))
            if not session: continue
            state = session.participants.setdefault(member.id, ParticipantState(now, now))
            if after.channel and after.channel.id == channel.id:
                if state.left_at and now - state.left_at > VOICE_GRACE_SECONDS: state.joined_at = now; state.streak_awarded.clear()
                state.last_seen = now; state.left_at = None; session.empty_since = None
            elif before.channel and before.channel.id == channel.id: state.left_at = now; session.empty_since = now if not _humans(channel) else session.empty_since
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        key = self._session_key(channel.guild.id, channel.id)
        if key in self._sesh_sessions: await self._end_sesh_session(key, reason="voice_channel_deleted")
        for skey, session in list(self._sesh_sessions.items()):
            if session.text_channel_id == channel.id: await self._end_sesh_session(skey, reason="announcement_channel_deleted")
    async def _start_session(self, ctx, session_type, note):
        guild_id = require_guild_id(ctx); _, config = await self._guild_config(guild_id); voice = self._configured_voice_channel(ctx, config)
        if not voice: return await ctx.send("❌ Join or configure a Sesh voice room first.")
        key = self._session_key(guild_id, voice.id)
        if key in self._sesh_sessions: return await ctx.send(f"⚠️ A Sesh is already active in {voice.mention}.")
        cooldown = (guild_id, voice.id, session_type); now = time.time(); remaining = PING_COOLDOWN_SECONDS - (now - self._ping_cooldowns.get(cooldown, 0))
        if remaining > 0: return await ctx.send(f"⏳ This room can ping again in {int(remaining)}s.")
        self._ping_cooldowns[cooldown] = now; media = await fetch_relevant_media(session_type, note) or curated_media(session_type, note)
        role = ctx.guild.get_role(int(config.get("ping_role_id") or 0)); ping = role.mention if role else "@here"
        session = SeshSession(guild_id, voice.id, ctx.channel.id, 0, ctx.author.id, session_type, note, media, now); view = SeshView(self, key)
        try: message = await ctx.send(content=f"{ping} — {ctx.author.mention} started {SESSION_TYPES[session_type][0]} in {voice.mention}!", embed=self._embed(ctx.guild, session), view=view)
        except discord.Forbidden: return await ctx.send("❌ I need Send Messages and Embed Links here.")
        session.message_id = message.id; session.last_xp_award_at = now; self._sesh_sessions[key] = session; await self._persist_descriptor(session, key); session.task = asyncio.create_task(self._session_loop(key), name=f"sesh-{guild_id}-{voice.id}")
    @commands.hybrid_command(name="sesh", aliases=["cheers", "smoke", "blaze"])
    async def sesh(self, ctx, *, note: str | None = None): await self._start_session(ctx, "SESH", note)
    @commands.hybrid_command(name="movie")
    async def movie(self, ctx, *, note: str | None = None): await self._start_session(ctx, "MOVIE", note)
    @commands.hybrid_command(name="karaoke")
    async def karaoke(self, ctx, *, note: str | None = None): await self._start_session(ctx, "KARAOKE", note)
    @commands.hybrid_command(name="seshmove", aliases=["movesesh", "switchsesh"])
    @commands.has_permissions(manage_channels=True)
    async def seshmove(self, ctx, voice_channel: discord.VoiceChannel):
        current = getattr(getattr(ctx.author, "voice", None), "channel", None)
        if not current: return await ctx.send("❌ Join the current Sesh room first.")
        new = await self._switch_session_voice_channel(self._session_key(ctx.guild.id, current.id), voice_channel)
        await ctx.send(f"✅ Sesh moved to {voice_channel.mention}." if new else "❌ Destination unavailable or already active.")
    @commands.hybrid_group(name="seshconfig", aliases=["seshcfg"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def seshconfig(self, ctx):
        _, cfg = await self._guild_config(ctx.guild.id); await ctx.send(f"Ping role: <@&{cfg.get('ping_role_id')}> | VCs: {cfg.get('voice_channels', [])} | Private category: <#{cfg.get('private_category_id')}>")
    @seshconfig.command(name="role")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_role(self, ctx, role: discord.Role):
        _, cfg = await self._guild_config(ctx.guild.id); cfg["ping_role_id"] = role.id; self.bot.db.mark_world_dirty(ctx.guild.id); await ctx.send(f"✅ Ping role: {role.mention}")
    @seshconfig.command(name="addvc")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_addvc(self, ctx, voice_channel: discord.VoiceChannel):
        _, cfg = await self._guild_config(ctx.guild.id); ids = cfg.setdefault("voice_channels", [])
        if voice_channel.id not in ids: ids.append(voice_channel.id); self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Added {voice_channel.mention}")
    @seshconfig.command(name="rmvc")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_rmvc(self, ctx, voice_channel: discord.VoiceChannel):
        _, cfg = await self._guild_config(ctx.guild.id); ids = cfg.setdefault("voice_channels", [])
        if voice_channel.id in ids: ids.remove(voice_channel.id); self.bot.db.mark_world_dirty(ctx.guild.id)
        await ctx.send(f"✅ Removed {voice_channel.mention}")
    @seshconfig.command(name="privatecat")
    @commands.has_permissions(manage_guild=True)
    async def seshconfig_privatecat(self, ctx, category: discord.CategoryChannel):
        _, cfg = await self._guild_config(ctx.guild.id); cfg["private_category_id"] = category.id; self.bot.db.mark_world_dirty(ctx.guild.id); await ctx.send(f"✅ Private category: **{category.name}**")


async def setup(bot): await bot.add_cog(Sesh(bot))
