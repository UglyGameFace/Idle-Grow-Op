import random
import time

import discord
from discord.ext import commands, tasks

from utils import SPECIAL_EVENTS, WEATHER_TYPES, get_plant_grow_time
from world_modes import (
    OPEN_WORLD_SCOPE_ID,
    normalize_world_mode_config,
    policy_allows_open_world,
    policy_uses_local_world,
    resolve_game_scope,
)


NOTIFICATION_CANDIDATE_LIMIT = 500
ANNOUNCEMENT_CHANNEL_KEY = "announcement_channel_id"
GAME_CHANNEL_KEY = "game_channel_id"
MAJOR_MARKET_CHANGE = 0.20
MARKET_CHANGE_EPSILON = 1e-9


class _WorldGuildProxy:
    """Use one Discord guild for routing while exposing a shared game scope ID."""

    def __init__(self, primary_guild, scope_id: int, member_guilds) -> None:
        self._primary_guild = primary_guild
        self.id = int(scope_id)
        self.source_guild_id = int(primary_guild.id)
        self.member_guilds = tuple(member_guilds)

    def __getattr__(self, name):
        return getattr(self._primary_guild, name)

    def get_member(self, user_id: int):
        resolved_user_id = int(user_id)
        for guild in self.member_guilds:
            member = guild.get_member(resolved_user_id)
            if member is not None:
                return member
        return None

    async def resolve_player_scope(self, database, user_id: int):
        """Return the shared scope only when the player actively uses it somewhere."""
        resolved_user_id = int(user_id)
        for guild in self.member_guilds:
            if guild.get_member(resolved_user_id) is None:
                continue
            scope = await resolve_game_scope(database, guild.id, resolved_user_id)
            if scope.scope_id == self.id:
                return scope
        return None


