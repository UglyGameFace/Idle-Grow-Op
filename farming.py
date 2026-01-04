import discord
import time
import random
import math
from discord.ext import commands
from utils import (
    db_manager, 
    GROWTH_CYCLES, 
    SHOP_ITEMS, 
    get_plant_grow_time, 
    jail_guard, 
    inv_take, 
    inv_get,
    check_achievements,
    discord_relative_time
)

class Farming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==========================================================
    # 🆘 HELPER: XP & LEVELING
    # ==========================================================
    async def _add_xp(self, ctx, user, amount):
        """Adds XP and handles level ups."""
        if amount <= 0: return
        user["xp"] = int(user.get("xp", 0)) + int(amount)
        current_level = int(user.get("level", 1))
        
        # Simple formula: Level^1.5 * 100
        req = int(100 * (current_level ** 1.5))
        
        if user["xp"] >= req:
            user["xp"] -= req
            user["level"] = current_level + 1
            await ctx.send(f"🎉 **LEVEL UP!** You are now Level **{user['level']}**!")

    # ==========================================================
    # 🌱 COMMAND: PLANT
    # ==========================================================
    @commands.hybrid_command(name="plant", aliases=["p", "grow"])
    async def plant(self, ctx, *, strain_name: str = ""):
        """
        Plant a seed.
        Usage: !plant og kush
        """
        user = self.bot.db.get_user(ctx.author.id)
        
        # 1. Check Jail / Basic Checks
        if await jail_guard(ctx, user, "plant"): return

        # 2. Validate Input
        if not strain_name:
            return await ctx.send("🌱 **Usage:** `!plant <strain name>` (e.g., `!plant og kush`)")
        
        # Normalize input (users might type "og kush" or "og kush seed")
        clean_name = strain_name.lower().replace(" seed", "").strip()
        seed_item_name = f"{clean_name} seed"

        # 3. Check if Strain Exists
        if clean_name not in GROWTH_CYCLES:
            return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `!strains`.")

        strain_info = GROWTH_CYCLES[clean_name]

        # 4. Check Level Requirement
        if user.get("level", 1) < strain_info.get("level_req", 1):
            return await ctx.send(f"🔒 You need Level **{strain_info['level_req']}** to grow this.")

        # 5. Check Inventory for Seed
        if inv_get(user, seed_item_name) < 1:
            return await ctx.send(f"❌ You don't have any **{clean_name.title()} Seeds**!\nBuy some in the `!shop`.")

        # 6. Check Pot Capacity
        # Default 3 pots, expandable via upgrades
        max_pots = user.get("max_pots", 3)
        current_plants = user.get("plants", [])
        
        if len(current_plants) >= max_pots:
            return await ctx.send(f"🚫 **No Pots Available!** ({len(current_plants)}/{max_pots})\nHarvest plants or buy Pot Upgrades in the shop.")

        # 7. EXECUTE PLANTING
        # Take seed
        inv_take(user, seed_item_name, 1)
        
        # Create plant object
        new_plant = {
            "strain": clean_name,
            "planted_at": time.time(),
            "last_watered": time.time(),
            "water_count": 1,
            "quality": 1.0
        }
        
        user.setdefault("plants", []).append(new_plant)
        await self.bot.db.save()
        
        grow_time = get_plant_grow_time(user, self.bot.db.world_state, new_plant)
        ready_at = int(time.time() + grow_time)
        
        await ctx.send(f"🌱 **Planted:** {clean_name.title()}\n⏳ **Ready:** {discord_relative_time(ready_at)}")

    # ==========================================================
    # 💦 COMMAND: WATER
    # ==========================================================
    @commands.hybrid_command(name="water", aliases=["hydrate"])
    async def water(self, ctx):
        """Water all your plants."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "water"): return

        plants = user.get("plants", [])
        if not plants:
            return await ctx.send("🏜️ You have no plants to water.")

        count = 0
        now = time.time()
        
        for p in plants:
            # Only water if it's been more than 5 minutes to prevent spam farming stats
            if now - p.get("last_watered", 0) > 300:
                p["last_watered"] = now
                p["water_count"] = p.get("water_count", 0) + 1
                count += 1
        
        if count > 0:
            await self.bot.db.save()
            await ctx.send(f"💦 **Watered {count} plants.** Keep 'em happy!")
        else:
            await ctx.send("💧 Plants are already wet enough.")

    # ==========================================================
    # ✂️ COMMAND: HARVEST
    # ==========================================================
    @commands.hybrid_command(name="harvest", aliases=["h"])
    async def harvest(self, ctx):
        """Harvest all ready plants."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "harvest"): return

        plants = user.get("plants", [])
        if not plants:
            return await ctx.send("🌱 You have no plants.")

        ready_plants = []
        remaining_plants = []
        
        total_yield = 0
        total_xp = 0
        harvested_names = []

        now = time.time()
        world = self.bot.db.world_state

        # Check each plant
        for p in plants:
            g_time = get_plant_grow_time(user, world, p)
            if now - p["planted_at"] >= g_time:
                # IT IS READY
                strain_data = GROWTH_CYCLES.get(p["strain"], {})
                
                # Calculate Yield
                min_y, max_y = strain_data.get("yield", (5, 10))
                
                # Apply Equipment Multipliers (simplified logic)
                mult = 1.0
                if inv_get(user, "led lights") > 0: mult += 0.5
                if inv_get(user, "hydroponic") > 0: mult += 1.0
                
                # Random roll
                base_yield = random.randint(min_y, max_y)
                final_yield = int(base_yield * mult)
                
                total_yield += final_yield
                
                # Calculate XP (Based on grow time roughly)
                xp_gain = int(g_time / 100) + 5
                total_xp += xp_gain
                
                harvested_names.append(p["strain"])
            else:
                remaining_plants.append(p)

        if not harvested_names:
            return await ctx.send("⏳ **Nothing is ready to harvest yet.**\nUse `!status` to check remaining time.")

        # Commit Changes
        user["plants"] = remaining_plants
        user["grams"] = int(user.get("grams", 0) + total_yield) # Storing weed as "grams" (conceptually) or just adding to inventory?
        # NOTE: Your DB schema uses "grams" as money usually, and "flower_stash" for weed.
        # Let's put weed in "flower_stash" so they can sell it later.
        
        for name in harvested_names:
            stash = user.setdefault("flower_stash", {})
            stash[name] = stash.get(name, 0) + (total_yield // len(harvested_names)) # Split yield roughly or calc per plant
            
            # Update Stats
            stats = user.setdefault("stats", {})
            stats["harvested"] = stats.get("harvested", 0) + 1

        # Save & Award XP
        await self._add_xp(ctx, user, total_xp)
        await self.bot.db.save()
        
        # Check Achievements
        await check_achievements(ctx, user)

        # Response
        embed = discord.Embed(title="✂️ Harvest Successful", color=discord.Color.green())
        embed.add_field(name="Yield", value=f"**{total_yield}g** Flower", inline=True)
        embed.add_field(name="XP Gained", value=f"+{total_xp} XP", inline=True)
        embed.add_field(name="Plants", value=f"{', '.join(set(harvested_names))}", inline=False)
        embed.set_footer(text=f"Remaining Plants: {len(remaining_plants)}")
        
        await ctx.send(embed=embed)

    # ==========================================================
    # 📊 COMMAND: STATUS
    # ==========================================================
    @commands.hybrid_command(name="status", aliases=["quickcheck", "check", "garden"])
    async def status(self, ctx):
        """Check your plants' progress."""
        user = self.bot.db.get_user(ctx.author.id)
        plants = user.get("plants", [])
        
        if not plants:
            embed = discord.Embed(title="🌱 Your Garden", description="Empty. Use `!plant` to start growing!", color=0x2f3136)
            return await ctx.send(embed=embed)

        embed = discord.Embed(title=f"🌱 {ctx.author.name}'s Garden", color=discord.Color.green())
        now = time.time()
        world = self.bot.db.world_state

        desc_lines = []
        ready_count = 0

        for idx, p in enumerate(plants):
            strain_key = p["strain"]
            g_time = get_plant_grow_time(user, world, p)
            elapsed = now - p["planted_at"]
            
            pct = min(100, int((elapsed / g_time) * 100))
            
            # Progress Bar
            filled = int(pct / 10)
            bar = "🟩" * filled + "⬛" * (10 - filled)
            
            status_text = f"**{pct}%**"
            if pct >= 100:
                status_text = "✅ **READY**"
                ready_count += 1
            else:
                rem_seconds = g_time - elapsed
                m, s = divmod(rem_seconds, 60)
                status_text += f" ({int(m)}m left)"

            desc_lines.append(f"**{idx+1}. {strain_key.title()}**\n{bar} {status_text}")

        embed.description = "\n\n".join(desc_lines)
        if ready_count > 0:
            embed.set_footer(text=f"{ready_count} plants ready! Type !harvest")
        
        await ctx.send(embed=embed)

    # ==========================================================
    # 📖 COMMAND: STRAINS
    # ==========================================================
    @commands.hybrid_command(name="strains", aliases=["seeds"])
    async def strains(self, ctx):
        """List all available strains info."""
        embed = discord.Embed(title="🧬 Strain Database", color=discord.Color.purple())
        
        # Sort by level requirement
        sorted_strains = sorted(GROWTH_CYCLES.items(), key=lambda x: x[1]['level_req'])
        
        for name, data in sorted_strains:
            embed.add_field(
                name=f"Lv{data['level_req']} {data['display_name']}",
                value=f"⏱️ {int(data['time']/60)}m | 📦 Yield: {data['yield'][0]}-{data['yield'][1]}g",
                inline=True
            )
            
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Farming(bot))