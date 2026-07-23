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

    # ==========================================================
    # 🌍 GAME CYCLE (Weather & Economy) - Every 15 Minutes
    # ==========================================================
    @tasks.loop(minutes=15)
    async def game_cycle(self):
        """Updates weather, economy, and random events."""
        world = self.bot.db.world_state

        current_event = world.get("event")
        now = time.time()

        if current_event:
            evt_data = SPECIAL_EVENTS.get(current_event["id"])
            if not evt_data or now > current_event.get("expires", 0):
                world["event"] = None
                world["last_event"] = now
                world["market_multiplier"] = 1.0
                print(f"🏁 Event Ended: {current_event['id']}")
            else:
                return

        if not world.get("event") and random.random() < 0.05:
            evt_id = random.choice(list(SPECIAL_EVENTS.keys()))
            evt_data = SPECIAL_EVENTS[evt_id]

            world["event"] = {
                "id": evt_id,
                "expires": now + evt_data["duration"],
                "name": evt_data["name"],
            }

            if evt_data["effect"] == "price_up":
                world["market_multiplier"] = 1.5
            elif evt_data["effect"] == "price_down":
                world["market_multiplier"] = 0.6

            print(f"🚨 EVENT STARTED: {evt_id}")
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
        if district.get("owner_crew_id") and now < district.get("expires_at", 0):
            district_multiplier = district.get("multiplier", 1.10)

        new_multiplier = fluctuation * weather_price_modifier * district_multiplier
        world["market_multiplier"] = max(0.5, min(3.0, new_multiplier))

        history = world.setdefault("market_history", [])
        history.append({"t": int(now), "m": round(new_multiplier, 2)})
        if len(history) > 24:
            history.pop(0)

        await self.bot.db.save()
        print(f"🌍 World Update: {new_weather} | Market: {int(new_multiplier * 100)}%")

    @game_cycle.before_loop
    async def before_game_cycle(self):
        await self.bot.wait_until_ready()

    # ==========================================================
    # 🔔 NOTIFICATIONS
    # ==========================================================
    @tasks.loop(minutes=2)
    async def notification_check(self):
        """Checks for ready plants/processing and DMs users."""
        users = self.bot.db.data
        now = time.time()

        for user_id, user_data in users.items():
            if user_id == "__world__":
                continue
            if not user_data.get("settings", {}).get("notifications", True):
                continue

            notifications = []

            ready_plants = 0
            for plant in user_data.get("plants", []):
                if plant.get("notified"):
                    continue
                grow_time = get_plant_grow_time(user_data, self.bot.db.world_state, plant)
                if now - plant["planted_at"] >= grow_time:
                    ready_plants += 1
                    plant["notified"] = True
            if ready_plants > 0:
                notifications.append(f"🌿 **{ready_plants} Plants** are ready!")

            ready_lab = 0
            for item in user_data.get("processing_queue", []):
                if item.get("notified"):
                    continue
                if now >= item["finish_time"]:
                    ready_lab += 1
                    item["notified"] = True
            if ready_lab > 0:
                notifications.append(f"⚗️ **{ready_lab} Batches** are done!")

            if notifications:
                try:
                    target = await self.bot.fetch_user(int(user_id))
                    if target:
                        await target.send(
                            embed=discord.Embed(
                                title="📟 Pager Alert",
                                description="\n".join(notifications),
                                color=discord.Color.green(),
                            )
                        )
                        await self.bot.db.save()
                except discord.DiscordException:
                    pass

    @notification_check.before_loop
    async def before_notification_check(self):
        await self.bot.wait_until_ready()

    # ==========================================================
    # 🔄 STATUS ROTATION
    # ==========================================================
    @tasks.loop(minutes=5)
    async def status_cycle(self):
        """Rotates the bot's status activity."""
        world = self.bot.db.world_state
        weather = world.get("weather", "Sunny ☀️")
        multiplier = int(world.get("market_multiplier", 1.0) * 100)

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
