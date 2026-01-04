import discord
import time
import random
import asyncio
from discord.ext import commands
from utils import (
    db_manager,
    CONCENTRATE_TYPES,
    SafeView,
    jail_guard,
    add_xp,
    add__progress,
    _inv_dict,
    has_item,
    inv_take
)

# ==========================================================
# 🛠️ LOCAL HELPERS
# ==========================================================
def _lab_format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m"
    elif seconds < 86400:
        return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"
    else:
        return f"{int(seconds/86400)}d {int((seconds%86400)/3600)}h"

def _lab_prestige_mult(user):
    """Calculate prestige market multiplier locally."""
    prestige = int(user.get("prestige", 0))
    return 1.0 + (prestige * 0.05)

def _lab_market_value(user, base_value):
    """Calculate estimated value including market and prestige."""
    world = db_manager.world_state
    market_mult = float(world.get("market_multiplier", 1.0))
    prestige_mult = _lab_prestige_mult(user)
    
    # District bonus check
    district_mult = 1.0
    district = world.get("district", {})
    if district.get("owner_crew_id") == user.get("crew_id") and time.time() < district.get("expires_at", 0):
        district_mult = float(district.get("multiplier", 1.10))

    return int(base_value * market_mult * prestige_mult * district_mult)

# ==========================================================
# 🧪 LAB MINIGAME VIEW
# ==========================================================
class LabMinigameView(SafeView):
    def __init__(self, owner_id: int, conc_type: str, amount: int, target_zone: int):
        super().__init__(timeout=15)
        self.owner_id = int(owner_id)
        self.conc_type = str(conc_type)
        self.amount = int(amount)
        self.pressed = False
        self.success = False
        self.progress = 0
        self.target_zone = target_zone
        self._message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Not your lab session.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🧪 EXTRACT NOW!", style=discord.ButtonStyle.danger)
    async def extract(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pressed = True
        self.stop()
        
        # Win condition: Press within target zone + 15% buffer
        if self.target_zone <= self.progress <= (self.target_zone + 15):
            self.success = True
            await interaction.response.edit_message(content=f"✅ **PERFECT EXTRACTION!** Hit at {self.progress}%", view=None)
        else:
            msg = "Too Early!" if self.progress < self.target_zone else "Too Late!"
            await interaction.response.edit_message(content=f"💥 **BOOM!** {msg}", view=None)

# ==========================================================
# 🧪 LAB COG
# ==========================================================
class Lab(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==========================================================
    # ⚗️ PROCESS COMMAND (QUEUE SYSTEM)
    # ==========================================================
    @commands.hybrid_command(name="process", aliases=["cook"])
    async def process(self, ctx, concentrate_type: str = None, amount: str = "1"):
        """
        Process flower into concentrates (Queue System).
        Usage: !process <type> <amount>
        """
        user = self.bot.db.get_user(ctx.author.id)
        
        # 🚔 JAIL CHECK
        if await jail_guard(ctx, user, "process"): 
            return

        # 1. SHOW MENU IF NO TYPE
        if not concentrate_type:
            embed = discord.Embed(title="🧪 **Concentrate Lab (Queue)**", color=0x9b59b6)
            
            # Helper to check inventory
            def check_tool(name): 
                if not name: return True
                return has_item(user, name)

            for conc_name, conc_data in CONCENTRATE_TYPES.items():
                req_tool = conc_data.get("req_item")
                have_it = check_tool(req_tool)
                status = "✅" if have_it else f"🔒 Need {req_tool}"
                
                yield_pct = int(conc_data.get('yield_ratio', 0.15) * 100)
                embed.add_field(
                    name=f"{status} {conc_name.title()}",
                    value=f"**Ratio:** {yield_pct}% Yield\n**Req:** Level {conc_data.get('level_req', 1)}",
                    inline=True
                )
            
            embed.set_footer(text="Use: !process [type] [amount] (e.g. !process wax 10)")
            return await ctx.send(embed=embed)
        
        # 2. VALIDATE INPUT
        c_type = concentrate_type.lower().strip()
        if c_type not in CONCENTRATE_TYPES:
            return await ctx.send(f"❌ **Invalid type.** Options: {', '.join(CONCENTRATE_TYPES.keys())}")
        
        try: 
            qty = int(amount)
        except: 
            qty = 1
        if qty <= 0: return await ctx.send("❌ Amount must be positive.")

        info = CONCENTRATE_TYPES[c_type]
        
        # 3. CHECK LEVEL
        req_lvl = info.get("level_req", 1)
        if user.get("level", 1) < req_lvl:
            return await ctx.send(f"🔒 **Level {req_lvl} Required.**")

        # 4. CHECK TOOL
        tool = info.get("req_item")
        if tool and not has_item(user, tool):
            return await ctx.send(f"🛠️ You need a **{tool.title()}** to make this.")

        # 5. CHECK RESOURCES
        ratio = info.get("yield_ratio", 0.1)
        needed_flower = int(qty / ratio)
        
        stash = user.get("flower_stash", {})
        total_flower = sum(stash.values())
        
        if total_flower < needed_flower:
            return await ctx.send(f"🌿 **Not enough flower.** Need {needed_flower}g total (You have {total_flower}g).")

        # 6. CONSUME FLOWER (Iterate stash to remove needed amount)
        removed = 0
        to_remove = needed_flower
        
        for strain in list(stash.keys()):
            if removed >= to_remove: break
            
            have = stash[strain]
            take = min(have, to_remove - removed)
            
            stash[strain] -= take
            removed += take
            
            if stash[strain] <= 0:
                del stash[strain]

        # 7. QUEUE PROCESS
        # Processing time: 5 mins per unit (300s)
        duration = 300 * qty 
        
        queue_item = {
            "type": c_type,
            "amount": qty,
            "start_time": time.time(),
            "finish_time": time.time() + duration,
            "flower_used": removed
        }
        
        user.setdefault("processing_queue", []).append(queue_item)
        
        # Update Stats
        add__progress(user, "process_dabs", qty)
            
        await self.bot.db.save()
        
        embed = discord.Embed(
            title="⚗️ **Extraction Started**",
            description=f"Processing **{removed}g flower** into **{qty}g {c_type.title()}**.",
            color=0xe67e22
        )
        embed.add_field(name="⏳ Time", value=f"{int(duration/60)} minutes", inline=True)
        await ctx.send(embed=embed)

    # ==========================================================
    # 🧪 CONC COMMAND (INVENTORY)
    # ==========================================================
    @commands.command(name="conc")
    async def conc(self, ctx, user_target: discord.Member = None):
        """View your concentrates and processing queue."""
        target = user_target or ctx.author
        player = self.bot.db.get_user(target.id)
        
        # Init safely
        player.setdefault("concentrates", {})
        player.setdefault("processing_queue", [])
        player.setdefault("stats", {})

        if not player["concentrates"] and not player["processing_queue"]:
            if target == ctx.author:
                return await ctx.send("🧪 **No concentrates yet!** Use `!process` to make some.")
            return await ctx.send(f"🧪 **{target.display_name}** has no concentrates.")
        
        embed = discord.Embed(
            title=f"🧪 {target.display_name}'s Concentrates",
            color=0x9b59b6
        )
        
        # --- Current Stock ---
        if player["concentrates"]:
            conc_text = ""
            total_value = 0

            for conc_type, amount in player["concentrates"].items():
                if amount > 0:
                    base_value = 500  # Base standard value
                    conc_data = CONCENTRATE_TYPES.get(conc_type, {"value_mult": 3.0})

                    # Calculate value
                    base_price_per_g = base_value * conc_data.get("value_mult", 3.0)
                    base_total = base_price_per_g * amount
                    
                    # Apply market/prestige logic for preview
                    final_val = _lab_market_value(player, base_total)
                    total_value += final_val

                    conc_text += f"**{conc_type.title()}:** {amount}g (≈${final_val:,})\n"

            if conc_text:
                embed.add_field(name="📦 **In Stock**", value=conc_text, inline=False)
                embed.add_field(name="💰 **Total Value**", value=f"≈${total_value:,}", inline=True)

        # --- Processing Queue ---
        if player["processing_queue"]:
            queue_text = ""
            for item in player["processing_queue"][:5]:  # Show first 5
                time_left = item["finish_time"] - time.time()
                if time_left > 0:
                    queue_text += f"**{item['type'].title()}:** {item['amount']}g - {_lab_format_time(time_left)} left\n"

            if queue_text:
                embed.add_field(name="⚗️ **Processing**", value=queue_text, inline=False)

            if len(player["processing_queue"]) > 5:
                embed.set_footer(text=f"+{len(player['processing_queue']) - 5} more in queue")

        await ctx.send(embed=embed)

    # ==========================================================
    # 💥 LAB MINIGAME COMMAND
    # ==========================================================
    @commands.hybrid_command(name="lab")
    async def lab(self, ctx, conc_type: str = "shatter", amount: int = 10):
        """Play the manual extraction minigame for instant processing."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "lab"): return

        c_type = conc_type.lower().strip()
        if c_type not in CONCENTRATE_TYPES:
            return await ctx.send(f"❌ Unknown type. Options: {', '.join(CONCENTRATE_TYPES.keys())}")
            
        info = CONCENTRATE_TYPES[c_type]
        
        # Requirements
        req_item = info.get("req_item")
        if req_item and not has_item(user, req_item):
            return await ctx.send(f"❌ You need a **{req_item.title()}**.")
        if user.get("level", 1) < info.get("level_req", 1):
            return await ctx.send(f"🔒 Level {info.get('level_req')} required.")

        # Resources
        # Manual extraction is slightly more efficient (10% bonus efficiency)
        ratio = info.get("yield_ratio", 0.1)
        needed_flower = int(amount / (ratio * 1.1)) 
        
        stash = user.get("flower_stash", {})
        if sum(stash.values()) < needed_flower:
            return await ctx.send(f"🌿 **Not enough flower.** Need {needed_flower}g.")

        # Start Game
        target = random.randint(40, 75)
        view = LabMinigameView(ctx.author.id, c_type, amount, target)
        msg = await ctx.send(f"⚗️ **Extraction Started: {c_type.title()}**\nTarget: **{target}% - {target+15}%**", view=view)
        view._message = msg
        
        # Animation Loop
        for i in range(0, 105, 5):
            if view.pressed: break
            view.progress = i
            
            # Visual Bar
            slots = 20
            pos = int((i/100)*slots)
            # Create dynamic bar string
            chars = []
            for k in range(slots):
                zone_val = k * 5
                if k == pos: chars.append("🔘")
                elif target <= zone_val <= (target + 15): chars.append("🟩")
                else: chars.append("➖")
            line = "".join(chars)
            
            try: await msg.edit(content=f"⚗️ Pressure: **{i}%**\n`[{line}]`")
            except: break
            
            # Speed up as it gets higher
            await asyncio.sleep(0.5 if i < 50 else 0.3)

        if not view.pressed and not view.success:
            await msg.edit(content="💥 **Timeout!** Batch ruined.", view=None)
            return

        # Result Logic
        if view.success:
            # Remove flower from stash
            removed = 0
            for strain in list(stash.keys()):
                if removed >= needed_flower: break
                take = min(stash[strain], needed_flower - removed)
                stash[strain] -= take
                removed += take
                if stash[strain] <= 0: del stash[strain]
                
            user.setdefault("concentrates", {})
            user["concentrates"][c_type] = user["concentrates"].get(c_type, 0) + amount
            
            # XP and Stats
            await add_xp(ctx, user, amount * 5, f"lab {c_type}")
            add__progress(user, "process_dabs", amount)
            
            user.setdefault("stats", {})
            user["stats"]["concentrate_made"] = user["stats"].get("concentrate_made", 0) + amount
            
            await ctx.send(f"💎 **Success!** Created **{amount}g {c_type.title()}**.")
        else:
            # Failure penalty: Lose 20% of required flower
            loss = int(needed_flower * 0.2)
            removed = 0
            for strain in list(stash.keys()):
                if removed >= loss: break
                take = min(stash[strain], loss - removed)
                stash[strain] -= take
                removed += take
                if stash[strain] <= 0: del stash[strain]
            await ctx.send(f"💥 **Failed!** Lost {removed}g flower.")
        
        await self.bot.db.save()

async def setup(bot):
    await bot.add_cog(Lab(bot))