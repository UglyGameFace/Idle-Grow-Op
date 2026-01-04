import discord
import random
import time
import asyncio
from discord.ext import commands
# THE FIX: Importing from utils, NOT config
from utils import (
    db_manager, 
    SHOP_ITEMS, 
    GROWTH_CYCLES,
    CONCENTRATE_TYPES,
    SLOTS_SYMBOLS, 
    SLOTS_PAYOUTS, 
    inv_add, 
    inv_get, 
    inv_take,
    jail_guard, 
    _shop_price,
    has_item,
    _norm_item_key
)

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==========================================================
    # 💰 BASIC MONEY COMMANDS
    # ==========================================================
    @commands.hybrid_command(name="balance", aliases=["bal", "cash", "wallet"])
    async def balance(self, ctx, target: discord.User = None):
        target = target or ctx.author
        user = self.bot.db.get_user(target.id)
        grams = user.get("grams", 0)
        dirty = user.get("dirty_cash", 0)
        
        embed = discord.Embed(color=discord.Color.green())
        embed.set_author(name=f"{target.name}'s Wallet", icon_url=target.display_avatar.url)
        embed.add_field(name="💸 Clean Cash", value=f"${grams:,}", inline=True)
        if dirty > 0:
            embed.add_field(name="🧼 Dirty Cash", value=f"${dirty:,}", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="give", aliases=["pay", "transfer"])
    async def give(self, ctx, target: discord.User, amount: int):
        if amount <= 0: return await ctx.send("❌ Amount must be positive.")
        if target.id == ctx.author.id: return await ctx.send("❌ Can't pay yourself.")
        
        sender = self.bot.db.get_user(ctx.author.id)
        receiver = self.bot.db.get_user(target.id)
        
        if await jail_guard(ctx, sender, "trade"): return
        if sender.get("grams", 0) < amount: return await ctx.send("💸 **Insufficient funds.**")
            
        sender["grams"] -= amount
        receiver["grams"] = receiver.get("grams", 0) + amount
        await self.bot.db.save()
        await ctx.send(f"💸 **Transferred:** ${amount:,} to {target.mention}.")

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top", "rich"])
    async def leaderboard(self, ctx):
        all_data = self.bot.db.data
        users = []
        for uid, data in all_data.items():
            if uid.isdigit(): users.append((uid, data.get("grams", 0)))
        
        users.sort(key=lambda x: x[1], reverse=True)
        desc = ""
        for idx, (uid, amt) in enumerate(users[:10]):
            try:
                member = ctx.guild.get_member(int(uid))
                name = member.name if member else f"User {uid}"
            except: name = f"User {uid}"
            emoji = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"#{idx+1}"
            desc += f"{emoji} **{name}**: ${amt:,}\n"
            
        embed = discord.Embed(title="🏆 Global Leaderboard", description=desc, color=discord.Color.gold())
        await ctx.send(embed=embed)

    # ==========================================================
    # 📦 INVENTORY & SHOP
    # ==========================================================
    @commands.hybrid_command(name="inventory", aliases=["inv", "bag", "stash"])
    async def inventory(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)
        
        items_list = user.get("items", {})
        sorted_items = sorted(items_list.items())
        items_desc = "\n".join([f"**{name.title()}**: x{count}" for name, count in sorted_items]) or "Nothing."

        flower_stash = user.get("flower_stash", {})
        sorted_stash = sorted(flower_stash.items())
        stash_desc = "\n".join([f"🌿 **{name.title()}**: {count}g" for name, count in sorted_stash]) or "Empty."
        
        conc_stash = user.get("concentrates", {})
        sorted_conc = sorted(conc_stash.items())
        conc_desc = "\n".join([f"🍯 **{name.title()}**: {count}g" for name, count in sorted_conc]) or "Empty."

        embed = discord.Embed(title=f"🎒 {ctx.author.name}'s Inventory", color=discord.Color.blue())
        embed.add_field(name="💳 Wallet", value=f"${user.get('grams', 0):,}", inline=False)
        embed.add_field(name="📦 Items", value=items_desc, inline=True)
        embed.add_field(name="🧱 Flower", value=stash_desc, inline=True)
        embed.add_field(name="⚗️ Concentrates", value=conc_desc, inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="shop", aliases=["store"])
    async def shop(self, ctx, category: str = "all"):
        embed = discord.Embed(title="🛒 Shop", color=discord.Color.gold())
        def get_cat(n, d):
            t = d.get("type", "misc")
            if "seed" in t: return "seeds"
            if "equipment" in t or "pot" in t or "tool" in t: return "equipment"
            return "misc"

        content = {"seeds": "", "equipment": "", "misc": ""}
        for name, data in SHOP_ITEMS.items():
            cat = get_cat(name, data)
            if category != "all" and category not in cat: continue
            price = _shop_price(data)
            content[cat] += f"• **{name.title()}** — ${price:,}\n"

        if content["seeds"]: embed.add_field(name="🌱 Seeds", value=content["seeds"], inline=False)
        if content["equipment"]: embed.add_field(name="💡 Equipment", value=content["equipment"], inline=False)
        if content["misc"]: embed.add_field(name="🔧 Misc", value=content["misc"], inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="buy")
    async def buy(self, ctx, *, item_name: str):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "buy"): return
        
        clean = item_name.lower().strip()
        if clean not in SHOP_ITEMS: return await ctx.send("❌ Item not found.")
        
        data = SHOP_ITEMS[clean]
        cost = _shop_price(data)
        
        if user.get("grams", 0) < cost: return await ctx.send("💸 Too poor.")
        if user.get("level", 1) < data.get("level_req", 1): return await ctx.send("🔒 Level locked.")
        
        if data.get("type") == "pot_upgrade":
            user["max_pots"] = user.get("max_pots", 3) + 1
        
        user["grams"] -= cost
        inv_add(user, clean, 1)
        await self.bot.db.save()
        await ctx.send(f"✅ Bought **{clean.title()}** for ${cost:,}.")

    # ==========================================================
    # 📉 SELLING & MARKET
    # ==========================================================
    @commands.hybrid_command(name="sell")
    async def sell(self, ctx, amount: str = "all", *, strain_name: str = None):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "sell"): return
        
        world = self.bot.db.world_state
        market_mult = world.get("market_multiplier", 1.0)
        stash = user.get("flower_stash", {})
        total_earnings = 0
        sold_log = []

        def sell_strain(name, qty):
            if qty <= 0: return 0
            g_info = GROWTH_CYCLES.get(name, {"base_value": 10})
            base = g_info.get("base_value", 10)
            
            # Skill Check
            skill_mult = 1.0 
            skills = user.get("skills", {})
            if "dealmaker" in skills: skill_mult += (skills["dealmaker"] * 0.05)

            price_per_g = int(base * market_mult * skill_mult)
            earnings = price_per_g * qty
            
            stash[name] -= qty
            if stash[name] <= 0: del stash[name]
            return earnings

        if amount.lower() == "all":
            items_to_sell = list(stash.items())
            if not items_to_sell: return await ctx.send("🎒 Your flower stash is empty.")
            for name, qty in items_to_sell:
                earn = sell_strain(name, qty)
                total_earnings += earn
                sold_log.append(f"{qty}g {name.title()}")
        else:
            if not strain_name: return await ctx.send("❌ Usage: `!sell <amount> <strain>`")
            try: qty = int(amount)
            except: return await ctx.send("❌ Invalid amount.")
            
            clean_name = strain_name.lower().strip()
            if stash.get(clean_name, 0) < qty: return await ctx.send(f"❌ You don't have {qty}g of {clean_name}.")
            earn = sell_strain(clean_name, qty)
            total_earnings += earn
            sold_log.append(f"{qty}g {clean_name.title()}")

        user["grams"] = int(user.get("grams", 0) + total_earnings)
        stats = user.setdefault("stats", {})
        stats["total_earned"] = stats.get("total_earned", 0) + total_earnings
        
        await self.bot.db.save()
        
        desc = "\n".join(sold_log)
        embed = discord.Embed(title="🤝 Market Sale", color=discord.Color.green())
        embed.add_field(name="Sold", value=desc or "Nothing", inline=False)
        embed.add_field(name="Earnings", value=f"**${total_earnings:,}** (Market: {int(market_mult*100)}%)", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="sellconc")
    async def sellconc(self, ctx, amount: str = "all", *, type_name: str = None):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "sell"): return
        
        conc_stash = user.get("concentrates", {})
        total_earnings = 0
        sold_log = []
        market_mult = self.bot.db.world_state.get("market_multiplier", 1.0)

        def sell_one(c_type, qty):
            c_info = CONCENTRATE_TYPES.get(c_type, {})
            mult = c_info.get("value_mult", 2.0)
            base_price = 50 * mult 
            final_price = int(base_price * market_mult)
            earnings = final_price * qty
            conc_stash[c_type] -= qty
            if conc_stash[c_type] <= 0: del conc_stash[c_type]
            return earnings

        if amount.lower() == "all":
            items = list(conc_stash.items())
            if not items: return await ctx.send("🍯 No concentrates to sell.")
            for c, q in items:
                earn = sell_one(c, q)
                total_earnings += earn
                sold_log.append(f"{q}g {c.title()}")
        else:
            if not type_name: return await ctx.send("❌ Usage: `!sellconc <amount> <type>`")
            try: qty = int(amount)
            except: return await ctx.send("❌ Invalid amount.")
            clean = type_name.lower().strip()
            if conc_stash.get(clean, 0) < qty: return await ctx.send("❌ Not enough.")
            earn = sell_one(clean, qty)
            total_earnings += earn
            sold_log.append(f"{qty}g {clean.title()}")

        user["grams"] += total_earnings
        await self.bot.db.save()
        await ctx.send(f"🍯 Sold **{', '.join(sold_log)}** for **${total_earnings:,}**.")

    # ==========================================================
    # 🔨 AUCTION SYSTEM
    # ==========================================================
    @commands.group(invoke_without_command=True)
    async def auction(self, ctx):
        auctions = self.bot.db.world_state.get("auctions", {})
        if not auctions: return await ctx.send("🔨 **Auction House is closed.** No items listed.")
            
        embed = discord.Embed(title="🔨 Auction House", color=discord.Color.dark_orange())
        for auc_id, data in auctions.items():
            seller = data['seller_name']
            item = data['item_name']
            curr_bid = data['current_bid']
            buyout = data.get('buyout', 'N/A')
            expires = data['end_time']
            time_left = int(expires - time.time())
            
            if time_left > 0:
                m, s = divmod(time_left, 60)
                desc = f"Seller: {seller}\nBid: ${curr_bid:,}\nBuyout: ${buyout}\nEnds in: {m}m {s}s"
                embed.add_field(name=f"ID: {auc_id} | {item}", value=desc, inline=True)
                
        embed.set_footer(text="Use !bid <id> <amount> or !auction list <item> <price> <buyout>")
        await ctx.send(embed=embed)

    @auction.command(name="list")
    async def auction_list(self, ctx, item_name: str, start_price: int, buyout: int = 0):
        user = self.bot.db.get_user(ctx.author.id)
        clean_item = item_name.lower().strip()
        
        if inv_get(user, clean_item) < 1: return await ctx.send(f"❌ You don't have **{clean_item}**.")
        inv_take(user, clean_item, 1)
        
        world = self.bot.db.world_state
        if "auctions" not in world: world["auctions"] = {}
        
        auc_id = str(world.get("auction_counter", 1000) + 1)
        world["auction_counter"] = int(auc_id)
        
        world["auctions"][auc_id] = {
            "seller_id": ctx.author.id,
            "seller_name": ctx.author.name,
            "item_name": clean_item,
            "start_price": start_price,
            "current_bid": start_price,
            "highest_bidder": None,
            "buyout": buyout,
            "end_time": time.time() + 3600
        }
        await self.bot.db.save()
        await ctx.send(f"🔨 **Listed!** {clean_item} for ${start_price}. ID: `{auc_id}`")

    @commands.command(name="bid")
    async def bid(self, ctx, auction_id: str, amount: int):
        world = self.bot.db.world_state
        auctions = world.get("auctions", {})
        if auction_id not in auctions: return await ctx.send("❌ Invalid Auction ID.")
            
        auc = auctions[auction_id]
        user = self.bot.db.get_user(ctx.author.id)
        
        if amount <= auc["current_bid"]: return await ctx.send(f"❌ Bid must be higher than ${auc['current_bid']}.")
        if user.get("grams", 0) < amount: return await ctx.send("💸 Insufficient funds.")
        if auc["seller_id"] == ctx.author.id: return await ctx.send("❌ You can't bid on your own item.")
            
        user["grams"] -= amount
        
        if auc["highest_bidder"]:
            prev_user = self.bot.db.get_user(auc["highest_bidder"])
            prev_user["grams"] += auc["current_bid"]
            
        auc["current_bid"] = amount
        auc["highest_bidder"] = ctx.author.id
        
        if auc["buyout"] > 0 and amount >= auc["buyout"]:
            buyer = self.bot.db.get_user(auc["highest_bidder"])
            inv_add(buyer, auc["item_name"], 1)
            seller = self.bot.db.get_user(auc["seller_id"])
            seller["grams"] += auc["current_bid"]
            del world["auctions"][auction_id]
            await ctx.send(f"🔨 **BOOM!** You bought out the item!")
        else:
            await ctx.send(f"✅ **Bid Placed!** You are leading with ${amount}.")
        await self.bot.db.save()

    # ==========================================================
    # 🎰 MINIGAMES
    # ==========================================================
    @commands.hybrid_command(name="slots")
    async def slots(self, ctx, amount: int = 100):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "gamble"): return
        if amount < 10: return await ctx.send("Min bet 10.")
        if user.get("grams", 0) < amount: return await ctx.send("💸 Broke.")
        
        user["grams"] -= amount
        row = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]
        win = 0
        
        if row[0] == row[1] == row[2]: win = int(amount * SLOTS_PAYOUTS.get(row[0], 2) * 3)
        elif row[0] == row[1] or row[1] == row[2]: win = int(amount * 1.5)
            
        user["grams"] += win
        await self.bot.db.save()
        res = "WIN" if win > 0 else "LOSE"
        await ctx.send(f"🎰 | {' '.join(row)} | **{res}** (${win})")

    @commands.hybrid_command(name="dice")
    async def dice(self, ctx, bet: int = 100):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "gamble"): return
        if user.get("grams", 0) < bet: return await ctx.send("💸 Broke.")
        
        user["grams"] -= bet
        roll = random.randint(1, 100)
        if roll > 50:
            win = int(bet * 1.9)
            user["grams"] += win
            await ctx.send(f"🎲 Rolled **{roll}**. You won ${win}!")
        else:
            await ctx.send(f"🎲 Rolled **{roll}**. You lost.")
        await self.bot.db.save()

async def setup(bot):
    await bot.add_cog(Economy(bot))