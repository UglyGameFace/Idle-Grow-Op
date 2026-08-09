from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from minecraft_service import (
    DEFAULT_BEDROCK_PORT,
    DEFAULT_JAVA_PORT,
    TOP_METRICS,
    MinecraftDataService,
    MinecraftDataUnavailable,
    MinecraftPingError,
    aura_total_level,
    discord_timestamp,
    format_duration_from_ticks,
    ping_java_server,
)


logger = logging.getLogger(__name__)
GUIDE_COLOR = 0x57F287
INFO_COLOR = 0x5865F2
WARN_COLOR = 0xFEE75C
ERROR_COLOR = 0xED4245
DISCORD_ID_RE = re.compile(r"^<@!?(\d+)>$")


def _trim(value: Any, limit: int = 1024) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _player_platform(row: dict[str, Any]) -> str:
    platform = str(row.get("platform") or "java").lower()
    return "🟩 Bedrock" if platform == "bedrock" else "☕ Java"


def _stats(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("stats")
    return value if isinstance(value, dict) else {}


def _aura_summary(row: dict[str, Any], *, limit: int = 6) -> str:
    value = row.get("aura_skills")
    if not isinstance(value, dict) or not value:
        return "No AuraSkills snapshot yet."
    pairs: list[tuple[str, int]] = []
    for name, entry in value.items():
        if not isinstance(entry, dict):
            continue
        try:
            level = max(0, int(entry.get("level") or 0))
        except (TypeError, ValueError):
            level = 0
        pairs.append((str(name), level))
    pairs.sort(key=lambda item: (-item[1], item[0].lower()))
    if not pairs:
        return "No AuraSkills snapshot yet."
    return "\n".join(f"• **{name.title()}** — Lv. {level}" for name, level in pairs[:limit])


def _metric_display(metric: str, value: int) -> str:
    return format_duration_from_ticks(value) if metric == "playtime" else f"{value:,}"


class Minecraft(commands.Cog):
    """The Plug's Discord-side Minecraft companion."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = MinecraftDataService()

    async def cog_load(self) -> None:
        if not self.data.configured:
            logger.warning(
                "Minecraft companion loaded without Turso credentials; commands remain registered but data setup is unavailable"
            )
            return
        await self.data.ensure_schema()
        logger.info("Minecraft companion Turso schema is ready")

    async def cog_unload(self) -> None:
        await self.data.close()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.send("❌ Minecraft companion commands only work inside a Discord server.")
            return False
        return True

    @staticmethod
    def _is_manager(ctx: commands.Context) -> bool:
        member = ctx.author
        return isinstance(member, discord.Member) and member.guild_permissions.manage_guild

    async def _need_manager(self, ctx: commands.Context) -> bool:
        if self._is_manager(ctx):
            return True
        await ctx.send("⛔ You need **Manage Server** to use that Minecraft manager command.")
        return False

    async def _data_error(self, ctx: commands.Context, exc: Exception) -> None:
        text = str(exc)
        if "not configured" in text.lower() or "must both be set" in text.lower():
            await ctx.send(
                "🗄️ **The Plug's Minecraft database isn't connected yet.**\n"
                "Add `MINECRAFT_TURSO_DATABASE_URL` and `MINECRAFT_TURSO_AUTH_TOKEN` "
                "to the Discloud app, then restart The Plug."
            )
            return
        logger.warning("Minecraft data operation failed: %s", exc)
        await ctx.send("❌ The Minecraft data service is temporarily unavailable.")

    async def _server_or_message(self, ctx: commands.Context) -> dict[str, Any] | None:
        try:
            server = await self.data.get_server(ctx.guild.id)
        except MinecraftDataUnavailable as exc:
            await self._data_error(ctx, exc)
            return None
        if server is None:
            await ctx.send(
                "⚙️ **Minecraft isn't configured for this Discord server yet.**\n"
                "A manager can run `/minecraft setup`."
            )
            return None
        return server

    async def _resolve_player(
        self,
        ctx: commands.Context,
        player: str | None,
    ) -> dict[str, Any] | None:
        try:
            if player and player.strip():
                row = await self.data.player_by_name(ctx.guild.id, player)
            else:
                row = await self.data.player_by_discord(ctx.guild.id, ctx.author.id)
        except MinecraftDataUnavailable as exc:
            await self._data_error(ctx, exc)
            return None

        if row is not None:
            return row
        if player:
            await ctx.send(f"🔎 I don't have Minecraft data for **{_trim(player, 80)}** yet.")
        else:
            await ctx.send(
                "🔗 I couldn't match your Discord account to a Minecraft player yet. "
                "During the migration, existing DiscordSRV links can be imported by ThePlugBridge; "
                "native The Plug linking comes before DiscordSRV is removed."
            )
        return None

    def _guide_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎮 The Plug — Minecraft Companion",
            description=(
                "Live information for **The 420 Server** without mixing it into the Idle Grow profile system. "
                "Java and Bedrock players use the same command surface."
            ),
            color=GUIDE_COLOR,
        )
        embed.add_field(
            name="Server",
            value=(
                "`/minecraft status` — live server-list status\n"
                "`/minecraft players` — named online roster\n"
                "`/minecraft activity` — recent joins/deaths/advancements\n"
                "`/minecraft health` — Paper/TPS/MSPT health (manager)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Players",
            value=(
                "`/minecraft profile [player]`\n"
                "`/minecraft stats [player]`\n"
                "`/minecraft seen [player]`\n"
                "`/minecraft playtime [player]`\n"
                "`/minecraft whois <player or @member>`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Leaderboards",
            value=(
                "`/minecraft top [playtime|kills|mobs|deaths|jumps|aura]`\n"
                "`/minecraft records`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Prefix shortcuts",
            value=(
                "`!mcstatus` `!mcplayers` `!mcprofile` `!mcstats` `!mcseen` "
                "`!mcplaytime` `!mctop` `!mcrecords` `!mcactivity` `!mcwhois` `!mchealth`"
            ),
            inline=False,
        )
        embed.set_footer(
            text="DiscordSRV remains temporary during migration; The Plug will take features over one at a time."
        )
        return embed

    @commands.hybrid_group(
        name="minecraft",
        invoke_without_command=True,
        description="The Plug's Minecraft companion commands.",
    )
    async def minecraft(self, ctx: commands.Context):
        await ctx.send(embed=self._guide_embed())

    @minecraft.command(name="commands", description="Show the Minecraft command guide.")
    async def minecraft_commands(self, ctx: commands.Context):
        await ctx.send(embed=self._guide_embed())

    @minecraft.command(name="setup", description="Configure this Discord server's Minecraft address.")
    async def minecraft_setup(
        self,
        ctx: commands.Context,
        host: str,
        java_port: int = DEFAULT_JAVA_PORT,
        bedrock_port: int = DEFAULT_BEDROCK_PORT,
        *,
        display_name: str = "The 420 Server",
    ):
        if not await self._need_manager(ctx):
            return
        try:
            row = await self.data.configure_server(
                ctx.guild.id,
                display_name=display_name or "The 420 Server",
                host=host,
                java_port=java_port,
                bedrock_port=bedrock_port,
            )
        except (ValueError, MinecraftDataUnavailable) as exc:
            if isinstance(exc, MinecraftDataUnavailable):
                return await self._data_error(ctx, exc)
            return await ctx.send(f"❌ {exc}")

        ping_text = "⚠️ Java status ping did not answer yet."
        try:
            ping = await ping_java_server(row["host"], int(row["java_port"]))
        except MinecraftPingError:
            pass
        else:
            ping_text = (
                f"✅ Java answered as **{ping['version_name']}** with "
                f"**{ping['players_online']}/{ping['players_max']}** online."
            )

        await ctx.send(
            "✅ **Minecraft companion server saved.**\n"
            f"Java: `{row['host']}:{row['java_port']}`\n"
            f"Bedrock: `{row['host']}:{row['bedrock_port']}`\n"
            f"{ping_text}\n\n"
            "The next deployment step is the restricted **Turso bridge token** for `ThePlugBridge.jar`. "
            "No Supabase key or Discord bot token belongs in the Paper plugin."
        )

    @minecraft.command(name="status", description="Show live Minecraft server status.")
    async def minecraft_status(self, ctx: commands.Context):
        await self._send_status(ctx)

    async def _send_status(self, ctx: commands.Context):
        server = await self._server_or_message(ctx)
        if server is None:
            return
        try:
            ping = await ping_java_server(server["host"], int(server["java_port"]))
        except MinecraftPingError as exc:
            embed = discord.Embed(
                title=f"🔴 {server.get('display_name') or 'Minecraft Server'}",
                description="The Java Server List Ping endpoint did not answer this check.",
                color=ERROR_COLOR,
            )
            embed.add_field(
                name="Endpoint",
                value=f"`{server['host']}:{server['java_port']}`",
                inline=False,
            )
            embed.set_footer(text=_trim(exc, 200))
            return await ctx.send(embed=embed)

        embed = discord.Embed(
            title=f"🟢 {server.get('display_name') or 'Minecraft Server'}",
            description=ping.get("motd") or "Minecraft server is online.",
            color=GUIDE_COLOR,
        )
        embed.add_field(name="Players", value=f"**{ping['players_online']} / {ping['players_max']}**", inline=True)
        embed.add_field(name="Version", value=_trim(ping["version_name"], 80), inline=True)
        embed.add_field(name="Ping", value=f"{ping['latency_ms']:.1f} ms", inline=True)
        embed.add_field(name="Java", value=f"`{server['host']}:{server['java_port']}`", inline=True)
        embed.add_field(name="Bedrock", value=f"`{server['host']}:{server['bedrock_port']}`", inline=True)
        if server.get("bridge_last_seen"):
            embed.add_field(
                name="ThePlugBridge",
                value=f"Last telemetry {discord_timestamp(server['bridge_last_seen'])}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @minecraft.command(name="players", description="Show Minecraft players currently online.")
    async def minecraft_players(self, ctx: commands.Context):
        await self._send_players(ctx)

    async def _send_players(self, ctx: commands.Context):
        server = await self._server_or_message(ctx)
        if server is None:
            return
        try:
            rows = await self.data.list_players(ctx.guild.id, online_only=True, limit=100)
        except MinecraftDataUnavailable as exc:
            return await self._data_error(ctx, exc)

        if not rows:
            try:
                ping = await ping_java_server(server["host"], int(server["java_port"]))
            except MinecraftPingError:
                return await ctx.send("🌙 No players are currently reported online.")
            sample = ping.get("sample_names") or []
            names = "\n" + ", ".join(f"`{_trim(name, 40)}`" for name in sample[:20]) if sample else ""
            return await ctx.send(
                f"👥 **{ping['players_online']}/{ping['players_max']}** online.{names}\n"
                "_ThePlugBridge has not supplied the full named roster yet._"
            )

        lines = []
        for row in rows[:40]:
            linked = " 🔗" if row.get("discord_user_id") else ""
            lines.append(f"{'🟩' if str(row.get('platform')).lower() == 'bedrock' else '☕'} **{_trim(row.get('username') or 'Unknown', 60)}**{linked}")
        embed = discord.Embed(
            title=f"👥 Minecraft Online — {len(rows)}",
            description="\n".join(lines),
            color=INFO_COLOR,
        )
        embed.set_footer(text="🟩 Bedrock • ☕ Java • 🔗 linked to Discord")
        await ctx.send(embed=embed)

    @minecraft.command(name="profile", description="Show a Minecraft player profile.")
    async def minecraft_profile(self, ctx: commands.Context, player: str | None = None):
        await self._send_profile(ctx, player)

    async def _send_profile(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        stats = _stats(row)
        username = str(row.get("username") or "Unknown")
        status = "🟢 Online" if row.get("online") else f"Last seen {discord_timestamp(row.get('last_seen'))}"
        embed = discord.Embed(
            title=f"⛏️ {username}",
            description=f"{_player_platform(row)} • {status}",
            color=INFO_COLOR,
        )
        if row.get("discord_user_id"):
            embed.add_field(name="Discord", value=f"<@{int(row['discord_user_id'])}>", inline=True)
        embed.add_field(name="Playtime", value=format_duration_from_ticks(row.get("playtime_ticks")), inline=True)
        embed.add_field(
            name="Combat",
            value=(
                f"Player kills **{int(stats.get('player_kills') or 0):,}**\n"
                f"Mob kills **{int(stats.get('mob_kills') or 0):,}**\n"
                f"Deaths **{int(stats.get('deaths') or 0):,}**"
            ),
            inline=True,
        )
        if row.get("online"):
            embed.add_field(
                name="Right now",
                value=(
                    f"World **{_trim(row.get('world') or 'Unknown', 60)}**\n"
                    f"Mode **{_trim(row.get('game_mode') or 'Unknown', 30)}**\n"
                    f"Level **{int(row.get('experience_level') or 0)}**"
                ),
                inline=True,
            )
        embed.add_field(
            name=f"✨ AuraSkills • Total {aura_total_level(row)}",
            value=_aura_summary(row),
            inline=False,
        )
        embed.set_footer(text=f"UUID: {row.get('player_uuid') or 'unknown'}")
        await ctx.send(embed=embed)

    @minecraft.command(name="stats", description="Show detailed Minecraft statistics.")
    async def minecraft_stats(self, ctx: commands.Context, player: str | None = None):
        await self._send_stats(ctx, player)

    async def _send_stats(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        stats = _stats(row)
        embed = discord.Embed(title=f"📊 {row.get('username') or 'Unknown'} — Minecraft Stats", color=INFO_COLOR)
        embed.add_field(name="Playtime", value=format_duration_from_ticks(row.get("playtime_ticks")), inline=False)
        embed.add_field(
            name="Combat",
            value=(
                f"👤 Player kills: **{int(stats.get('player_kills') or 0):,}**\n"
                f"👾 Mob kills: **{int(stats.get('mob_kills') or 0):,}**\n"
                f"💀 Deaths: **{int(stats.get('deaths') or 0):,}**\n"
                f"⚔️ Damage dealt: **{int(stats.get('damage_dealt') or 0):,}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Movement",
            value=(
                f"🦘 Jumps: **{int(stats.get('jumps') or 0):,}**\n"
                f"🚶 Walked: **{int(stats.get('walk_cm') or 0) / 100000:.1f} km**\n"
                f"🏃 Sprinted: **{int(stats.get('sprint_cm') or 0) / 100000:.1f} km**\n"
                f"🏊 Swam: **{int(stats.get('swim_cm') or 0) / 100000:.1f} km**"
            ),
            inline=True,
        )
        embed.add_field(name="AuraSkills", value=_aura_summary(row, limit=11), inline=False)
        embed.set_footer(text=f"Last synchronized {discord_timestamp(row.get('updated_at'))}")
        await ctx.send(embed=embed)

    @minecraft.command(name="seen", description="Show when a Minecraft player was last seen.")
    async def minecraft_seen(self, ctx: commands.Context, player: str | None = None):
        await self._send_seen(ctx, player)

    async def _send_seen(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        if row.get("online"):
            await ctx.send(f"🟢 **{row['username']}** is online right now.")
        else:
            await ctx.send(f"👀 **{row['username']}** was last seen {discord_timestamp(row.get('last_seen'))}.")

    @minecraft.command(name="playtime", description="Show a Minecraft player's total playtime.")
    async def minecraft_playtime(self, ctx: commands.Context, player: str | None = None):
        await self._send_playtime(ctx, player)

    async def _send_playtime(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        await ctx.send(f"⏱️ **{row['username']}** — **{format_duration_from_ticks(row.get('playtime_ticks'))}** total playtime.")

    @minecraft.command(name="top", description="Show a Minecraft leaderboard.")
    async def minecraft_top(self, ctx: commands.Context, metric: str = "playtime"):
        await self._send_top(ctx, metric)

    async def _send_top(self, ctx: commands.Context, metric: str):
        key = str(metric or "playtime").lower()
        if key not in TOP_METRICS:
            return await ctx.send("❌ Metric must be one of: " + ", ".join(f"`{name}`" for name in sorted(TOP_METRICS)))
        try:
            ranked = await self.data.top_players(ctx.guild.id, key, limit=10)
        except MinecraftDataUnavailable as exc:
            return await self._data_error(ctx, exc)
        if not ranked:
            return await ctx.send("📭 No Minecraft leaderboard snapshots exist yet.")
        _, label = TOP_METRICS[key]
        medals = ("🥇", "🥈", "🥉")
        lines = []
        for index, (row, value) in enumerate(ranked, start=1):
            prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(f"{prefix} **{_trim(row.get('username') or 'Unknown', 60)}** — {_metric_display(key, value)}")
        await ctx.send(embed=discord.Embed(title=f"🏆 Minecraft Top — {label}", description="\n".join(lines), color=WARN_COLOR))

    @minecraft.command(name="records", description="Show current Minecraft server records.")
    async def minecraft_records(self, ctx: commands.Context):
        await self._send_records(ctx)

    async def _send_records(self, ctx: commands.Context):
        try:
            records = await self.data.records(ctx.guild.id)
        except MinecraftDataUnavailable as exc:
            return await self._data_error(ctx, exc)
        if not any(records.values()):
            return await ctx.send("📭 No Minecraft record snapshots exist yet.")
        labels = {
            "playtime": "⏱️ Playtime",
            "kills": "⚔️ Player Kills",
            "mobs": "👾 Mob Kills",
            "deaths": "💀 Deaths",
            "jumps": "🦘 Jumps",
            "aura": "✨ AuraSkills",
        }
        lines = []
        for metric, label in labels.items():
            item = records.get(metric)
            if item:
                row, value = item
                lines.append(f"{label}: **{row.get('username') or 'Unknown'}** — {_metric_display(metric, value)}")
        await ctx.send(embed=discord.Embed(title="🏅 Minecraft Server Records", description="\n".join(lines), color=WARN_COLOR))

    @minecraft.command(name="activity", description="Show recent Minecraft activity.")
    async def minecraft_activity(self, ctx: commands.Context):
        await self._send_activity(ctx)

    async def _send_activity(self, ctx: commands.Context):
        try:
            rows = await self.data.recent_activity(ctx.guild.id, limit=12)
        except MinecraftDataUnavailable as exc:
            return await self._data_error(ctx, exc)
        if not rows:
            return await ctx.send("📭 No recent Minecraft activity has been captured yet.")
        icons = {"join": "➡️", "quit": "⬅️", "death": "💀", "advancement": "🏆", "kick": "⚠️"}
        lines = []
        for row in rows:
            kind = str(row.get("event_type") or "event").lower()
            detail = str(row.get("detail") or "").strip()
            suffix = f" — {_trim(detail, 120)}" if detail else ""
            lines.append(
                f"{icons.get(kind, '•')} **{_trim(row.get('username') or 'Server', 50)}** "
                f"{kind}{suffix} • {discord_timestamp(row.get('occurred_at'))}"
            )
        await ctx.send(embed=discord.Embed(title="🛰️ Recent Minecraft Activity", description="\n".join(lines), color=INFO_COLOR))

    @minecraft.command(name="whois", description="Resolve a Minecraft player or linked Discord member.")
    async def minecraft_whois(self, ctx: commands.Context, query: str):
        await self._send_whois(ctx, query)

    async def _send_whois(self, ctx: commands.Context, query: str):
        raw = str(query or "").strip()
        match = DISCORD_ID_RE.match(raw)
        discord_id = int(match.group(1)) if match else (int(raw) if raw.isdigit() and len(raw) >= 15 else None)
        try:
            row = (
                await self.data.player_by_discord(ctx.guild.id, discord_id)
                if discord_id
                else await self.data.player_by_name(ctx.guild.id, raw)
            )
        except MinecraftDataUnavailable as exc:
            return await self._data_error(ctx, exc)
        if row is None:
            return await ctx.send(f"🔎 No Minecraft identity matched **{_trim(raw, 80)}**.")
        linked = row.get("discord_user_id")
        embed = discord.Embed(title="🔎 Minecraft Identity", color=INFO_COLOR)
        embed.add_field(name="Minecraft", value=f"**{row.get('username') or 'Unknown'}**", inline=True)
        embed.add_field(name="Platform", value=_player_platform(row), inline=True)
        embed.add_field(name="Discord", value=f"<@{int(linked)}>" if linked else "Not linked yet", inline=False)
        embed.add_field(name="Last Seen", value="Online now" if row.get("online") else discord_timestamp(row.get("last_seen")), inline=True)
        embed.set_footer(text=f"UUID: {row.get('player_uuid') or 'unknown'}")
        await ctx.send(embed=embed)

    @minecraft.command(name="health", description="Show detailed Minecraft server/bridge health.")
    async def minecraft_health(self, ctx: commands.Context):
        await self._send_health(ctx)

    async def _send_health(self, ctx: commands.Context):
        if not await self._need_manager(ctx):
            return
        server = await self._server_or_message(ctx)
        if server is None:
            return
        try:
            ping = await ping_java_server(server["host"], int(server["java_port"]))
            ping_text = f"✅ {ping['latency_ms']:.1f} ms • {ping['players_online']}/{ping['players_max']} online"
        except MinecraftPingError as exc:
            ping_text = f"❌ {_trim(exc, 220)}"

        embed = discord.Embed(title="🩺 Minecraft Server Health", color=INFO_COLOR)
        embed.add_field(name="Java endpoint", value=ping_text, inline=False)
        if server.get("bridge_last_seen"):
            embed.add_field(name="ThePlugBridge", value=f"Last heartbeat {discord_timestamp(server['bridge_last_seen'])}", inline=False)
            embed.add_field(
                name="TPS • 1/5/15m",
                value=" / ".join(
                    f"{float(server.get(key)):.2f}" if server.get(key) is not None else "?"
                    for key in ("tps_1m", "tps_5m", "tps_15m")
                ),
                inline=False,
            )
            embed.add_field(name="MSPT", value=f"{float(server.get('mspt') or 0):.2f} ms", inline=True)
            embed.add_field(
                name="Memory",
                value=f"{float(server.get('memory_used_mb') or 0):.0f}/{float(server.get('memory_max_mb') or 0):.0f} MB",
                inline=True,
            )
            embed.add_field(name="Bedrock online", value=str(int(server.get("bedrock_online") or 0)), inline=True)
            embed.add_field(
                name="Runtime",
                value=(
                    f"Minecraft: **{_trim(server.get('minecraft_version') or 'Unknown', 50)}**\n"
                    f"Paper: **{_trim(server.get('paper_version') or 'Unknown', 80)}**\n"
                    f"Bridge: **{_trim(server.get('bridge_version') or 'Unknown', 30)}**"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Paper telemetry",
                value="Waiting for `ThePlugBridge.jar`; TPS/MSPT/memory will appear after its first Turso heartbeat.",
                inline=False,
            )
        await ctx.send(embed=embed)

    @minecraft.command(name="panel", description="Post and pin a public Minecraft command guide.")
    async def minecraft_panel(self, ctx: commands.Context):
        if not await self._need_manager(ctx):
            return
        sent = await ctx.send(embed=self._guide_embed())
        try:
            member = ctx.guild.me
            if member and isinstance(ctx.channel, discord.TextChannel) and ctx.channel.permissions_for(member).manage_messages:
                await sent.pin(reason="The Plug Minecraft command guide")
        except (discord.DiscordException, AttributeError):
            pass

    # Prefix-only compatibility shortcuts. Generic !help, !players, !profile and !stats
    # remain untouched so DiscordSRV and Idle Grow cannot collide with this module.
    @commands.command(name="mccommands")
    async def mccommands(self, ctx: commands.Context):
        await ctx.send(embed=self._guide_embed())

    @commands.command(name="mcstatus")
    async def mcstatus(self, ctx: commands.Context):
        await self._send_status(ctx)

    @commands.command(name="mcplayers")
    async def mcplayers(self, ctx: commands.Context):
        await self._send_players(ctx)

    @commands.command(name="mcprofile")
    async def mcprofile(self, ctx: commands.Context, *, player: str | None = None):
        await self._send_profile(ctx, player)

    @commands.command(name="mcstats")
    async def mcstats(self, ctx: commands.Context, *, player: str | None = None):
        await self._send_stats(ctx, player)

    @commands.command(name="mcseen")
    async def mcseen(self, ctx: commands.Context, *, player: str | None = None):
        await self._send_seen(ctx, player)

    @commands.command(name="mcplaytime")
    async def mcplaytime(self, ctx: commands.Context, *, player: str | None = None):
        await self._send_playtime(ctx, player)

    @commands.command(name="mctop")
    async def mctop(self, ctx: commands.Context, metric: str = "playtime"):
        await self._send_top(ctx, metric)

    @commands.command(name="mcrecords")
    async def mcrecords(self, ctx: commands.Context):
        await self._send_records(ctx)

    @commands.command(name="mcactivity")
    async def mcactivity(self, ctx: commands.Context):
        await self._send_activity(ctx)

    @commands.command(name="mcwhois")
    async def mcwhois(self, ctx: commands.Context, *, query: str):
        await self._send_whois(ctx, query)

    @commands.command(name="mchealth")
    async def mchealth(self, ctx: commands.Context):
        await self._send_health(ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(Minecraft(bot))
