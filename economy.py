import random
import time

import discord
from discord.ext import commands

from economy_integrity import (
    pot_upgrade_capacity,
    require_positive_amount,
    validate_auction_prices,
    validate_bid_amount,
)
from utils import (
    CONCENTRATE_TYPES,
    GROWTH_CYCLES,
    POT_UPGRADE_LIMITS,
    SHOP_ITEMS,
    SLOTS_PAYOUTS,
    SLOTS_SYMBOLS,
    _shop_price,
    inv_add,
    inv_get,
    inv_take,
    jail_guard,
)


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="balance", aliases=["bal", "cash", "wallet"])
    async def balance(self, ctx, target: discord.User = None):
        target = target or ctx.author
        user = self.bot.db.get_user(target.id)
        clean_cash = max(0, int(user.get("grams", 0)))
        dirty_cash = max(0, int(user.get("dirty_cash", 0)))

        embed = discord.Embed(color=discord.Color.green())
        embed.set_author(name=f"{target.name}'s Wallet", icon_url=target.display_avatar.url)
        embed.add_field(name="💸 Clean Cash", value=f"${clean_cash:,}", inline=True)
        if dirty_cash:
            embed.add_field(name="🧼 Dirty Cash", value=f"${dirty_cash:,}", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="give", aliases=["pay", "transfer"])
    async def give(self, ctx, target: discord.User, amount: int):
        try:
            transfer_amount = require_positive_amount(amount)
        except ValueError:
            return await ctx.send("❌ Amount must be a positive whole number.")
        if target.id == ctx.author.id:
            return await ctx.send("❌ Can't pay yourself.")

        sender = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, sender, "trade"):
            return

        async with self.bot.db.lock:
            receiver = self.bot.db.get_user(target.id)
            sender_balance = max(0, int(sender.get("grams", 0)))
            if sender_balance < transfer_amount:
                return await ctx.send("💸 **Insufficient funds.**")
            sender["grams"] = sender_balance - transfer_amount
            receiver["grams"] = max(0, int(receiver.get("grams", 0))) + transfer_amount
            await self.bot.db.save()

        await ctx.send(f"💸 **Transferred:** ${transfer_amount:,} to {target.mention}.")

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top", "rich"])
    async def leaderboard(self, ctx):
        users = []
        for uid, data in self.bot.db.data.items():
            if uid.isdigit():
                users.append((uid, max(0, int(data.get("grams", 0)))))
        users.sort(key=lambda item: item[1], reverse=True)

        lines = []
        for index, (uid, amount) in enumerate(users[:10]):
            member = ctx.guild.get_member(int(uid)) if ctx.guild else None
            name = member.name if member else f"User {uid}"
            rank = "🥇" if index == 0 else "🥈" if index == 1 else "🥉" if index == 2 else f"#{index + 1}"
            lines.append(f"{rank} **{name}**: ${amount:,}")

        embed = discord.Embed(
            title="🏆 Global Leaderboard",
            description="\n".join(lines) or "No players yet.",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="inventory", aliases=["inv", "bag", "stash"])
    async def inventory(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)
        items = user.get("items", {})
        flower = user.get("flower_stash", {})
        concentrates = user.get("concentrates", {})

        items_desc = "\n".join(
            f"**{name.title()}**: x{count}"
            for name, count in sorted(items.items())
            if int(count) > 0
        ) or "Nothing."
        flower_desc = "\n".join(
            f"🌿 **{name.title()}**: {count}g"
            for name, count in sorted(flower.items())
            if int(count) > 0
        ) or "Empty."
        concentrate_desc = "\n".join(
            f"🍯 **{name.title()}**: {count}g"
            for name, count in sorted(concentrates.items())
            if int(count) > 0
        ) or "Empty."

        embed = discord.Embed(title=f"🎒 {ctx.author.name}'s Inventory", color=discord.Color.blue())
        embed.add_field(name="💳 Wallet", value=f"${max(0, int(user.get('grams', 0))):,}", inline=False)
        embed.add_field(name="📦 Items", value=items_desc, inline=True)
        embed.add_field(name="🧱 Flower", value=flower_desc, inline=True)
        embed.add_field(name="⚗️ Concentrates", value=concentrate_desc, inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="shop", aliases=["store"])
    async def shop(self, ctx, category: str = "all"):
        embed = discord.Embed(title="🛒 Shop", color=discord.Color.gold())
        content = {"seeds": "", "equipment": "", "misc": ""}

        for name, data in SHOP_ITEMS.items():
            item_type = data.get("type", "misc")
            if "seed" in item_type:
                item_category = "seeds"
            elif "equipment" in item_type or "pot" in item_type or "tool" in item_type:
                item_category = "equipment"
            else:
                item_category = "misc"
            if category != "all" and category != item_category:
                continue
            content[item_category] += f"• **{name.title()}** — ${_shop_price(data):,}\n"

        if content["seeds"]:
            embed.add_field(name="🌱 Seeds", value=content["seeds"], inline=False)
        if content["equipment"]:
            embed.add_field(name="💡 Equipment", value=content["equipment"], inline=False)
        if content["misc"]:
            embed.add_field(name="🔧 Misc", value=content["misc"], inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="buy")
    async def buy(self, ctx, *, item_name: str):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "buy"):
            return

        clean_name = item_name.lower().strip()
        item = SHOP_ITEMS.get(clean_name)
        if item is None:
            return await ctx.send("❌ Item not found.")

        cost = _shop_price(item)
        if cost < 0:
            return await ctx.send("❌ This item is currently unavailable.")
        if int(user.get("level", 1)) < int(item.get("level_req", 1)):
            return await ctx.send("🔒 Level locked.")

        async with self.bot.db.lock:
            balance = max(0, int(user.get("grams", 0)))
            if balance < cost:
                return await ctx.send("💸 Too poor.")

            new_capacity = None
            if item.get("type") == "pot_upgrade":
                try:
                    new_capacity = pot_upgrade_capacity(user, clean_name, POT_UPGRADE_LIMITS)
                except ValueError:
                    return await ctx.send("🚫 You already own the maximum number of that pot upgrade.")

            user["grams"] = balance - cost
            inv_add(user, clean_name, 1)
            if new_capacity is not None:
                user["max_pots"] = new_capacity
            await self.bot.db.save()

        await ctx.send(f"✅ Bought **{clean_name.title()}** for ${cost:,}.")

    @commands.hybrid_command(name="sell")
    async def sell(self, ctx, amount: str = "all", *, strain_name: str = None):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "sell"):
            return

        market_multiplier = max(0.0, float(self.bot.db.world_state.get("market_multiplier", 1.0)))
        sold_log = []
        total_earnings = 0

        async with self.bot.db.lock:
            stash = user.setdefault("flower_stash", {})
            if amount.lower() == "all":
                sale_items = [(name, max(0, int(qty))) for name, qty in list(stash.items()) if int(qty) > 0]
                if not sale_items:
                    return await ctx.send("🎒 Your flower stash is empty.")
            else:
                if not strain_name:
                    return await ctx.send("❌ Usage: `!sell <amount> <strain>`")
                try:
                    quantity = require_positive_amount(amount)
                except ValueError:
                    return await ctx.send("❌ Amount must be a positive whole number.")
                clean_name = strain_name.lower().strip()
                if max(0, int(stash.get(clean_name, 0))) < quantity:
                    return await ctx.send(f"❌ You don't have {quantity}g of {clean_name}.")
                sale_items = [(clean_name, quantity)]

            skills = user.get("skills", {})
            dealmaker_level = max(0, int(skills.get("dealmaker", 0)))
            skill_multiplier = 1.0 + dealmaker_level * 0.05

            for name, quantity in sale_items:
                base_value = max(0, int(GROWTH_CYCLES.get(name, {"base_value": 10}).get("base_value", 10)))
                unit_price = max(0, int(base_value * market_multiplier * skill_multiplier))
                total_earnings += unit_price * quantity
                stash[name] = max(0, int(stash.get(name, 0))) - quantity
                if stash[name] <= 0:
                    stash.pop(name, None)
                sold_log.append(f"{quantity}g {name.title()}")

            user["grams"] = max(0, int(user.get("grams", 0))) + total_earnings
            stats = user.setdefault("stats", {})
            stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + total_earnings
            await self.bot.db.save()

        embed = discord.Embed(title="🤝 Market Sale", color=discord.Color.green())
        embed.add_field(name="Sold", value="\n".join(sold_log), inline=False)
        embed.add_field(
            name="Earnings",
            value=f"**${total_earnings:,}** (Market: {int(market_multiplier * 100)}%)",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="sellconc")
    async def sellconc(self, ctx, amount: str = "all", *, type_name: str = None):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "sell"):
            return

        market_multiplier = max(0.0, float(self.bot.db.world_state.get("market_multiplier", 1.0)))
        sold_log = []
        total_earnings = 0

        async with self.bot.db.lock:
            stash = user.setdefault("concentrates", {})
            if amount.lower() == "all":
                sale_items = [(name, max(0, int(qty))) for name, qty in list(stash.items()) if int(qty) > 0]
                if not sale_items:
                    return await ctx.send("🍯 No concentrates to sell.")
            else:
                if not type_name:
                    return await ctx.send("❌ Usage: `!sellconc <amount> <type>`")
                try:
                    quantity = require_positive_amount(amount)
                except ValueError:
                    return await ctx.send("❌ Amount must be a positive whole number.")
                clean_name = type_name.lower().strip()
                if max(0, int(stash.get(clean_name, 0))) < quantity:
                    return await ctx.send("❌ Not enough.")
                sale_items = [(clean_name, quantity)]

            for concentrate_type, quantity in sale_items:
                value_multiplier = max(
                    0.0,
                    float(CONCENTRATE_TYPES.get(concentrate_type, {}).get("value_mult", 2.0)),
                )
                unit_price = max(0, int(50 * value_multiplier * market_multiplier))
                total_earnings += unit_price * quantity
                stash[concentrate_type] = max(0, int(stash.get(concentrate_type, 0))) - quantity
                if stash[concentrate_type] <= 0:
                    stash.pop(concentrate_type, None)
                sold_log.append(f"{quantity}g {concentrate_type.title()}")

            user["grams"] = max(0, int(user.get("grams", 0))) + total_earnings
            stats = user.setdefault("stats", {})
            stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + total_earnings
            await self.bot.db.save()

        await ctx.send(f"🍯 Sold **{', '.join(sold_log)}** for **${total_earnings:,}**.")

    async def _settle_expired_auctions(self):
        world = self.bot.db.world_state
        auctions = world.setdefault("auctions", {})
        now = time.time()
        changed = False

        for auction_id, auction in list(auctions.items()):
            if now < float(auction.get("end_time", 0)):
                continue

            seller = self.bot.db.get_user(auction["seller_id"])
            highest_bidder_id = auction.get("highest_bidder")
            if highest_bidder_id is None:
                inv_add(seller, auction["item_name"], 1)
            else:
                buyer = self.bot.db.get_user(highest_bidder_id)
                inv_add(buyer, auction["item_name"], 1)
                seller["grams"] = max(0, int(seller.get("grams", 0))) + max(0, int(auction["current_bid"]))
            del auctions[auction_id]
            changed = True

        if changed:
            await self.bot.db.save()

    @commands.group(invoke_without_command=True)
    async def auction(self, ctx):
        async with self.bot.db.lock:
            await self._settle_expired_auctions()
            auctions = dict(self.bot.db.world_state.get("auctions", {}))

        if not auctions:
            return await ctx.send("🔨 **Auction House is closed.** No items listed.")

        embed = discord.Embed(title="🔨 Auction House", color=discord.Color.dark_orange())
        now = time.time()
        for auction_id, auction in auctions.items():
            seconds_left = max(0, int(float(auction["end_time"]) - now))
            minutes, seconds = divmod(seconds_left, 60)
            buyout = int(auction.get("buyout", 0))
            buyout_text = f"${buyout:,}" if buyout else "N/A"
            description = (
                f"Seller: {auction['seller_name']}\n"
                f"Bid: ${int(auction['current_bid']):,}\n"
                f"Buyout: {buyout_text}\n"
                f"Ends in: {minutes}m {seconds}s"
            )
            embed.add_field(
                name=f"ID: {auction_id} | {auction['item_name']}",
                value=description,
                inline=True,
            )
        embed.set_footer(text="Use !bid <id> <amount> or !auction list <item> <price> <buyout>")
        await ctx.send(embed=embed)

    @auction.command(name="list")
    async def auction_list(self, ctx, item_name: str, start_price: int, buyout: int = 0):
        try:
            valid_start, valid_buyout = validate_auction_prices(start_price, buyout)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}.")

        user = self.bot.db.get_user(ctx.author.id)
        clean_item = item_name.lower().strip()

        async with self.bot.db.lock:
            await self._settle_expired_auctions()
            if inv_get(user, clean_item) < 1:
                return await ctx.send(f"❌ You don't have **{clean_item}**.")
            if not inv_take(user, clean_item, 1):
                return await ctx.send(f"❌ You don't have **{clean_item}**.")

            world = self.bot.db.world_state
            auctions = world.setdefault("auctions", {})
            auction_id = str(int(world.get("auction_counter", 1000)) + 1)
            world["auction_counter"] = int(auction_id)
            auctions[auction_id] = {
                "seller_id": ctx.author.id,
                "seller_name": ctx.author.name,
                "item_name": clean_item,
                "start_price": valid_start,
                "current_bid": valid_start,
                "highest_bidder": None,
                "buyout": valid_buyout,
                "end_time": time.time() + 3600,
            }
            await self.bot.db.save()

        await ctx.send(f"🔨 **Listed!** {clean_item} for ${valid_start:,}. ID: `{auction_id}`")

    @commands.command(name="bid")
    async def bid(self, ctx, auction_id: str, amount: int):
        user = self.bot.db.get_user(ctx.author.id)

        async with self.bot.db.lock:
            await self._settle_expired_auctions()
            auctions = self.bot.db.world_state.setdefault("auctions", {})
            auction = auctions.get(auction_id)
            if auction is None:
                return await ctx.send("❌ Invalid or expired Auction ID.")
            if int(auction["seller_id"]) == ctx.author.id:
                return await ctx.send("❌ You can't bid on your own item.")

            buyout = max(0, int(auction.get("buyout", 0)))
            requested = buyout if buyout and amount >= buyout else amount
            try:
                valid_bid = validate_bid_amount(
                    requested,
                    current_bid=auction["current_bid"],
                    end_time=auction["end_time"],
                    now=time.time(),
                )
            except ValueError as exc:
                return await ctx.send(f"❌ {exc}.")

            previous_bidder_id = auction.get("highest_bidder")
            current_bid = max(0, int(auction["current_bid"]))
            bidder_balance = max(0, int(user.get("grams", 0)))
            required_funds = valid_bid - current_bid if previous_bidder_id == ctx.author.id else valid_bid
            if bidder_balance < required_funds:
                return await ctx.send("💸 Insufficient funds.")

            user["grams"] = bidder_balance - required_funds
            if previous_bidder_id is not None and previous_bidder_id != ctx.author.id:
                previous_bidder = self.bot.db.get_user(previous_bidder_id)
                previous_bidder["grams"] = max(0, int(previous_bidder.get("grams", 0))) + current_bid

            auction["current_bid"] = valid_bid
            auction["highest_bidder"] = ctx.author.id

            bought_out = bool(buyout and valid_bid >= buyout)
            if bought_out:
                inv_add(user, auction["item_name"], 1)
                seller = self.bot.db.get_user(auction["seller_id"])
                seller["grams"] = max(0, int(seller.get("grams", 0))) + valid_bid
                del auctions[auction_id]
            await self.bot.db.save()

        if bought_out:
            await ctx.send(f"🔨 **BOOM!** You bought out the item for ${valid_bid:,}!")
        else:
            await ctx.send(f"✅ **Bid Placed!** You are leading with ${valid_bid:,}.")

    @commands.hybrid_command(name="slots")
    async def slots(self, ctx, amount: int = 100):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "gamble"):
            return
        try:
            bet = require_positive_amount(amount, minimum=10)
        except ValueError:
            return await ctx.send("❌ Minimum bet is $10.")

        async with self.bot.db.lock:
            balance = max(0, int(user.get("grams", 0)))
            if balance < bet:
                return await ctx.send("💸 Broke.")
            user["grams"] = balance - bet
            row = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]
            winnings = 0
            if row[0] == row[1] == row[2]:
                winnings = max(0, int(bet * SLOTS_PAYOUTS.get(row[0], 2) * 3))
            elif row[0] == row[1] or row[1] == row[2]:
                winnings = max(0, int(bet * 1.5))
            user["grams"] += winnings
            await self.bot.db.save()

        result = "WIN" if winnings else "LOSE"
        await ctx.send(f"🎰 | {' '.join(row)} | **{result}** (${winnings:,})")

    @commands.hybrid_command(name="dice")
    async def dice(self, ctx, bet: int = 100):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "gamble"):
            return
        try:
            valid_bet = require_positive_amount(bet, minimum=10)
        except ValueError:
            return await ctx.send("❌ Minimum bet is $10.")

        async with self.bot.db.lock:
            balance = max(0, int(user.get("grams", 0)))
            if balance < valid_bet:
                return await ctx.send("💸 Broke.")
            user["grams"] = balance - valid_bet
            roll = random.randint(1, 100)
            winnings = max(0, int(valid_bet * 1.9)) if roll > 50 else 0
            user["grams"] += winnings
            await self.bot.db.save()

        if winnings:
            await ctx.send(f"🎲 Rolled **{roll}**. You won ${winnings:,}!")
        else:
            await ctx.send(f"🎲 Rolled **{roll}**. You lost.")


async def setup(bot):
    await bot.add_cog(Economy(bot))
