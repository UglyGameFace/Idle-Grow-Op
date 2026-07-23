import discord
import asyncio
import random
import time
import json
import os
from discord.ext import commands, tasks
from utils import (
    db_manager,
    WEATHER_TYPES,
    SPECIAL_EVENTS,
    GROWTH_CYCLES,
    get_plant_grow_time
)

class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Start background loops only after Discord has initialized the client."""
        if not self.game_cycle.is_running():
            self.game_cycle.start()
        if not self.notification_check.is_running():
            self.notification_check.start()
        if not self.status_cycle.is_running():
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
        
        # 1. EVENT CHECK
        current_event = world.get("event")
        now = time.time()
        
        if current_event:
            # Check if event expired
            evt_data = SPECIAL_EVENTS.get(current_event["id"])
            if not evt_data or now > current_event.get("expires", 0):
                world["event"] = None
                world["last_event"] = now
                world["market_multiplier"] = 1.0
                print(f"🏁 Event Ended: {current_event['id']}")
            else:
                return 
        
        # 2. TRIGGER NEW EVENT
        if not world.get("event") and random.random() < 0.05:
            evt_id = random.choice(list(SPECIAL_EVENTS.keys()))
            evt_data = SPECIAL_EVENTS[evt_id]
            
            world["event"] = {
                "id": evt_id,
                "expires": now + evt_data["duration"],
                "name": evt_data["name"]
            }
            
            if evt_data["effect"] == "price_up":
                world["market_multiplier"] = 1.5
            elif evt_data["effect"] == "price_down":
                world["market_multiplier"] = 0.6
                
            print(f"🚨 EVENT STARTED: {evt_id}")
            await self.bot.db.save()
            return

        # 3. WEATHER CYCLE
        weather_names = list(WEATHER_TYPES.keys())
        weights = [40] + [10] * (len(weather_names) - 1) 
        new_weather = random.choices(weather_names, weights=weights, k=1)[0]
        world["weather"] = new_weather
        
        # 4. MARKET FLUCTUATION
        fluctuation = random.uniform(0.95, 1.05)
        w_data = WEATHER_TYPES.get(new_weather, {})
        w_price_mod = w_data.get("price", 1.0)
        
        dist_mult = 1.0
        dist = world.get("district", {})
        if dist.get("owner_crew_id") and now < dist.get("expires_at", 0):
            dist_mult = dist.get("multiplier", 1.10)
            
        new_mult = 1.0 * fluctuation * w_price_mod * dist_mult
        world["market_multiplier"] = max(0.5, min(3.0, new_mult))
        
        history = world.setdefault("market_history", [])
        history.append({"t": int(now), "m": round(new_mult, 2)})
        if len(history) > 24: history.pop(0)
        
        await self.bot.db.save()
        print(f"🌍 World Update: {new_weather} | Market: {int(new_mult*100)}%")

    # ==========================================================
    # 🔔 NOTIFICATIONS
    # ==========================================================
    @tasks.loop(minutes=2)
    async def notification_check(self):
        """Checks for ready plants/processing and DMs users."""
        users = self.bot.db.data
        now = time.time()
        
        for user_id, user_data in users.items():
            if user_id == "__world__": continue
            if not user_data.get("settings", {}).get("notifications", True): continue
                
            notifications = []
            
            # Plants
            plants = user_data.get("plants", [])
            ready_plants = 0
            for p in plants:
                if p.get("notified"): continue
                g_time = get_plant_grow_time(user_data, self.bot.db.world_state, p)
                if now - p["planted_at"] >= g_time:
                    ready_plants += 1
                    p["notified"] = True
            if ready_plants > 0:
                notifications.append(f"🌿 **{ready_plants} Plants** are ready!")

            # Lab
            queue = user_data.get("processing_queue", [])
            ready_lab = 0
            for item in queue:
                if item.get("notified"): continue
                if now >= item["finish_time"]:
                    ready_lab += 1
                    item["notified"] = True
            if ready_lab > 0:
                notifications.append(f"⚗️ **{ready_lab} Batches** are done!")

            if notifications:
                try:
                    target = await self.bot.fetch_user(int(user_id))
                    if target:
                        await target.send(embed=discord.Embed(
                            title="📟 Pager Alert", 
                            description="\n".join(notifications), 
                            color=discord.Color.green()
                        ))
                        await self.bot.db.save()
                except:
                    pass

    # ==========================================================
    # 🔄 STATUS ROTATION
    # ==========================================================
    @tasks.loop(minutes=5)
    async def status_cycle(self):
        """Rotates the bot's status activity."""
        world = self.bot.db.world_state
        weather = world.get("weather", "Sunny ☀️")
        mult = int(world.get("market_multiplier", 1.0) * 100)
        
        # FIX: Safe Event Name Check
        evt_name = "None"
        evt = world.get("event")
        if evt and isinstance(evt, dict):
            evt_name = evt.get("name", "None")

        statuses = [
            f"Weather: {weather}",
            f"Market: {mult}%",
            f"Event: {evt_name}",
            "!help | Growing 🌿"
        ]
        
        await self.bot.change_presence(activity=discord.Game(name=random.choice(statuses)))

async def setup(bot):
    await bot.add_cog(Tasks(bot))
