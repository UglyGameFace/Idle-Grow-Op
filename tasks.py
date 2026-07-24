import random
import time

import discord
from discord.ext import commands, tasks

from utils import SPECIAL_EVENTS, WEATHER_TYPES, get_plant_grow_time


NOTIFICATION_CANDIDATE_LIMIT = 500


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

    @tasks.loop(minutes=15)
    async def game_cycle(self):
        """Update each connected guild world and settle its auctions atomically."""
        economy = self.bot.get_cog("Economy")
        if economy is None:
            raise RuntimeError("Economy cog is required for auction settlement")

        updated_worlds = 0
        for guild in tuple(self.bot.guilds):
            guild_id = int(guild.id)
            try:
                async with self.bot.db.lock:
                    world = await self.bot.db.get_world(guild_id)
                    auction_changed = await economy._settle_expired_auctions(guild_id, world)
                    world_changed = self._advance_world(world)
                    if world_changed:
                        self.bot.db.mark_world_dirty(guild_id)
                    if auction_changed or world_changed:
                        updated_worlds += 1
            except Exception as exc:
                print(f"❌ Guild world cycle failed for {guild_id}: {exc}")

        if updated_worlds:
            print(f"🌍 Updated {updated_worlds} guild world(s)")

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
        """Notify only indexed active profiles and commit flags after delivery."""
        now = time.time()
        for guild in tuple(self.bot.guilds):
            guild_id = int(guild.id)
            try:
                candidate_ids = await self.bot.db.list_guild_notification_candidates(
                    guild_id,
                    limit=NOTIFICATION_CANDIDATE_LIMIT,
                )
                world = await self.bot.db.get_world(guild_id)
            except Exception as exc:
                print(f"❌ Notification candidate query failed for {guild_id}: {exc}")
                continue

            for user_id in candidate_ids:
                try:
                    pending = await self._notification_snapshot(
                        guild_id,
                        int(user_id),
                        world,
                        now,
                    )
                    if pending is None:
                        continue
                    plant_indexes, batch_indexes = pending
                    target = await self.bot.fetch_user(int(user_id))
                    notifications = []
                    if plant_indexes:
                        notifications.append(f"🌿 **{len(plant_indexes)} Plants** are ready!")
                    if batch_indexes:
                        notifications.append(f"⚗️ **{len(batch_indexes)} Batches** are done!")
                    await target.send(
                        embed=discord.Embed(
                            title=f"📟 Pager Alert — {guild.name}",
                            description="\n".join(notifications),
                            color=discord.Color.green(),
                        )
                    )
                except discord.DiscordException:
                    continue
                except Exception as exc:
                    print(
                        f"❌ Notification check failed for guild {guild_id}, user {user_id}: {exc}"
                    )
                    continue

                await self._commit_notification_flags(
                    guild_id,
                    int(user_id),
                    world,
                    now,
                    plant_indexes,
                    batch_indexes,
                )

    async def _notification_snapshot(
        self,
        guild_id: int,
        user_id: int,
        world: dict,
        now: float,
    ) -> tuple[list[int], list[int]] | None:
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(guild_id, user_id)
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
        guild_id: int,
        user_id: int,
        world: dict,
        now: float,
        plant_indexes: list[int],
        batch_indexes: list[int],
    ) -> None:
        changed = False
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(guild_id, user_id)
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
                self.bot.db.mark_profile_dirty(guild_id, user_id)

    @notification_check.before_loop
    async def before_notification_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def status_cycle(self):
        """Rotate global status without exposing one guild's private world state."""
        server_count = len(self.bot.guilds)
        statuses = [
            f"Growing in {server_count:,} servers 🌿",
            "Guild economies stay local 🏙️",
            "!help | Build your empire",
        ]
        await self.bot.change_presence(activity=discord.Game(name=random.choice(statuses)))

    @status_cycle.before_loop
    async def before_status_cycle(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tasks(bot))