class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Start scheduled loops through discord.py's native cog lifecycle."""
        self.game_cycle.start()
        self.notification_check.start()
        self.status_cycle.start()

    def cog_unload(self):
        self.game_cycle.cancel()
        self.notification_check.cancel()
        self.status_cycle.cancel()

    async def _active_cycle_guilds(self):
        """Return local worlds plus servers participating in the shared world."""
        local_guilds = []
        open_world_guilds = []
        for guild in tuple(self.bot.guilds):
            try:
                world = await self.bot.db.get_world(guild.id)
                config = normalize_world_mode_config(world)
                policy = config["policy"]
            except Exception as exc:
                print(f"❌ World mode lookup failed for guild {guild.id}: {exc}")
                continue
            if policy_uses_local_world(policy):
                local_guilds.append(guild)
            if policy_allows_open_world(policy):
                open_world_guilds.append(guild)
        return local_guilds, open_world_guilds

    async def _open_world_notification_guild(self, guilds):
        """Choose one participating guild with a usable announcement route."""
        for guild in guilds:
            if await self._configured_announcement_channel(guild) is not None:
                return guild
        return guilds[0] if guilds else None

    async def _sync_open_world_routing(self, guild) -> None:
        """Keep only the selected guild's channel route in the shared world record."""
        if guild is None:
            return
        async with self.bot.db.lock:
            local_world = await self.bot.db.get_world(guild.id)
            shared_world = await self.bot.db.get_world(OPEN_WORLD_SCOPE_ID)
            local_settings = local_world.get("settings", {}) if isinstance(local_world, dict) else {}
            shared_settings = shared_world.setdefault("settings", {})
            changed = False
            for key in (ANNOUNCEMENT_CHANNEL_KEY, GAME_CHANNEL_KEY):
                value = local_settings.get(key)
                if value:
                    normalized = int(value)
                    if shared_settings.get(key) != normalized:
                        shared_settings[key] = normalized
                        changed = True
                elif key in shared_settings:
                    shared_settings.pop(key, None)
                    changed = True
            if changed:
                self.bot.db.mark_world_dirty(OPEN_WORLD_SCOPE_ID)

    @tasks.loop(minutes=15)
    async def game_cycle(self):
        """Advance every active local world and the shared Open World once."""
        local_guilds, open_world_guilds = await self._active_cycle_guilds()
        cycle_guilds = list(local_guilds)
        open_world_processed = False
        if open_world_guilds:
            if not open_world_processed:
                routing_guild = await self._open_world_notification_guild(open_world_guilds)
                if routing_guild is not None:
                    await self._sync_open_world_routing(routing_guild)
                    cycle_guilds.append(
                        _WorldGuildProxy(
                            routing_guild,
                            OPEN_WORLD_SCOPE_ID,
                            open_world_guilds,
                        )
                    )
                    open_world_processed = True
        await self._run_game_cycle_for(cycle_guilds)

    async def _run_game_cycle_for(self, guilds):
        economy = self.bot.get_cog("Economy")
        if economy is None:
            raise RuntimeError("Economy cog is required for auction settlement")

        updated_worlds = 0
        for guild in guilds:
            scope_id = int(guild.id)
            announcement = None
            try:
                async with self.bot.db.lock:
                    world = await self.bot.db.get_world(scope_id)
                    before = self._world_announcement_snapshot(world)
                    auction_changed = await economy._settle_expired_auctions(scope_id, world)
                    world_changed = self._advance_world(world)
                    if world_changed:
                        self.bot.db.mark_world_dirty(scope_id)
                        announcement = self._build_world_announcement(before, world)
                    if auction_changed or world_changed:
                        updated_worlds += 1
            except Exception as exc:
                print(f"❌ World cycle failed for scope {scope_id}: {exc}")
                continue

            if announcement is not None:
                await self._send_world_announcement(guild, announcement)

        if updated_worlds:
            print(f"🌍 Updated {updated_worlds} active world scope(s)")

    @staticmethod
    def _world_announcement_snapshot(world: dict) -> dict:
        return {
            "event": dict(world.get("event") or {}),
            "weather": world.get("weather"),
            "market_multiplier": float(world.get("market_multiplier", 1.0)),
        }

    @staticmethod
    def _build_world_announcement(before: dict, world: dict) -> discord.Embed | None:
        previous_event = before.get("event") or {}
        current_event = world.get("event") or {}
        previous_multiplier = float(before.get("market_multiplier", 1.0))
        current_multiplier = float(world.get("market_multiplier", 1.0))
        delta = current_multiplier - previous_multiplier

        if not previous_event and current_event:
            return discord.Embed(
                title="🚨 Special World Event Started",
                description=(
                    f"**{current_event.get('name', 'Unknown Event')}** is now active.\n"
                    f"Market multiplier: **{current_multiplier:.2f}x**"
                ),
                color=discord.Color.gold(),
            )

        if previous_event and not current_event:
            return discord.Embed(
                title="✅ Special World Event Ended",
                description=(
                    f"**{previous_event.get('name', 'The event')}** has ended.\n"
                    f"The market is now **{current_multiplier:.2f}x**."
                ),
                color=discord.Color.green(),
            )

        if abs(delta) + MARKET_CHANGE_EPSILON < MAJOR_MARKET_CHANGE:
            return None

        direction = "surged" if delta > 0 else "dropped"
        icon = "📈" if delta > 0 else "📉"
        color = discord.Color.green() if delta > 0 else discord.Color.red()
        return discord.Embed(
            title=f"{icon} Market {direction.title()}",
            description=(
                f"The market {direction} from **{previous_multiplier:.2f}x** "
                f"to **{current_multiplier:.2f}x**.\n"
                f"Weather: **{world.get('weather', 'Unknown')}**"
            ),
            color=color,
        )

    async def _configured_announcement_channel(
        self,
        guild,
    ) -> discord.TextChannel | None:
        try:
            world = await self.bot.db.get_world(guild.id)
        except Exception as exc:
            print(f"❌ Announcement configuration lookup failed for {guild.id}: {exc}")
            return None

        settings = world.get("settings", {})
        announcement_id = settings.get(ANNOUNCEMENT_CHANNEL_KEY)
        channel_id = announcement_id or settings.get(GAME_CHANNEL_KEY)
        if not channel_id:
            return None

        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel) or guild.me is None:
            return None
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            return None
        return channel

    async def _send_world_announcement(
        self,
        guild,
        embed: discord.Embed,
    ) -> None:
        channel = await self._configured_announcement_channel(guild)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            print(f"❌ World announcement failed for scope {guild.id}: {exc}")

    @staticmethod
    def _advance_world(world: dict) -> bool:
        now = time.time()
        changed = False
        current_event = world.get("event")

        if current_event:
            event_data = SPECIAL_EVENTS.get(current_event.get("id"))
            if not event_data or now > float(current_event.get("expires", 0)):
                world["event"] = None
                world["last_event"] = now
                world["market_multiplier"] = 1.0
                changed = True
            else:
                return changed

        if random.random() < 0.05:
            event_id = random.choice(list(SPECIAL_EVENTS.keys()))
            event_data = SPECIAL_EVENTS[event_id]
            world["event"] = {
                "id": event_id,
                "expires": now + event_data["duration"],
                "name": event_data["name"],
            }
            if event_data["effect"] == "price_up":
                world["market_multiplier"] = 1.5
            elif event_data["effect"] == "price_down":
                world["market_multiplier"] = 0.6
            return True

        weather_names = list(WEATHER_TYPES.keys())
        weights = [40] + [10] * (len(weather_names) - 1)
        new_weather = random.choices(weather_names, weights=weights, k=1)[0]
        fluctuation = random.uniform(0.95, 1.05)
        weather_price_modifier = WEATHER_TYPES.get(new_weather, {}).get("price", 1.0)

        district_multiplier = 1.0
        district = world.get("district", {})
        if district.get("owner_crew_id") and now < float(district.get("expires_at", 0)):
            district_multiplier = float(district.get("multiplier", 1.10))

        new_multiplier = max(
            0.5,
            min(3.0, fluctuation * weather_price_modifier * district_multiplier),
        )
        world["weather"] = new_weather
        world["market_multiplier"] = new_multiplier
        history = world.setdefault("market_history", [])
        history.append({"t": int(now), "m": round(new_multiplier, 2)})
        if len(history) > 24:
            del history[:-24]
        return True

    @game_cycle.before_loop
    async def before_game_cycle(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=2)
    async def notification_check(self):
        """Check active local saves and the shared Open World once each."""
        local_guilds, open_world_guilds = await self._active_cycle_guilds()
        notification_guilds = list(local_guilds)
        open_world_processed = False
        if open_world_guilds:
            if not open_world_processed:
                routing_guild = await self._open_world_notification_guild(open_world_guilds)
                if routing_guild is not None:
                    await self._sync_open_world_routing(routing_guild)
                    notification_guilds.append(
                        _WorldGuildProxy(
                            routing_guild,
                            OPEN_WORLD_SCOPE_ID,
                            open_world_guilds,
                        )
                    )
                    open_world_processed = True
        await self._run_notification_check_for(notification_guilds)

    async def _run_notification_check_for(self, guilds):
        now = time.time()
        for guild in guilds:
            scope_id = int(guild.id)
            guild_id = int(getattr(guild, "source_guild_id", guild.id))
            try:
                candidate_ids = await self.bot.db.list_guild_notification_candidates(
                    scope_id,
                    limit=NOTIFICATION_CANDIDATE_LIMIT,
                )
                world = await self.bot.db.get_world(scope_id)
            except Exception as exc:
                print(f"❌ Notification candidate query failed for scope {scope_id}: {exc}")
                continue

            for user_id in candidate_ids:
                resolved_user_id = int(user_id)
                try:
                    if hasattr(guild, "resolve_player_scope"):
                        scope = await guild.resolve_player_scope(self.bot.db, resolved_user_id)
                        if scope is None or scope.scope_id != guild.id:
                            continue
                    else:
                        scope = await resolve_game_scope(
                            self.bot.db,
                            guild_id,
                            resolved_user_id,
                        )
                        if scope.scope_id != guild_id:
                            continue

                    pending = await self._notification_snapshot(
                        scope_id,
                        resolved_user_id,
                        world,
                        now,
                    )
                    if pending is None:
                        continue
                    plant_indexes, batch_indexes = pending
                    target = await self.bot.fetch_user(resolved_user_id)
                    notifications = []
                    if plant_indexes:
                        notifications.append(f"🌿 **{len(plant_indexes)} Plants** are ready!")
                    if batch_indexes:
                        notifications.append(f"⚗️ **{len(batch_indexes)} Batches** are done!")
                    world_name = "Open World" if scope_id == OPEN_WORLD_SCOPE_ID else guild.name
                    await target.send(
                        embed=discord.Embed(
                            title=f"📟 Pager Alert — {world_name}",
                            description="\n".join(notifications),
                            color=discord.Color.green(),
                        )
                    )
                except discord.DiscordException:
                    continue
                except Exception as exc:
                    print(
                        f"❌ Notification check failed for scope {scope_id}, "
                        f"user {resolved_user_id}: {exc}"
                    )
                    continue

                await self._commit_notification_flags(
                    scope_id,
                    resolved_user_id,
                    world,
                    now,
                    plant_indexes,
                    batch_indexes,
                )

    async def _notification_snapshot(
        self,
        scope_id: int,
        user_id: int,
        world: dict,
        now: float,
    ) -> tuple[list[int], list[int]] | None:
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(scope_id, user_id)
            if not profile.get("settings", {}).get("notifications", True):
                return None

            plant_indexes = []
            for index, plant in enumerate(profile.get("plants", [])):
                if plant.get("notified"):
                    continue
                grow_time = get_plant_grow_time(profile, world, plant)
                if now - float(plant.get("planted_at", now)) >= grow_time:
                    plant_indexes.append(index)

            batch_indexes = []
            for index, item in enumerate(profile.get("processing_queue", [])):
                if item.get("notified"):
                    continue
                if now >= float(item.get("finish_time", now + 1)):
                    batch_indexes.append(index)

            if not plant_indexes and not batch_indexes:
                return None
            return plant_indexes, batch_indexes

    async def _commit_notification_flags(
        self,
        scope_id: int,
        user_id: int,
        world: dict,
        now: float,
        plant_indexes: list[int],
        batch_indexes: list[int],
    ) -> None:
        changed = False
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(scope_id, user_id)
            plants = profile.get("plants", [])
            queue = profile.get("processing_queue", [])

            for index in plant_indexes:
                if index >= len(plants):
                    continue
                plant = plants[index]
                grow_time = get_plant_grow_time(profile, world, plant)
                if (
                    not plant.get("notified")
                    and now - float(plant.get("planted_at", now)) >= grow_time
                ):
                    plant["notified"] = True
                    changed = True

            for index in batch_indexes:
                if index >= len(queue):
                    continue
                item = queue[index]
                if (
                    not item.get("notified")
                    and now >= float(item.get("finish_time", now + 1))
                ):
                    item["notified"] = True
                    changed = True

            if changed:
                self.bot.db.mark_profile_dirty(scope_id, user_id)

    @notification_check.before_loop
    async def before_notification_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def status_cycle(self):
        """Rotate status without exposing one server's private world state."""
        server_count = len(self.bot.guilds)
        statuses = [
            f"Growing in {server_count:,} servers 🌿",
            "Solo Grow + Open World 🌍",
            "!help | Build your empire",
        ]
        await self.bot.change_presence(activity=discord.Game(name=random.choice(statuses)))

    @status_cycle.before_loop
    async def before_status_cycle(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tasks(bot))
