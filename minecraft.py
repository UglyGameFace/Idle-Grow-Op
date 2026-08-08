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
    metric_value,
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


def _bool_icon(value: bool) -> str:
    return "🟢" if value else "⚫"


def _player_platform(row: dict[str, Any]) -> str:
    platform = str(row.get("platform") or "java").lower()
    return "🟩 Bedrock" if platform == "bedrock" else "☕ Java"


def _stats(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("stats")
    return value if isinstance(value, dict) else {}


def _aura_summary(row: dict[str, Any], *, limit: int = 5) -> str:
    value = row.get("aura_skills")
    if not isinstance(value, dict) or not value:
        return "No AuraSkills data yet."

    pairs = []
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
        return "No AuraSkills data yet."
    return "\n".join(
        f"• **{name.title()}** — Lv. {level}"
        for name, level in pairs[:limit]
    )


def _metric_display(metric: str, value: int) -> str:
    if metric == "playtime":
        return format_duration_from_ticks(value)
    return f"{value:,}"


class Minecraft(commands.Cog):
    """The Plug's Minecraft companion surface."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = MinecraftDataService(self._supabase_client)

    def _supabase_client(self):
        database = getattr(self.bot, "db", None)
        backend = getattr(database, "backend", None)
        return getattr(backend, "client", None)

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.send("❌ Minecraft companion commands only work inside a server.")
            return False
        return True

    @staticmethod
    def _is_manager(ctx: commands.Context) -> bool:
        member = ctx.author
        return isinstance(member, discord.Member) and member.guild_permissions.manage_guild

    async def _need_manager(self, ctx: commands.Context) -> bool:
        if self._is_manager(ctx):
            return True
        await ctx.send("❌ You need **Manage Server** to use that Minecraft admin command.")
        return False

    async def _server_or_message(self, ctx: commands.Context) -> dict[str, Any] | None:
        try:
            server = await self.data.get_server(ctx.guild.id)
        except MinecraftDataUnavailable as exc:
            await ctx.send(f"❌ {exc}")
            return None
        if server is None:
            await ctx.send(
                "⚙️ Minecraft companion setup is not finished yet. "
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
            if player:
                row = await self.data.player_by_name(ctx.guild.id, player)
            else:
                row = await self.data.player_by_discord(ctx.guild.id, ctx.author.id)
        except MinecraftDataUnavailable as exc:
            await ctx.send(f"❌ {exc}")
            return None

        if row is None:
            if player:
                await ctx.send(f"🔎 I don't have Minecraft data for **{_trim(player, 80)}** yet.")
            else:
                await ctx.send(
                    "🔗 I couldn't match your Discord account to a Minecraft player yet.\n"
                    "Join Minecraft and run `/discord link`, then try again after the bridge syncs."
                )
            return None
        return row

    def _guide_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎮 The Plug — Minecraft Commands",
            description=(
                "Live server info, linked-player profiles, stats, leaderboards, "
                "recent activity, and server health — without making you memorize a wall of commands."
            ),
            color=GUIDE_COLOR,
        )
        embed.add_field(
            name="Quick",
            value=(
                "`/minecraft status` — server + player count\n"
                "`/minecraft players` — who's online\n"
                "`/minecraft profile` — your linked profile\n"
                "`/minecraft commands` — this guide"
            ),
            inline=False,
        )
        embed.add_field(
            name="Player Intel",
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
            name="Server Intel",
            value=(
                "`/minecraft top [metric]` — `playtime`, `kills`, `mobs`, `deaths`, `jumps`, `aura`\n"
                "`/minecraft records`\n"
                "`/minecraft activity`\n"
                "`/minecraft health` — managers"
            ),
            inline=False,
        )
        embed.add_field(
            name="Legacy Shortcuts",
            value=(
                "`!mcstatus` `!mcplayers` `!mcprofile` `!mcstats` "
                "`!mcseen` `!mcplaytime` `!mctop` `!mcwhois` "
                "`!mcrecords` `!mcactivity` `!mchealth` `!mccommands`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Minecraft ↔ Discord Link",
            value=(
                "Inside Minecraft run `/discord link`, then privately message the DiscordSRV bot "
                "with the four-digit code. After the server bridge syncs, `/minecraft profile` "
                "can find you automatically."
            ),
            inline=False,
        )
        embed.set_footer(
            text="DiscordSRV's !players and live #minecraft-chat can stay enabled alongside The Plug."
        )
        return embed

    @commands.hybrid_group(
        name="minecraft",
        invoke_without_command=True,
        description="The Plug's Minecraft companion commands.",
    )
    async def minecraft(self, ctx: commands.Context):
        """Show the Minecraft command directory."""
        await ctx.send(embed=self._guide_embed())

    @minecraft.command(name="commands", description="Show all Minecraft companion commands.")
    async def minecraft_commands(self, ctx: commands.Context):
        await ctx.send(embed=self._guide_embed())

    @minecraft.command(name="status", description="Show live Minecraft server status.")
    async def minecraft_status(self, ctx: commands.Context):
        await self._send_status(ctx)

    async def _send_status(self, ctx: commands.Context):
        server = await self._server_or_message(ctx)
        if server is None:
            return

        host = str(server.get("host") or "").strip()
        java_port = int(server.get("java_port") or DEFAULT_JAVA_PORT)
        bedrock_port = int(server.get("bedrock_port") or DEFAULT_BEDROCK_PORT)
        ping = None
        ping_error = None
        if host:
            try:
                ping = await ping_java_server(host, java_port)
            except MinecraftPingError as exc:
                ping_error = str(exc)

        bridge_seen = server.get("bridge_last_seen")
        embed = discord.Embed(
            title=f"🎮 {server.get('display_name') or ctx.guild.name}",
            color=GUIDE_COLOR if ping else WARN_COLOR,
        )
        if host:
            embed.add_field(
                name="Connect",
                value=f"☕ Java: `{host}:{java_port}`\n🟩 Bedrock: `{host}:{bedrock_port}`",
                inline=False,
            )
        if ping:
            embed.add_field(
                name="Live",
                value=(
                    f"🟢 Online • **{ping['players_online']}/{ping['players_max']}** players\n"
                    f"Version: **{_trim(ping['version_name'], 80)}** • Ping: **{ping['latency_ms']} ms**"
                ),
                inline=False,
            )
            if ping.get("motd"):
                embed.add_field(name="MOTD", value=_trim(ping["motd"]), inline=False)
        else:
            embed.add_field(
                name="Live",
                value=f"🔴 Direct Java ping failed: `{_trim(ping_error or 'not configured', 300)}`",
                inline=False,
            )

        bridge_line = (
            f"Last bridge sync {discord_timestamp(bridge_seen)}"
            if bridge_seen
            else "Bridge has not reported yet."
        )
        runtime = []
        if server.get("tps") is not None:
            runtime.append(f"TPS **{float(server['tps']):.2f}**")
        if server.get("mspt") is not None:
            runtime.append(f"MSPT **{float(server['mspt']):.2f}**")
        if server.get("minecraft_version"):
            runtime.append(f"MC **{_trim(server['minecraft_version'], 40)}**")
        embed.add_field(
            name="The Plug Bridge",
            value=bridge_line + (f"\n{' • '.join(runtime)}" if runtime else ""),
            inline=False,
        )
        await ctx.send(embed=embed)

    @minecraft.command(name="players", description="Show Minecraft players currently online.")
    async def minecraft_players(self, ctx: commands.Context):
        await self._send_players(ctx)

    async def _send_players(self, ctx: commands.Context):
        try:
            rows = await self.data.list_players(ctx.guild.id, online_only=True, limit=100)
        except MinecraftDataUnavailable as exc:
            await ctx.send(f"❌ {exc}")
            return

        if not rows:
            server = await self._server_or_message(ctx)
            if server and server.get("host"):
                try:
                    ping = await ping_java_server(
                        server["host"],
                        int(server.get("java_port") or DEFAULT_JAVA_PORT),
                    )
                    sample = ping.get("sample_names") or []
                    detail = (
                        "\n" + ", ".join(f"`{_trim(name, 40)}`" for name in sample[:20])
                        if sample
                        else ""
                    )
                    return await ctx.send(
                        f"👥 **{ping['players_online']}/{ping['players_max']}** online.{detail}\n"
                        "_The bridge has not supplied individual player rows yet._"
                    )
                except MinecraftPingError:
                    pass
            return await ctx.send("🌙 Nobody is reported online right now.")

        lines = []
        for row in rows[:40]:
            linked = " 🔗" if row.get("discord_user_id") else ""
            lines.append(
                f"{_bool_icon(bool(row.get('online')))} **{_trim(row.get('username') or 'Unknown', 60)}** "
                f"• {_player_platform(row)}{linked}"
            )
        embed = discord.Embed(
            title=f"👥 Minecraft Online — {len(rows)}",
            description="\n".join(lines),
            color=GUIDE_COLOR,
        )
        if len(rows) > 40:
            embed.set_footer(text=f"Showing 40 of {len(rows)} online players.")
        await ctx.send(embed=embed)

    @minecraft.command(name="profile", description="Show a linked Minecraft player profile.")
    async def minecraft_profile(self, ctx: commands.Context, player: str | None = None):
        await self._send_profile(ctx, player)

    async def _send_profile(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return

        stats = _stats(row)
        username = str(row.get("username") or "Unknown")
        status_text = "🟢 Online" if row.get("online") else f"Last seen {discord_timestamp(row.get('last_seen'))}"
        embed = discord.Embed(
            title=f"⛏️ {username}",
            description=f"{_player_platform(row)} • {status_text}",
            color=INFO_COLOR,
        )
        discord_id = row.get("discord_user_id")
        if discord_id:
            embed.add_field(name="Discord", value=f"<@{int(discord_id)}>", inline=True)
        embed.add_field(
            name="Playtime",
            value=format_duration_from_ticks(row.get("playtime_ticks")),
            inline=True,
        )
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
                name="Right Now",
                value=(
                    f"World **{_trim(row.get('world') or 'Unknown', 60)}**\n"
                    f"Mode **{_trim(row.get('game_mode') or 'Unknown', 30)}**\n"
                    f"Level **{int(row.get('experience_level') or 0)}**"
                ),
                inline=True,
            )
        embed.add_field(
            name=f"AuraSkills • Total {aura_total_level(row)}",
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
        embed = discord.Embed(
            title=f"📊 {_trim(row.get('username') or 'Unknown', 80)} — Minecraft Stats",
            color=INFO_COLOR,
        )
        embed.add_field(
            name="Time",
            value=f"Playtime **{format_duration_from_ticks(row.get('playtime_ticks'))}**",
            inline=False,
        )
        embed.add_field(
            name="Combat",
            value=(
                f"👤 Player kills: **{int(stats.get('player_kills') or 0):,}**\n"
                f"👾 Mob kills: **{int(stats.get('mob_kills') or 0):,}**\n"
                f"💀 Deaths: **{int(stats.get('deaths') or 0):,}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Movement",
            value=(
                f"🦘 Jumps: **{int(stats.get('jumps') or 0):,}**\n"
                f"🚶 Walked: **{int(stats.get('walk_cm') or 0) / 100000:.1f} km**\n"
                f"🏃 Sprinted: **{int(stats.get('sprint_cm') or 0) / 100000:.1f} km**"
            ),
            inline=True,
        )
        embed.add_field(
            name="AuraSkills",
            value=_aura_summary(row, limit=11),
            inline=False,
        )
        embed.set_footer(text=f"Last synchronized {discord_timestamp(row.get('updated_at'))}")
        await ctx.send(embed=embed)

    @minecraft.command(name="seen", description="Show when a Minecraft player was last seen.")
    async def minecraft_seen(self, ctx: commands.Context, player: str | None = None):
        await self._send_seen(ctx, player)

    async def _send_seen(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        username = str(row.get("username") or "Unknown")
        if row.get("online"):
            await ctx.send(f"🟢 **{username}** is online right now.")
        else:
            await ctx.send(
                f"👀 **{username}** was last seen {discord_timestamp(row.get('last_seen'))}."
            )

    @minecraft.command(name="playtime", description="Show a Minecraft player's total playtime.")
    async def minecraft_playtime(self, ctx: commands.Context, player: str | None = None):
        await self._send_playtime(ctx, player)

    async def _send_playtime(self, ctx: commands.Context, player: str | None):
        row = await self._resolve_player(ctx, player)
        if row is None:
            return
        await ctx.send(
            f"⏱️ **{row.get('username') or 'Unknown'}** — "
            f"**{format_duration_from_ticks(row.get('playtime_ticks'))}** total playtime."
        )

    @minecraft.command(name="top", description="Show a Minecraft leaderboard.")
    async def minecraft_top(self, ctx: commands.Context, metric: str = "playtime"):
        await self._send_top(ctx, metric)

    async def _send_top(self, ctx: commands.Context, metric: str):
        metric = str(metric or "playtime").lower()
        if metric not in TOP_METRICS:
            return await ctx.send(
                "❌ Metric must be one of: "
                + ", ".join(f"`{name}`" for name in sorted(TOP_METRICS))
            )
        try:
            ranked = await self.data.top_players(ctx.guild.id, metric, limit=10)
        except MinecraftDataUnavailable as exc:
            return await ctx.send(f"❌ {exc}")

        if not ranked:
            return await ctx.send("📭 No Minecraft leaderboard data has been collected yet.")

        _, label = TOP_METRICS[metric]
        lines = []
        medals = ("🥇", "🥈", "🥉")
        for index, (row, value) in enumerate(ranked, start=1):
            prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(
                f"{prefix} **{_trim(row.get('username') or 'Unknown', 60)}** — "
                f"{_metric_display(metric, value)}"
            )
        await ctx.send(
            embed=discord.Embed(
                title=f"🏆 Minecraft Top — {label}",
                description="\n".join(lines),
                color=WARN_COLOR,
            )
        )

    @minecraft.command(name="records", description="Show current Minecraft server records.")
    async def minecraft_records(self, ctx: commands.Context):
        await self._send_records(ctx)

    async def _send_records(self, ctx: commands.Context):
        try:
            records = await self.data.records(ctx.guild.id)
        except MinecraftDataUnavailable as exc:
            return await ctx.send(f"❌ {exc}")
        if not any(records.values()):
            return await ctx.send("📭 No Minecraft record data has been collected yet.")

        lines = []
        for metric, label in (
            ("playtime", "⏱️ Playtime"),
            ("kills", "⚔️ Player Kills"),
            ("mobs", "👾 Mob Kills"),
            ("deaths", "💀 Deaths"),
            ("jumps", "🦘 Jumps"),
            ("aura", "✨ AuraSkills"),
        ):
            item = records.get(metric)
            if item is None:
                continue
            row, value = item
            lines.append(
                f"{label}: **{_trim(row.get('username') or 'Unknown', 60)}** — "
                f"{_metric_display(metric, value)}"
            )
        await ctx.send(
            embed=discord.Embed(
                title="🏅 Minecraft Server Records",
                description="\n".join(lines),
                color=WARN_COLOR,
            )
        )

    @minecraft.command(name="activity", description="Show recent Minecraft activity.")
    async def minecraft_activity(self, ctx: commands.Context):
        await self._send_activity(ctx)

    async def _send_activity(self, ctx: commands.Context):
        try:
            rows = await self.data.recent_activity(ctx.guild.id, limit=12)
        except MinecraftDataUnavailable as exc:
            return await ctx.send(f"❌ {exc}")
        if not rows:
            return await ctx.send("📭 No recent Minecraft activity has been captured yet.")

        icons = {
            "join": "➡️",
            "quit": "⬅️",
            "death": "💀",
            "advancement": "🏆",
        }
        lines = []
        for row in rows:
            kind = str(row.get("event_type") or "event").lower()
            icon = icons.get(kind, "•")
            username = _trim(row.get("username") or "Unknown", 50)
            detail = str(row.get("detail") or "").strip()
            suffix = f" — {_trim(detail, 120)}" if detail else ""
            lines.append(
                f"{icon} **{username}** {kind}{suffix} • {discord_timestamp(row.get('occurred_at'))}"
            )
        await ctx.send(
            embed=discord.Embed(
                title="🛰️ Recent Minecraft Activity",
                description="\n".join(lines),
                color=INFO_COLOR,
            )
        )

    @minecraft.command(name="whois", description="Resolve a Minecraft player or linked Discord member.")
    async def minecraft_whois(self, ctx: commands.Context, query: str):
        await self._send_whois(ctx, query)

    async def _send_whois(self, ctx: commands.Context, query: str):
        raw = str(query or "").strip()
        match = DISCORD_ID_RE.match(raw)
        discord_id = None
        if match:
            discord_id = int(match.group(1))
        elif raw.isdigit() and len(raw) >= 15:
            discord_id = int(raw)

        try:
            if discord_id:
                row = await self.data.player_by_discord(ctx.guild.id, discord_id)
            else:
                row = await self.data.player_by_name(ctx.guild.id, raw)
        except MinecraftDataUnavailable as exc:
            return await ctx.send(f"❌ {exc}")

        if row is None:
            return await ctx.send(f"🔎 No linked Minecraft identity matched **{_trim(raw, 80)}**.")

        linked = row.get("discord_user_id")
        embed = discord.Embed(
            title="🔎 Minecraft Identity",
            color=INFO_COLOR,
        )
        embed.add_field(name="Minecraft", value=f"**{row.get('username') or 'Unknown'}**", inline=True)
        embed.add_field(name="Platform", value=_player_platform(row), inline=True)
        embed.add_field(
            name="Discord",
            value=f"<@{int(linked)}>" if linked else "Not linked through DiscordSRV",
            inline=False,
        )
        embed.add_field(
            name="Last Seen",
            value="Online now" if row.get("online") else discord_timestamp(row.get("last_seen")),
            inline=True,
        )
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

        ping_text = "Not tested"
        host = str(server.get("host") or "").strip()
        if host:
            try:
                ping = await ping_java_server(
                    host,
                    int(server.get("java_port") or DEFAULT_JAVA_PORT),
                )
                ping_text = (
                    f"✅ Java ping: {ping['latency_ms']} ms • "
                    f"{ping['players_online']}/{ping['players_max']} online"
                )
            except MinecraftPingError as exc:
                ping_text = f"❌ Java ping: {_trim(exc, 250)}"

        bridge = server.get("bridge_last_seen")
        embed = discord.Embed(title="🩺 Minecraft Server Health", color=INFO_COLOR)
        embed.add_field(name="Network", value=ping_text, inline=False)
        embed.add_field(
            name="Bridge",
            value=(
                f"Last heartbeat {discord_timestamp(bridge)}"
                if bridge
                else "❌ ThePlugBridge has never reported."
            ),
            inline=False,
        )
        embed.add_field(
            name="Server Runtime",
            value=(
                f"TPS: **{float(server.get('tps') or 0):.2f}**\n"
                f"MSPT: **{float(server.get('mspt') or 0):.2f}**\n"
                f"Memory: **{int(server.get('memory_used_mb') or 0):,}/"
                f"{int(server.get('memory_max_mb') or 0):,} MB**\n"
                f"Players: **{int(server.get('online_players') or 0)}/"
                f"{int(server.get('max_players') or 0)}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Versions",
            value=(
                f"Minecraft: **{_trim(server.get('minecraft_version') or 'Unknown', 50)}**\n"
                f"Paper: **{_trim(server.get('paper_version') or 'Unknown', 80)}**\n"
                f"Bridge: **{_trim(server.get('bridge_version') or 'Unknown', 30)}**"
            ),
            inline=True,
        )
        await ctx.send(embed=embed)

    @minecraft.command(name="setup", description="Configure this Discord server's Minecraft address.")
    async def minecraft_setup(
        self,
        ctx: commands.Context,
        host: str,
        java_port: int = DEFAULT_JAVA_PORT,
        bedrock_port: int = DEFAULT_BEDROCK_PORT,
        *,
        display_name: str = "",
    ):
        if not await self._need_manager(ctx):
            return
        try:
            row = await self.data.configure_server(
                ctx.guild.id,
                display_name=display_name or ctx.guild.name,
                host=host,
                java_port=java_port,
                bedrock_port=bedrock_port,
            )
        except (ValueError, MinecraftDataUnavailable) as exc:
            return await ctx.send(f"❌ {exc}")

        await ctx.send(
            "✅ **Minecraft companion server saved.**\n"
            f"Java: `{row['host']}:{row['java_port']}`\n"
            f"Bedrock: `{row['host']}:{row['bedrock_port']}`\n\n"
            "Next: run `/minecraft bridgekey` once, put that secret into "
            "`plugins/ThePlugBridge/config.yml`, then restart Minecraft."
        )

    @minecraft.command(
        name="bridgekey",
        description="Rotate the private ThePlugBridge ingest secret.",
    )
    async def minecraft_bridgekey(self, ctx: commands.Context):
        if not await self._need_manager(ctx):
            return
        if ctx.interaction is None:
            return await ctx.send(
                "🔐 For safety, use the slash command `/minecraft bridgekey` so the secret is private."
            )
        try:
            secret = await self.data.rotate_bridge_secret(ctx.guild.id)
        except MinecraftDataUnavailable as exc:
            return await ctx.send(f"❌ {exc}", ephemeral=True)

        await ctx.send(
            "🔐 **New ThePlugBridge secret generated.**\n"
            "Copy it now into `plugins/ThePlugBridge/config.yml` under `bridge-secret`.\n"
            "Generating another key immediately invalidates this one.\n\n"
            f"```{secret}```",
            ephemeral=True,
        )

    @minecraft.command(
        name="panel",
        description="Post a public Minecraft command guide for members.",
    )
    async def minecraft_panel(self, ctx: commands.Context):
        if not await self._need_manager(ctx):
            return
        sent = await ctx.send(embed=self._guide_embed())
        try:
            member = ctx.guild.me
            if (
                member
                and isinstance(ctx.channel, discord.TextChannel)
                and ctx.channel.permissions_for(member).manage_messages
            ):
                await sent.pin(reason="Minecraft command guide")
        except (discord.DiscordException, AttributeError):
            pass

    # Prefix-only shortcuts. They deliberately avoid !mc, !help, !players, !profile,
    # and !stats so DiscordSRV and Idle Grow's existing command surface cannot collide.
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
