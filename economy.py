import time

import discord
from discord.ext import commands

from economy_integrity import (
    pot_upgrade_capacity,
    require_positive_amount,
    validate_auction_prices,
    validate_bid_amount,
)
from persistence_context import GuildContextRequired, require_guild_id
from utils import (
    CONCENTRATE_TYPES,
    GROWTH_CYCLES,
    POT_UPGRADE_LIMITS,
    SHOP_ITEMS,
    _shop_price,
    inv_add,
    inv_get,
    inv_take,
    jail_guard,
)
from world_modes import (
    WorldModeDenied,
    effective_market_multiplier,
    require_multiplayer,
    require_same_multiplayer_scope,
    resolve_game_scope,
)


class Economy(commands.Cog):
    """Server-local economy, inventory, shop, sales, and auctions."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    async def _profile(self, ctx, user_id=None):
        guild_id = require_guild_id(ctx)
        resolved_user_id = ctx.author.id if user_id is None else int(user_id)
        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)
        profile = await self.bot.db.get_profile(scope.scope_id, resolved_user_id)
        return scope, profile

    async def _world(self, ctx, user_id=None):
        guild_id = require_guild_id(ctx)
        resolved_user_id = ctx.author.id if user_id is None else int(user_id)
        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)
        world = await self.bot.db.get_world(scope.scope_id)
        return scope, world

    @commands.hybrid_command(name="balance", aliases=["bal", "cash", "wallet"])
    async def balance(self, ctx, target: discord.User = None):
        target = target or ctx.author
        scope, user = await self._profile(ctx, target.id)
        clean_cash = max(0, int(user.get("grams", 0)))
        dirty_cash = max(0, int(user.get("dirty_cash", 0)))
        embed = discord.Embed(color=discord.Color.green())
        embed.set_author(name=f"{target.name}'s Wallet", icon_url=target.display_avatar.url)
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
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

        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        target_scope = await resolve_game_scope(self.bot.db, guild_id, target.id)
        try:
            require_same_multiplayer_scope(scope, target_scope, "transfer")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))

        sender = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, sender, "trade"):
            return
        async with self.bot.db.lock:
            receiver = await self.bot.db.get_profile(scope.scope_id, target.id)
            sender_balance = max(0, int(sender.get("grams", 0)))
            if sender_balance < transfer_amount:
                return await ctx.send("💸 **Insufficient funds.**")
            sender["grams"] = sender_balance - transfer_amount
            receiver["grams"] = max(0, int(receiver.get("grams", 0))) + transfer_amount
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)
        await ctx.send(f"💸 **Transferred:** ${transfer_amount:,} to {target.mention}.")

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top", "rich"])
    async def leaderboard(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "leaderboard")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        rows = await self.bot.db.list_guild_leaderboard(scope.scope_id, limit=10)
        lines = []
        for index, row in enumerate(rows):
            user_id = int(row["user_id"])
            amount = max(0, int(row.get("balance", 0)))
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            rank = "🥇" if index == 0 else "🥈" if index == 1 else "🥉" if index == 2 else f"#{index + 1}"
            lines.append(f"{rank} **{name}**: ${amount:,}")
        title = "🏆 Open World Leaderboard" if scope.cross_server else "🏆 Server Leaderboard"
        embed = discord.Embed(
            title=title,
            description="\n".join(lines) or "No players yet.",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="inventory", aliases=["inv", "bag", "stash"])
    async def inventory(self, ctx):
        scope, user = await self._profile(ctx)
        items = user.get("items", {})
        flower = user.get("flower_stash", {})
        concentrates = user.get("concentrates", {})
        items_desc = "\n".join(
            f"**{name.title()}**: x{count}" for name, count in sorted(items.items()) if int(count) > 0
        ) or "Nothing."
        flower_desc = "\n".join(
            f"🌿 **{name.title()}**: {count}g" for name, count in sorted(flower.items()) if int(count) > 0
        ) or "Empty."
        concentrate_desc = "\n".join(
            f"🍯 **{name.title()}**: {count}g"
            for name, count in sorted(concentrates.items())
            if int(count) > 0
        ) or "Empty."
        embed = discord.Embed(title=f"🎒 {ctx.author.name}'s Inventory", color=discord.Color.blue())
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
        embed.add_field(name="💳 Wallet", value=f"${max(0, int(user.get('grams', 0))):,}", inline=False)
        embed.add_field(name="📦 Items", value=items_desc, inline=True)
        embed.add_field(name="🧱 Flower", value=flower_desc, inline=True)
        embed.add_field(name="⚗️ Concentrates", value=concentrate_desc, inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="shop", aliases=["store"])
    async def shop(self, ctx, category: str = "all"):
        category = str(category or "all").lower().strip()
        embed = discord.Embed(title="🛒 Shop", color=discord.Color.gold())
        content = {"seeds": "", "equipment": "", "misc": ""}
        for name, item in SHOP_ITEMS.items():
            item_type = item.get("type", "misc")
            if "seed" in item_type:
                section = "seeds"
            elif any(token in item_type for token in ("equipment", "pot", "tool")):
                section = "equipment"
            else:
                section = "misc"
            if category not in {"all", section}:
                continue
            content[section] += f"• **{name.title()}** — ${_shop_price(item):,}\n"
        for section, title in (("seeds", "🌱 Seeds"), ("equipment", "💡 Equipment"), ("misc", "🔧 Misc")):
            if content[section]:
                embed.add_field(name=title, value=content[section], inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="buy")
    async def buy(self, ctx, *, item_name: str):
        scope, user = await self._profile(ctx)
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
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        await ctx.send(f"✅ Bought **{clean_name.title()}** for ${cost:,}.")

    @commands.hybrid_command(name="sell")
    async def sell(self, ctx, amount: str = "all", *, strain_name: str = None):
        scope, user = await self._profile(ctx)
        if await jail_guard(ctx, user, "sell"):
            return
        world = await self.bot.db.get_world(scope.scope_id)
        market_multiplier = effective_market_multiplier(world, scope)
        district_multiplier = 1.0
        district = world.get("district", {})
        if (
            scope.multiplayer
            and district.get("owner_crew_id") == user.get("crew_id")
            and time.time() < float(district.get("expires_at", 0) or 0)
        ):
            district_multiplier = max(1.0, float(district.get("multiplier", 1.10)))
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
            skill_multiplier = 1.0 + max(0, int(user.get("skills", {}).get("dealmaker", 0))) * 0.05
            for name, quantity in sale_items:
                base_value = max(0, int(GROWTH_CYCLES.get(name, {"base_value": 10}).get("base_value", 10)))
                unit_price = max(
                    0,
                    int(base_value * market_multiplier * district_multiplier * skill_multiplier),
                )
                total_earnings += unit_price * quantity
                stash[name] = max(0, int(stash.get(name, 0))) - quantity
                if stash[name] <= 0:
                    stash.pop(name, None)
                sold_log.append(f"{quantity}g {name.title()}")
            user["grams"] = max(0, int(user.get("grams", 0))) + total_earnings
            stats = user.setdefault("stats", {})
            stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + total_earnings
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
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
        scope, user = await self._profile(ctx)
        if await jail_guard(ctx, user, "sell"):
            return
        world = await self.bot.db.get_world(scope.scope_id)
        market_multiplier = effective_market_multiplier(world, scope)
        district_multiplier = 1.0
        district = world.get("district", {})
        if (
            scope.multiplayer
            and district.get("owner_crew_id") == user.get("crew_id")
            and time.time() < float(district.get("expires_at", 0) or 0)
        ):
            district_multiplier = max(1.0, float(district.get("multiplier", 1.10)))
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
                multiplier = max(0.0, float(CONCENTRATE_TYPES.get(concentrate_type, {}).get("value_mult", 2.0)))
                unit_price = max(
                    0,
                    int(50 * multiplier * market_multiplier * district_multiplier),
                )
                total_earnings += unit_price * quantity
                stash[concentrate_type] = max(0, int(stash.get(concentrate_type, 0))) - quantity
                if stash[concentrate_type] <= 0:
                    stash.pop(concentrate_type, None)
                sold_log.append(f"{quantity}g {concentrate_type.title()}")
            user["grams"] = max(0, int(user.get("grams", 0))) + total_earnings
            stats = user.setdefault("stats", {})
            stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + total_earnings
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        await ctx.send(f"🍯 Sold **{', '.join(sold_log)}** for **${total_earnings:,}**.")

    async def _settle_expired_auctions(self, scope_id: int, world=None):
        world = world if world is not None else await self.bot.db.get_world(scope_id)
        auctions = world.setdefault("auctions", {})
        now = time.time()
        changed = False
        for auction_id, auction in list(auctions.items()):
            if now < float(auction.get("end_time", 0)):
                continue
            seller_id = int(auction["seller_id"])
            seller = await self.bot.db.get_profile(scope_id, seller_id)
            highest_bidder_id = auction.get("highest_bidder")
            if highest_bidder_id is None:
                inv_add(seller, auction["item_name"], 1)
            else:
                buyer_id = int(highest_bidder_id)
                buyer = await self.bot.db.get_profile(scope_id, buyer_id)
                inv_add(buyer, auction["item_name"], 1)
                seller["grams"] = max(0, int(seller.get("grams", 0))) + max(0, int(auction["current_bid"]))
                self.bot.db.mark_profile_dirty(scope_id, buyer_id)
            self.bot.db.mark_profile_dirty(scope_id, seller_id)
            del auctions[auction_id]
            changed = True
        if changed:
            self.bot.db.mark_world_dirty(scope_id)
        return changed

    @commands.group(invoke_without_command=True)
    async def auction(self, ctx):
        scope, world = await self._world(ctx)
        try:
            require_multiplayer(scope, "auction")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        async with self.bot.db.lock:
            await self._settle_expired_auctions(scope.scope_id, world)
            auctions = dict(world.get("auctions", {}))
        if not auctions:
            return await ctx.send("🔨 **Auction House is closed.** No items listed.")
        title = "🔨 Open World Auction House" if scope.cross_server else "🔨 Auction House"
        embed = discord.Embed(title=title, color=discord.Color.dark_orange())
        now = time.time()
        for auction_id, auction in auctions.items():
            minutes, seconds = divmod(max(0, int(float(auction["end_time"]) - now)), 60)
            buyout = int(auction.get("buyout", 0))
            description = (
                f"Seller: {auction['seller_name']}\nBid: ${int(auction['current_bid']):,}\n"
                f"Buyout: {f'${buyout:,}' if buyout else 'N/A'}\nEnds in: {minutes}m {seconds}s"
            )
            embed.add_field(name=f"ID: {auction_id} | {auction['item_name']}", value=description, inline=True)
        embed.set_footer(text="Use !bid <id> <amount> or !auction list <item> <price> <buyout>")
        await ctx.send(embed=embed)

    @auction.command(name="list")
    async def auction_list(self, ctx, item_name: str, start_price: int, buyout: int = 0):
        try:
            valid_start, valid_buyout = validate_auction_prices(start_price, buyout)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}.")
        scope, user = await self._profile(ctx)
        try:
            require_multiplayer(scope, "auction")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        world = await self.bot.db.get_world(scope.scope_id)
        clean_item = item_name.lower().strip()
        async with self.bot.db.lock:
            await self._settle_expired_auctions(scope.scope_id, world)
            if inv_get(user, clean_item) < 1 or not inv_take(user, clean_item, 1):
                return await ctx.send(f"❌ You don't have **{clean_item}**.")
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
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_world_dirty(scope.scope_id)
        await ctx.send(f"🔨 **Listed!** {clean_item} for ${valid_start:,}. ID: `{auction_id}`")

    @commands.command(name="bid")
    async def bid(self, ctx, auction_id: str, amount: int):
        scope, user = await self._profile(ctx)
        try:
            require_multiplayer(scope, "auction")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        world = await self.bot.db.get_world(scope.scope_id)
        async with self.bot.db.lock:
            await self._settle_expired_auctions(scope.scope_id, world)
            auctions = world.setdefault("auctions", {})
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
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            if previous_bidder_id is not None and previous_bidder_id != ctx.author.id:
                previous_id = int(previous_bidder_id)
                previous_bidder = await self.bot.db.get_profile(scope.scope_id, previous_id)
                previous_bidder["grams"] = max(0, int(previous_bidder.get("grams", 0))) + current_bid
                self.bot.db.mark_profile_dirty(scope.scope_id, previous_id)
            auction["current_bid"] = valid_bid
            auction["highest_bidder"] = ctx.author.id
            bought_out = bool(buyout and valid_bid >= buyout)
            if bought_out:
                inv_add(user, auction["item_name"], 1)
                seller_id = int(auction["seller_id"])
                seller = await self.bot.db.get_profile(scope.scope_id, seller_id)
                seller["grams"] = max(0, int(seller.get("grams", 0))) + valid_bid
                self.bot.db.mark_profile_dirty(scope.scope_id, seller_id)
                del auctions[auction_id]
            self.bot.db.mark_world_dirty(scope.scope_id)
        if bought_out:
            await ctx.send(f"🔨 **BOOM!** You bought out the item for ${valid_bid:,}!")
        else:
            await ctx.send(f"✅ **Bid Placed!** You are leading with ${valid_bid:,}.")


async def setup(bot):
    await bot.add_cog(Economy(bot))
