import random
import time

import discord
from discord.ext import commands, tasks

from utils import SPECIAL_EVENTS, WEATHER_TYPES, get_plant_grow_time


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
        """Update world state and settle expired auctions atomically."""
        async with self.bot.db.lock:
            economy = self.bot.get_cog("Economy")
            if economy is None:
                raise RuntimeError("Economy cog is required for auction settlement")
            await economy._settle_expired_auctions()

            world = self.bot.db.world_state
            current_event = world.get("event")
            now = time.time()

            if current_event:
                event_data = SPECIAL_EVENTS.get(current_event.get("id"))
                if not event_data or now > float(current_event.get("expires", 0)):
                    event_id = current_event.get("id", "unknown")
                    world["event"] = None
                    world["last_event"] = now
                    world["market_multiplier"] = 1.0
                    print(f"🏁 Event Ended: {event_id}")
                else:
                    return

            if not world.get("event") and random.random() < 0.05:
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
                print(f"🚨 EVENT STARTED: {event_id}")
                await self.bot.db.save()
                return

            weather_names = list(WEATHER_TYPES.keys())
            weights = [40] + [10] * (len(weather_names) - 1)
            new_weather = random.choices(weather_names, weights=weights, k=1)[0]
            world["weather"] = new_weather

            fluctuation = random.uniform(0.95, 1.05)
            weather_data = WEATHER_TYPES.get(new_weather, {})
            weather_price_modifier = weather_data.get("price", 1.0)

            district_multiplier = 1.0
            district = world.get("district", {})
            if district.get("owner_crew_id") and now < float(district.get("expires_at", 0)):
                district_multiplier = float(district.get("multiplier", 1.10))

            new_multiplier = fluctuation * weather_price_modifier * district_multiplier
            world["market_multiplier"] = max(0.5, min(3.0, new_multiplier))

            history = world.setdefault("market_history", [])
            history.append({"t": int(now), "m": round(new_multiplier, 2)})
            if len(history) > 24:
                del history[:-24]

            await self.bot.db.save()

        print(f"🌍 World Update: {new_weather} | Market: {int(new_multiplier * 100)}%")

    @game_cycle.before_loop
    async def before_game_cycle(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=2)
    async def notification_check(self):
        """Send ready alerts and mark only successfully delivered notifications."""
        now = time.time()
        pending = []

        async with self.bot.db.lock:
            for user_id, user_data in self.bot.db.data.items():
                if user_id == "__world__":
                    continue
                if not user_data.get("settings", {}).get("notifications", True):
                    continue

                ready_plant_indexes = []
                for index, plant in enumerate(user_data.get("plants", [])):
                    if plant.get("notified"):
                        continue
                    grow_time = get_plant_grow_time(
                        user_data,
                        self.bot.db.world_state,
                        plant,
                    )
                    if now - float(plant.get("planted_at", now)) >= grow_time:
                        ready_plant_indexes.append(index)

                ready_batch_indexes = []
                for index, item in enumerate(user_data.get("processing_queue", [])):
                    if item.get("notified"):
                        continue
                    if now >= float(item.get("finish_time", now + 1)):
                        ready_batch_indexes.append(index)

                if ready_plant_indexes or ready_batch_indexes:
                    pending.append(
                        (
                            int(user_id),
                            ready_plant_indexes,
                            ready_batch_indexes,
                        )
                    )

        for user_id, plant_indexes, batch_indexes in pending:
            notifications = []
            if plant_indexes:
                notifications.append(f"🌿 **{len(plant_indexes)} Plants** are ready!")
            if batch_indexes:
                notifications.append(f"⚗️ **{len(batch_indexes)} Batches** are done!")

            try:
                target = await self.bot.fetch_user(user_id)
                await target.send(
                    embed=discord.Embed(
                        title="📟 Pager Alert",
                        description="\n".join(notifications),
                        color=discord.Color.green(),
                    )
                )
            except discord.DiscordException:
                continue

            async with self.bot.db.lock:
                user_data = self.bot.db.get_user(user_id)
                plants = user_data.get("plants", [])
                queue = user_data.get("processing_queue", [])

                for index in plant_indexes:
                    if index < len(plants):
                        plant = plants[index]
                        grow_time = get_plant_grow_time(
                            user_data,
                            self.bot.db.world_state,
                            plant,
                        )
                        if not plant.get("notified") and now - float(
                            plant.get("planted_at", now)
                        ) >= grow_time:
                            plant["notified"] = True

                for index in batch_indexes:
                    if index < len(queue):
                        item = queue[index]
                        if not item.get("notified") and now >= float(
                            item.get("finish_time", now + 1)
                        ):
                            item["notified"] = True

                await self.bot.db.save()

    @notification_check.before_loop
    async def before_notification_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def status_cycle(self):
        """Rotate the bot's status activity."""
        world = self.bot.db.world_state
        weather = world.get("weather", "Sunny ☀️")
        multiplier = int(float(world.get("market_multiplier", 1.0)) * 100)

        event_name = "None"
        event = world.get("event")
        if isinstance(event, dict):
            event_name = event.get("name", "None")

        statuses = [
            f"Weather: {weather}",
            f"Market: {multiplier}%",
            f"Event: {event_name}",
            "!help | Growing 🌿",
        ]
        await self.bot.change_presence(activity=discord.Game(name=random.choice(statuses)))

    @status_cycle.before_loop
    async def before_status_cycle(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tasks(bot))
