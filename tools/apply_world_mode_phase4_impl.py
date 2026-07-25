from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def add_import(path: str, import_text: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if import_text.strip() in source:
        return
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if not imports:
        raise RuntimeError(f"No import block found in {path}")
    insert_line = max(node.end_lineno for node in imports)
    lines = source.splitlines(keepends=True)
    lines.insert(insert_line, import_text.rstrip() + "\n")
    target.write_text("".join(lines), encoding="utf-8")


def replace_method(path: str, class_name: str, method_name: str, replacement: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    start = min([decorator.lineno for decorator in method.decorator_list] or [method.lineno]) - 1
    end = method.end_lineno
    lines = source.splitlines(keepends=True)
    new_block = replacement.strip("\n") + "\n"
    target.write_text("".join(lines[:start]) + new_block + "".join(lines[end:]), encoding="utf-8")


def write_contract(path: str, content: str) -> None:
    (ROOT / path).write_text(content.strip("\n") + "\n", encoding="utf-8")


WORLD_MODE_IMPORT = '''from world_modes import (
    WorldModeDenied,
    effective_market_multiplier,
    require_multiplayer,
    require_same_multiplayer_scope,
    resolve_game_scope,
)
'''
add_import("economy.py", WORLD_MODE_IMPORT)

replace_method(
    "economy.py",
    "Economy",
    "_profile",
    '''    async def _profile(self, ctx, user_id=None):
        guild_id = require_guild_id(ctx)
        resolved_user_id = ctx.author.id if user_id is None else int(user_id)
        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)
        profile = await self.bot.db.get_profile(scope.scope_id, resolved_user_id)
        return scope, profile
''',
)
replace_method(
    "economy.py",
    "Economy",
    "_world",
    '''    async def _world(self, ctx, user_id=None):
        guild_id = require_guild_id(ctx)
        resolved_user_id = ctx.author.id if user_id is None else int(user_id)
        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)
        world = await self.bot.db.get_world(scope.scope_id)
        return scope, world
''',
)
replace_method(
    "economy.py",
    "Economy",
    "balance",
    '''    @commands.hybrid_command(name="balance", aliases=["bal", "cash", "wallet"])
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "give",
    '''    @commands.hybrid_command(name="give", aliases=["pay", "transfer"])
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "leaderboard",
    '''    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top", "rich"])
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
            cached_user = self.bot.get_user(user_id)
            name = member.display_name if member else cached_user.name if cached_user else f"User {user_id}"
            rank = "🥇" if index == 0 else "🥈" if index == 1 else "🥉" if index == 2 else f"#{index + 1}"
            lines.append(f"{rank} **{name}**: ${amount:,}")
        title = "🏆 Open World Leaderboard" if scope.cross_server else "🏆 Server Leaderboard"
        embed = discord.Embed(
            title=title,
            description="\n".join(lines) or "No players yet.",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)
''',
)
replace_method(
    "economy.py",
    "Economy",
    "inventory",
    '''    @commands.hybrid_command(name="inventory", aliases=["inv", "bag", "stash"])
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "buy",
    '''    @commands.hybrid_command(name="buy")
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "sell",
    '''    @commands.hybrid_command(name="sell")
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "sellconc",
    '''    @commands.command(name="sellconc")
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "_settle_expired_auctions",
    '''    async def _settle_expired_auctions(self, scope_id: int, world=None):
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "auction",
    '''    @commands.group(invoke_without_command=True)
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "auction_list",
    '''    @auction.command(name="list")
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
''',
)
replace_method(
    "economy.py",
    "Economy",
    "bid",
    '''    @commands.command(name="bid")
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
''',
)

SOCIAL_IMPORT = '''from world_modes import WorldModeDenied, require_multiplayer, resolve_game_scope
'''
add_import("social.py", SOCIAL_IMPORT)

replace_method(
    "social.py",
    "Social",
    "profile",
    '''    @commands.hybrid_command(name="profile", aliases=["me", "stats"])
    async def profile(self, ctx, target: discord.Member = None):
        guild_id = require_guild_id(ctx)
        target = target or ctx.author
        signatures = self.bot.get_cog("ProfileSignatures")
        if signatures is not None and hasattr(signatures, "build_full_profile"):
            embed, view = await signatures.build_full_profile(
                ctx.guild,
                target,
                viewer_id=ctx.author.id,
            )
            await ctx.send(embed=embed, view=view)
            return
        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)
        user = await self.bot.db.get_profile(scope.scope_id, target.id)
        world = await self.bot.db.get_world(scope.scope_id)

        level = max(1, int(user.get("level", 1)))
        xp = max(0, int(user.get("xp", 0)))
        needed = max(1, int(_xp_needed_for_level(level)))
        percent = min(100, int((xp / needed) * 100))
        filled = int(percent / 10)
        progress = "🟦" * filled + "⬜" * (10 - filled)

        crew_name = "None"
        crew_id = user.get("crew_id") if scope.multiplayer else None
        if crew_id:
            crew = get_crews(world).get(str(crew_id))
            if crew:
                crew_name = crew.get("name", "Unknown")

        stats = user.get("stats", {})
        embed = discord.Embed(title=f"👤 {target.display_name}", color=target.color)
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="⭐ Level", value=f"**{level}**", inline=True)
        embed.add_field(name="✨ XP", value=f"{xp} / {needed}\n{progress}", inline=True)
        embed.add_field(name="🧢 Crew", value=crew_name, inline=True)
        embed.add_field(
            name="💰 Wealth",
            value=(
                f"Clean: **${max(0, int(user.get('grams', 0))):,}**\n"
                f"Dirty: **${max(0, int(user.get('dirty_cash', 0))):,}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Career Stats",
            value=(
                f"🌿 Harvested: {max(0, int(stats.get('harvested', 0)))}\n"
                f"🔫 Heists Won: {max(0, int(stats.get('heists_won', 0)))}\n"
                f"😈 Robberies: {max(0, int(stats.get('steals', 0)))}\n"
                f"🔥 Highest Heat: {max(0, int(stats.get('max_heat', 0)))}%"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)
''',
)
replace_method(
    "social.py",
    "Social",
    "crew",
    '''    @commands.group(invoke_without_command=True, aliases=["c"])
    async def crew(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        await ctx.send(
            "ℹ️ **Crew Commands:**\n"
            "`!crew create <name>`\n"
            "`!crew join <id>`\n"
            "`!crew info`\n"
            "`!crew deposit <amount>`\n"
            "`!crew war` (Turf War)\n"
            "`!district` (Check control)"
        )
''',
)
replace_method(
    "social.py",
    "Social",
    "crew_create",
    '''    @crew.command(name="create")
    async def crew_create(self, ctx, *, name: str):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        clean_name = name.strip()
        if not clean_name:
            return await ctx.send("❌ Crew name cannot be empty.")
        if len(clean_name) > 50:
            return await ctx.send("❌ Crew name is too long.")

        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            if user.get("crew_id"):
                return await ctx.send("❌ Already in a crew.")
            balance = max(0, int(user.get("grams", 0)))
            if balance < 50000:
                return await ctx.send("💸 Cost: $50,000.")

            crews = get_crews(world)
            crew_id = str(random.randint(10000, 99999))
            while crew_id in crews:
                crew_id = str(random.randint(10000, 99999))
            crews[crew_id] = {
                "id": crew_id,
                "name": clean_name,
                "owner_id": ctx.author.id,
                "members": [ctx.author.id],
                "bank": 0,
                "level": 1,
                "created_at": time.time(),
            }
            user["grams"] = balance - 50000
            user["crew_id"] = crew_id
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_world_dirty(scope.scope_id)

        await ctx.send(f"✅ **Crew Created!** ID: `{crew_id}`")
''',
)
replace_method(
    "social.py",
    "Social",
    "crew_join",
    '''    @crew.command(name="join")
    async def crew_join(self, ctx, crew_id: str):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            if user.get("crew_id"):
                return await ctx.send("❌ Leave your current crew first.")
            crew = get_crews(world).get(str(crew_id))
            if not crew:
                return await ctx.send("❌ Crew not found.")
            members = crew.setdefault("members", [])
            if ctx.author.id not in members:
                members.append(ctx.author.id)
            user["crew_id"] = str(crew_id)
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_world_dirty(scope.scope_id)

        await ctx.send(f"✅ Joined **{crew['name']}**!")
''',
)
replace_method(
    "social.py",
    "Social",
    "crew_info",
    '''    @crew.command(name="info")
    async def crew_info(self, ctx, crew_id: str = None):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        world = await self.bot.db.get_world(scope.scope_id)
        resolved_id = str(crew_id or user.get("crew_id") or "")
        crew = get_crews(world).get(resolved_id)
        if not crew:
            return await ctx.send("❌ Crew not found.")

        member_ids = [int(value) for value in crew.get("members", []) if str(value).isdigit()]
        owner_id = int(crew.get("owner_id", 0) or 0)
        owner = ctx.guild.get_member(owner_id)
        cached_owner = self.bot.get_user(owner_id)
        owner_label = owner.mention if owner else cached_owner.name if cached_owner else f"User {owner_id}"
        embed = discord.Embed(title=f"🧢 {crew.get('name', 'Unknown Crew')}", color=0x2ECC71)
        embed.description = f"**World:** {scope.emoji} {scope.label}"
        embed.add_field(name="ID", value=f"`{resolved_id}`", inline=True)
        embed.add_field(name="Owner", value=owner_label, inline=True)
        embed.add_field(name="Members", value=str(len(member_ids)), inline=True)
        embed.add_field(name="Bank", value=f"${max(0, int(crew.get('bank', 0))):,}", inline=True)
        embed.add_field(name="Level", value=str(max(1, int(crew.get('level', 1)))), inline=True)
        await ctx.send(embed=embed)
''',
)
replace_method(
    "social.py",
    "Social",
    "crew_deposit",
    '''    @crew.command(name="deposit")
    async def crew_deposit(self, ctx, amount: int):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew_bank")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        try:
            deposit = require_positive_amount(amount)
        except ValueError:
            return await ctx.send("❌ Deposit must be a positive whole number.")

        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            crew_id = user.get("crew_id")
            if not crew_id:
                return await ctx.send("❌ No crew.")
            crew = get_crews(world).get(str(crew_id))
            if not crew:
                return await ctx.send("❌ Crew data missing.")
            balance = max(0, int(user.get("grams", 0)))
            if balance < deposit:
                return await ctx.send("💸 Insufficient funds.")
            user["grams"] = balance - deposit
            crew["bank"] = max(0, int(crew.get("bank", 0))) + deposit
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_world_dirty(scope.scope_id)

        await ctx.send(f"🏦 Deposited ${deposit:,}.")
''',
)
replace_method(
    "social.py",
    "Social",
    "crew_war",
    '''    @crew.command(name="war")
    @commands.cooldown(1, 3600, commands.BucketType.guild)
    async def crew_war(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "district")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            crew_id = user.get("crew_id")
            if not crew_id:
                return await ctx.send("❌ You need a crew.")

            crews = get_crews(world)
            attacker = crews.get(str(crew_id))
            if not attacker:
                return await ctx.send("❌ Crew data missing.")
            now = time.time()
            cooldowns = attacker.setdefault("cooldowns", {})
            last_war = float(cooldowns.get("war", 0) or 0)
            remaining = int(last_war + 3600 - now)
            if remaining > 0:
                return await ctx.send(f"⏳ Crew turf-war cooldown: **{remaining // 60 + 1}m**")

            district = world.setdefault("district", {})
            current_owner = district.get("owner_crew_id")
            if not current_owner or now >= float(district.get("expires_at", 0)):
                district.update(
                    {
                        "owner_crew_id": str(crew_id),
                        "owner_name": attacker["name"],
                        "multiplier": 1.10,
                        "expires_at": now + 86400,
                    }
                )
                cooldowns["war"] = now
                self.bot.db.mark_world_dirty(scope.scope_id)
                return await ctx.send(f"🔥 **{attacker['name']}** claimed the empty district!")
            if str(current_owner) == str(crew_id):
                return await ctx.send("🏙️ You already own the block.")

            defender = crews.get(str(current_owner))
            if not defender:
                return await ctx.send("❌ Defending crew data is missing.")
            attacker_score = len(attacker.get("members", [])) * random.uniform(0.8, 1.2)
            defender_score = len(defender.get("members", [])) * random.uniform(0.8, 1.2)
            attacker_won = attacker_score > defender_score
            cooldowns["war"] = now
            if attacker_won:
                district.update(
                    {
                        "owner_crew_id": str(crew_id),
                        "owner_name": attacker["name"],
                        "multiplier": 1.10,
                        "expires_at": now + 86400,
                    }
                )
            self.bot.db.mark_world_dirty(scope.scope_id)

        if attacker_won:
            await ctx.send(
                f"💥 **WAR!** {attacker['name']} defeated {defender['name']} and took the district!"
            )
        else:
            await ctx.send(f"🛡️ **Failed.** {defender['name']} held the district.")
''',
)
replace_method(
    "social.py",
    "Social",
    "district",
    '''    @commands.command(name="district")
    async def district(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "district")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        world = await self.bot.db.get_world(scope.scope_id)
        district = world.get("district", {})
        owner = district.get("owner_name", "None")
        multiplier = max(1.0, float(district.get("multiplier", 1.0)))
        bonus = int((multiplier - 1) * 100)
        remaining = max(0, int((float(district.get("expires_at", 0)) - time.time()) / 60))
        embed = discord.Embed(title="🏙️ District Control", color=0xE67E22)
        embed.description = (
            f"**World:** {scope.emoji} {scope.label}\n"
            f"**Owner:** {owner}\n"
            f"**Bonus:** +{bonus}% Sell Value\n"
            f"**Expires:** {remaining} mins"
        )
        await ctx.send(embed=embed)
''',
)
replace_method(
    "social.py",
    "Social",
    "on_message",
    '''    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.channel.id != SUPPORT_CHANNEL_ID:
            return
        service_name = SUPPORT_SERVICES.get(message.author.id)
        if service_name is None:
            return

        content = message.content.lower() + " ".join(
            embed.description.lower() for embed in message.embeds if embed.description
        )
        if "bump done" not in content and "voted" not in content:
            return
        rewarded_user = message.mentions[0] if message.mentions else None
        if rewarded_user is None or rewarded_user.bot:
            return

        guild_id = int(message.guild.id)
        reward_scope = await resolve_game_scope(self.bot.db, guild_id, rewarded_user.id)
        async with self.bot.db.lock:
            user_data = await self.bot.db.get_profile(reward_scope.scope_id, rewarded_user.id)
            cooldowns = user_data.setdefault("support_cooldowns", {})
            now = time.time()
            last_reward = max(0.0, float(cooldowns.get(service_name, 0)))
            cooldown = max(0, int(SUPPORT_COOLDOWN_SECONDS.get(service_name, 7200)))
            if now - last_reward < cooldown:
                return
            user_data["xp"] = max(0, int(user_data.get("xp", 0))) + SUPPORT_REWARD_XP
            cooldowns[service_name] = now
            self.bot.db.mark_profile_dirty(reward_scope.scope_id, rewarded_user.id)

        await message.channel.send(
            f"✅ **{rewarded_user.mention}** received {SUPPORT_REWARD_XP} XP for {service_name}!"
        )
''',
)

CRIME_IMPORT = '''from world_modes import (
    WorldModeDenied,
    require_multiplayer,
    require_same_multiplayer_scope,
    resolve_game_scope,
)
'''
add_import("crime.py", CRIME_IMPORT)

replace_method(
    "crime.py",
    "Crime",
    "_session_key",
    '''    @staticmethod
    def _session_key(scope_id: int, kind: str, identifier: object) -> str:
        return f"scope:{scope_id}:{kind}:{identifier}"
''',
)
replace_method(
    "crime.py",
    "Crime",
    "heist",
    '''    @commands.command(name="heist", aliases=["heists"])
    async def heist(self, ctx, mode: str = "solo", arg: str = None):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, user, "heist"):
            return

        mode = (mode or "solo").lower().strip()
        if mode in ("solo", ""):
            await self._solo_heist(ctx, scope, user, arg or "stealth")
        elif mode in ("crew", "coop"):
            try:
                require_multiplayer(scope, "crew_heist")
            except WorldModeDenied as exc:
                return await ctx.send(str(exc))
            await self._start_crew_heist(ctx, scope, user)
        elif mode == "join":
            try:
                require_multiplayer(scope, "crew_heist")
            except WorldModeDenied as exc:
                return await ctx.send(str(exc))
            await self._join_crew_heist(ctx, scope, user)
        elif mode in ("raid", "pvp"):
            try:
                require_multiplayer(scope, "raid")
            except WorldModeDenied as exc:
                return await ctx.send(str(exc))
            await self._raid(ctx, scope, user, arg)
        else:
            await ctx.send("Usage: `!heist solo [plan]`, `!heist crew`, `!heist join`, or `!heist raid <crew_id>`")
''',
)
replace_method(
    "crime.py",
    "Crime",
    "_solo_heist",
    '''    async def _solo_heist(self, ctx, scope, user: dict, plan: str) -> None:
        key = self._session_key(scope.scope_id, "user", ctx.author.id)
        if _ACTIVE_HEISTS.get(key, {}).get("ends", 0) > self._now():
            await ctx.send("⏳ You’re already mid-heist.")
            return

        _ACTIVE_HEISTS[key] = {"ends": self._now() + 8}
        try:
            async with self.bot.db.lock:
                last = self._get_user_cooldown(user, "heist_solo")
                remaining = int(last + HEIST_SOLO_COOLDOWN - self._now())
                if remaining > 0:
                    await ctx.send(f"⏳ Solo heist cooldown: **{self._fmt_time(remaining)}**")
                    return

                heat = self._apply_heat_decay(user)
                level = max(1, int(user.get("level", 1) or 1))
                prestige = max(0, int(user.get("prestige", 0) or 0))
                config = self._solo_profile(level, prestige, heat, plan)
                balance = max(0, int(user.get("grams", 0) or 0))
                if balance < config["buyin"]:
                    await ctx.send(f"💸 You need **${config['buyin']:,}** for this job.")
                    return

                user["grams"] = balance - config["buyin"]
                stats = user.setdefault("stats", {})
                stats["heists_run"] = max(0, int(stats.get("heists_run", 0))) + 1
                success = self._roll(config["chance"])

                if success:
                    payout = random.randint(*config["reward"])
                    xp = random.randint(*config["xp"])
                    user["grams"] += payout
                    user["xp"] = max(0, int(user.get("xp", 0))) + xp
                    add_heat(user, HEAT_GAIN_WIN + config["heat_mod"])
                    stats["heists_won"] = max(0, int(stats.get("heists_won", 0))) + 1
                    stats["heist_profit"] = max(0, int(stats.get("heist_profit", 0))) + payout
                    jail_minutes = 0
                    loss = 0
                else:
                    requested_loss = max(150, int(config["buyin"] * random.uniform(0.30, 0.70)))
                    loss = calculate_capped_loss(user["grams"], requested_loss)
                    user["grams"] -= loss
                    jail_minutes = random.randint(HEIST_JAIL_MIN, HEIST_JAIL_MAX)
                    user["jail_until"] = int(self._now() + jail_minutes * 60)
                    add_heat(user, HEAT_GAIN_FAIL + config["heat_mod"])
                    stats["heists_lost"] = max(0, int(stats.get("heists_lost", 0))) + 1
                    payout = 0
                    xp = 0

                self._set_user_cooldown(user, "heist_solo", self._now())
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        finally:
            _ACTIVE_HEISTS.pop(key, None)

        if success:
            embed = discord.Embed(
                title="🏦 Heist Success",
                description=(
                    f"**Plan:** {config['plan']}\n"
                    f"🎯 Odds: **{int(config['chance'] * 100)}%**\n"
                    f"💰 Payout: **+${payout:,}**\n"
                    f"⭐ XP: **+{xp:,}**\n"
                    f"🚓 Heat: **{int(user.get('heat', 0))}%**"
                ),
                color=0x2ECC71,
            )
        else:
            embed = discord.Embed(
                title="🚨 Heist Failed",
                description=(
                    f"**Plan:** {config['plan']}\n"
                    f"🎯 Odds: **{int(config['chance'] * 100)}%**\n"
                    f"💸 Additional loss: **${loss:,}**\n"
                    f"🚔 Jail: **{jail_minutes}m**\n"
                    f"🚓 Heat: **{int(user.get('heat', 0))}%**"
                ),
                color=0xE74C3C,
            )
        await ctx.send(embed=embed)
''',
)
replace_method(
    "crime.py",
    "Crime",
    "_start_crew_heist",
    '''    async def _start_crew_heist(self, ctx, scope, user: dict) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")

        world = await self.bot.db.get_world(scope.scope_id)
        crew = self._get_crews(world).get(str(crew_id))
        if not crew:
            return await ctx.send("❌ Crew data missing.")

        key = self._session_key(scope.scope_id, "crew", crew_id)
        async with self.bot.db.lock:
            remaining = self._crew_cooldown_left(crew, "heist")
            if remaining > 0:
                return await ctx.send(f"⏳ Crew cooldown: **{self._fmt_time(remaining)}**")
            if _ACTIVE_HEISTS.get(key, {}).get("join_until", 0) > self._now():
                return await ctx.send("⏳ Crew heist already forming. Use `!heist join`.")
            _ACTIVE_HEISTS[key] = {
                "join_until": self._now() + HEIST_JOIN_WINDOW,
                "members": {int(ctx.author.id): int(scope.guild_id)},
                "host_id": int(ctx.author.id),
            }

        await ctx.send(embed=discord.Embed(
            title="🧪 Crew Heist Forming",
            description=(
                f"**{crew.get('name', 'Crew')}** is starting a job!\n"
                f"Type `!heist join` within **{HEIST_JOIN_WINDOW}s**.\nNeed 2+ members."
            ),
            color=0x9B59B6,
        ))
        await asyncio.sleep(HEIST_JOIN_WINDOW + 1)

        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.pop(key, None)
            if not session:
                return
            world = await self.bot.db.get_world(scope.scope_id)
            crew = self._get_crews(world).get(str(crew_id))
            if not crew:
                return await ctx.send("❌ Crew data missing.")

            valid_members: list[tuple[int, dict]] = []
            for member_id, member_guild_id in session.get("members", {}).items():
                member_scope = await resolve_game_scope(
                    self.bot.db,
                    int(member_guild_id),
                    int(member_id),
                )
                if member_scope.scope_id != scope.scope_id:
                    continue
                member = await self.bot.db.get_profile(scope.scope_id, int(member_id))
                if self._in_jail(member) <= 0 and str(member.get("crew_id")) == str(crew_id):
                    valid_members.append((int(member_id), member))
            if len(valid_members) < 2:
                return await ctx.send("❌ Heist cancelled: not enough eligible crew members joined.")

            levels = [max(1, int(member.get("level", 1))) for _, member in valid_members]
            power = self._calc_power(levels)
            chance = max(0.18, min(0.88, 0.46 + power * 0.06 + len(valid_members) * 0.03))
            success = self._roll(chance)
            base = int(2_600 + power * 1_200)
            total = random.randint(int(base * 0.7), int(base * 1.3))

            if success:
                split = calculate_crew_payout(total, len(valid_members), bank_rate=0.30)
                crew["bank"] = max(0, int(crew.get("bank", 0))) + split.crew_bank_gain + split.remainder
                for member_id, member in valid_members:
                    member["grams"] = max(0, int(member.get("grams", 0))) + split.member_gain
                    add_heat(member, 2)
                    self.bot.db.mark_profile_dirty(scope.scope_id, member_id)
                bank_gain = split.crew_bank_gain + split.remainder
                member_gain = split.member_gain
                jail_minutes = 0
            else:
                jail_minutes = random.randint(2, 7)
                for member_id, member in valid_members:
                    balance = max(0, int(member.get("grams", 0)))
                    loss = calculate_capped_loss(balance, int(balance * 0.04))
                    member["grams"] = balance - loss
                    member["jail_until"] = int(self._now() + jail_minutes * 60)
                    add_heat(member, 6)
                    self.bot.db.mark_profile_dirty(scope.scope_id, member_id)
                bank_gain = 0
                member_gain = 0

            self._set_crew_cooldown(crew, "heist")
            self.bot.db.mark_world_dirty(scope.scope_id)

        if success:
            await ctx.send(embed=discord.Embed(
                title="🏦 Crew Heist Success",
                description=(
                    f"💰 Total: **${total:,}**\n"
                    f"🏦 Crew bank: **+${bank_gain:,}**\n"
                    f"👤 Each member: **+${member_gain:,}**"
                ),
                color=0x2ECC71,
            ))
        else:
            await ctx.send(f"🚨 **Crew heist failed.** Eligible members were jailed for {jail_minutes}m.")
''',
)
replace_method(
    "crime.py",
    "Crime",
    "_join_crew_heist",
    '''    async def _join_crew_heist(self, ctx, scope, user: dict) -> None:
        if self._in_jail(user) > 0:
            return await ctx.send("🚔 You are jailed.")
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")
        key = self._session_key(scope.scope_id, "crew", crew_id)
        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.get(key)
            if not session or session.get("join_until", 0) <= self._now():
                return await ctx.send("❌ No heist is forming.")
            session.setdefault("members", {})[int(ctx.author.id)] = int(scope.guild_id)
        await ctx.send(f"✅ {ctx.author.mention} joined!")
''',
)
replace_method(
    "crime.py",
    "Crime",
    "_raid",
    '''    async def _raid(self, ctx, scope, user: dict, target_id: str | None) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")
        if not target_id:
            return await ctx.send("Usage: `!heist raid <target_crew_id>`")

        async with self.bot.db.lock:
            world = await self.bot.db.get_world(scope.scope_id)
            crews = self._get_crews(world)
            attacker = crews.get(str(crew_id))
            defender = crews.get(str(target_id).strip())
            if not attacker or not defender:
                return await ctx.send("❌ Invalid crew IDs.")
            if str(crew_id) == str(target_id).strip():
                return await ctx.send("❌ Cannot raid your own crew.")
            remaining = self._crew_cooldown_left(attacker, "raid")
            if remaining > 0:
                return await ctx.send(f"⏳ Raid cooldown: **{self._fmt_time(remaining)}**")
            defender_bank = max(0, int(defender.get("bank", 0)))
            if defender_bank < RAID_MIN_TARGET_BANK:
                return await ctx.send("❌ Target is too poor to raid.")

            async def levels(crew: dict) -> list[int]:
                result = []
                for member_id in crew.get("members", []):
                    try:
                        profile = await self.bot.db.get_profile(scope.scope_id, int(member_id))
                    except (TypeError, ValueError):
                        continue
                    result.append(max(1, int(profile.get("level", 1))))
                return result

            attacker_power = self._calc_power(await levels(attacker))
            defender_power = self._calc_power(await levels(defender))
            chance = max(0.12, min(0.85, 0.50 + (attacker_power - defender_power) * 0.06))
            success = self._roll(chance)
            attacker_bank = max(0, int(attacker.get("bank", 0)))
            if success:
                outcome = calculate_raid_outcome(
                    defender_bank,
                    attacker_bank,
                    steal_rate=RAID_MAX_STEAL_PCT,
                    steal_cap=RAID_MAX_STEAL_FLAT,
                    attacker_keep_rate=0.85,
                )
                defender["bank"] = outcome.defender_balance
                attacker["bank"] = outcome.attacker_balance
                stolen = outcome.stolen
                attacker_gain = outcome.attacker_gain
                penalty = 0
            else:
                penalty = calculate_capped_loss(attacker_bank, min(12_000, int(attacker_bank * 0.06)))
                attacker["bank"] = attacker_bank - penalty
                stolen = 0
                attacker_gain = 0

            self._set_crew_cooldown(attacker, "raid")
            stats = user.setdefault("stats", {})
            stats["raids_run"] = max(0, int(stats.get("raids_run", 0))) + 1
            if success:
                stats["raids_won"] = max(0, int(stats.get("raids_won", 0))) + 1
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            self.bot.db.mark_world_dirty(scope.scope_id)

        if success:
            await ctx.send(embed=discord.Embed(
                title="⚔️ Raid Success",
                description=(
                    f"Stole **${stolen:,}** from **{defender.get('name', 'crew')}**!\n"
                    f"Net crew-bank gain: **${attacker_gain:,}**"
                ),
                color=0xF1C40F,
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="🚫 Raid Failed",
                description=f"Attack failed. Lost **${penalty:,}** in crew resources.",
                color=0xE74C3C,
            ))
''',
)
replace_method(
    "crime.py",
    "Crime",
    "steal",
    '''    @commands.hybrid_command(name="steal", aliases=["rob"])
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def steal(self, ctx, target: discord.Member):
        if target.id == ctx.author.id:
            return await ctx.send("❌ Robbing yourself?")
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        target_scope = await resolve_game_scope(self.bot.db, guild_id, target.id)
        try:
            require_same_multiplayer_scope(scope, target_scope, "theft")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        robber = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        if await jail_guard(ctx, robber, "steal"):
            return

        async with self.bot.db.lock:
            victim = await self.bot.db.get_profile(scope.scope_id, target.id)
            chance = 0.50
            if has_item(victim, "dog") or has_item(victim, "guard dog"):
                chance -= 0.25
            if has_item(victim, "cam") or has_item(victim, "security camera"):
                chance -= 0.15
            if has_item(robber, "lockpick"):
                chance += 0.10
            if has_item(robber, "ski mask"):
                chance += 0.10
            chance = max(0.05, min(0.90, chance))

            if random.random() < chance:
                wallet = max(0, int(victim.get("grams", 0)))
                try:
                    amount = calculate_robbery_transfer(wallet, random.uniform(0.05, 0.20))
                except ValueError:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send("That player is too poor to rob.")
                victim["grams"] = wallet - amount
                robber["dirty_cash"] = max(0, int(robber.get("dirty_cash", 0))) + amount
                add_heat(robber, 15)
                stats = robber.setdefault("stats", {})
                stats["steals"] = max(0, int(stats.get("steals", 0))) + 1
                success = True
                fine = 0
                self.bot.db.mark_profile_dirty(scope.scope_id, target.id)
            else:
                balance = max(0, int(robber.get("grams", 0)))
                fine = calculate_capped_loss(balance, 1_000)
                robber["grams"] = balance - fine
                robber["jail_until"] = int(self._now() + 300)
                add_heat(robber, 25)
                amount = 0
                success = False
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        if success:
            await ctx.send(f"🔫 **SUCCESS!** Stole **${amount:,}** in dirty cash.")
        else:
            await ctx.send(f"🚓 **BUSTED!** Fined ${fine:,} and jailed for 5m.")
''',
)
replace_method(
    "crime.py",
    "Crime",
    "launder",
    '''    @commands.command(name="launder")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def launder(self, ctx, amount: str = "all"):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        async with self.bot.db.lock:
            dirty = max(0, int(user.get("dirty_cash", 0) or 0))
            heat = max(0, int(user.get("heat", 0) or 0))
            if dirty <= 0:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("❌ You have no **Dirty Cash** to launder.")
            if heat >= 90:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"🚓 **Too Hot!** Heat is **{heat}%**. Let it cool down first.")

            raw = (amount or "all").strip().lower()
            try:
                requested = dirty if raw in ("all", "max", "*") else require_positive_amount(raw.replace(",", ""))
                outcome = calculate_launder_outcome(requested, dirty_balance=dirty, fee_rate=0.20)
            except ValueError as error:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"❌ {error}.")

            user["dirty_cash"] = dirty - outcome.dirty_spent
            user["grams"] = max(0, int(user.get("grams", 0))) + outcome.clean_received
            add_heat(user, 5)
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)

        embed = discord.Embed(
            title="🧼 Money Laundered",
            description=f"You cleaned **${outcome.dirty_spent:,}** dirty cash.",
            color=0x95A5A6,
        )
        embed.add_field(name="💸 Fee (20%)", value=f"-${outcome.fee:,}", inline=True)
        embed.add_field(name="💰 Received", value=f"+${outcome.clean_received:,} clean", inline=True)
        embed.add_field(name="🔥 Heat", value=f"+5 (Total: {int(user.get('heat', 0))}%)", inline=True)
        await ctx.send(embed=embed)
''',
)
replace_method(
    "crime.py",
    "Crime",
    "heat",
    '''    @commands.command(name="heat")
    async def heat(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
        heat_level = max(0, min(100, int(user.get("heat", 0) or 0)))
        dirty_cash = max(0, int(user.get("dirty_cash", 0) or 0))
        filled = heat_level // 10
        bar = "🟥" * filled + "⬜" * (10 - filled)
        status = "WANTED 🚓" if heat_level > 80 else "Hot 🔥" if heat_level > 50 else "Suspicious" if heat_level > 20 else "Chill"
        embed = discord.Embed(title="🚓 Police Heat Level", color=0xE74C3C)
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
        embed.add_field(name="Heat", value=f"{bar} ({heat_level}%)", inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="💼 Dirty Cash", value=f"${dirty_cash:,}", inline=True)
        embed.set_footer(text="Use !launder to clean dirty cash. High heat increases crime risk.")
        await ctx.send(embed=embed)
''',
)
replace_method(
    "crime.py",
    "Crime",
    "heiststats",
    '''    @commands.command(name="heiststats", aliases=["hst"])
    async def heiststats(self, ctx, member: discord.Member = None):
        guild_id = require_guild_id(ctx)
        target = member or ctx.author
        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)
        profile = await self.bot.db.get_profile(scope.scope_id, target.id)
        stats = profile.get("stats", {})
        embed = discord.Embed(title=f"🏆 Heist Stats: {target.display_name}", color=0x3498DB)
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
        embed.add_field(name="Solo", value=f"Won: {stats.get('heists_won', 0)}\nRun: {stats.get('heists_run', 0)}", inline=True)
        embed.add_field(name="Raids", value=f"Won: {stats.get('raids_won', 0)}\nRun: {stats.get('raids_run', 0)}", inline=True)
        embed.add_field(name="Payouts", value=f"${stats.get('heist_profit', 0):,}", inline=False)
        await ctx.send(embed=embed)
''',
)
replace_method(
    "crime.py",
    "Crime",
    "topheists",
    '''    @commands.command(name="topheists", aliases=["lbheists"])
    async def topheists(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "leaderboard")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        rows = await self.bot.db.list_guild_heist_leaderboard(scope.scope_id, limit=10)
        lines = []
        for index, (user_id, score) in enumerate(rows, 1):
            member = ctx.guild.get_member(user_id)
            cached_user = self.bot.get_user(user_id)
            name = member.display_name if member else cached_user.name if cached_user else f"User {user_id}"
            lines.append(f"**{index}.** {name} — {score} wins")
        title = "🏆 Open World Heisters" if scope.cross_server else "🏆 Top Heisters"
        await ctx.send(embed=discord.Embed(
            title=title,
            description="\n".join(lines) or "None",
            color=0xF1C40F,
        ))
''',
)

write_contract(
    "tests/test_economy_scoped_persistence_contract.py",
    '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_economy_uses_explicit_active_scope_storage_paths():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_same_multiplayer_scope" in source
    assert "require_multiplayer" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_economy_uses_backend_leaderboard_queries_for_active_scope():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "list_guild_leaderboard(scope.scope_id, limit=10)" in source
    assert "for uid, data in self.bot.db.data.items()" not in source


def test_auction_state_and_settlement_use_explicit_multiplayer_scope():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert "def _settle_expired_auctions(self, scope_id" in source
    assert "await self.bot.db.get_world(scope_id)" in source
    assert "await self._settle_expired_auctions(scope.scope_id, world)" in source
    assert 'require_multiplayer(scope, "auction")' in source
''',
)
write_contract(
    "tests/test_social_guild_scope_contract.py",
    '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_social_uses_explicit_active_scope_storage_paths():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_multiplayer" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source
    assert "db_manager" not in source


def test_social_support_rewards_follow_the_rewarded_users_active_save():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "if message.guild is None" in source
    assert "reward_scope = await resolve_game_scope" in source
    assert "reward_scope.scope_id" in source


def test_social_no_longer_owns_daily_or_sesh_interactions():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert '@commands.hybrid_command(name="daily")' not in source
    assert '@commands.hybrid_command(name="sesh")' not in source
    assert '@commands.hybrid_command(name="movie")' not in source
    assert "class SeshView" not in source
    assert "_ACTIVE_SESHES" not in source


def test_social_crew_and_district_state_use_the_active_multiplayer_world():
    source = (ROOT / "social.py").read_text(encoding="utf-8")
    assert "def get_crews(world: dict)" in source
    assert 'district = world.setdefault("district", {})' in source
    assert 'require_multiplayer(scope, "crew")' in source
    assert 'require_multiplayer(scope, "district")' in source
''',
)
write_contract(
    "tests/test_crime_scoped_persistence_contract.py",
    '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crime_routes_gameplay_through_explicit_active_scopes():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    assert "resolve_game_scope" in source
    assert "scope.scope_id" in source
    assert "require_multiplayer" in source
    assert "require_same_multiplayer_scope" in source
    assert "self.bot.db.get_user" not in source
    assert "self.bot.db.world_state" not in source
    assert "self.bot.db.data" not in source
    assert "await self.bot.db.save()" not in source


def test_crime_sessions_and_rankings_are_active_scope_isolated():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    assert 'return f"scope:{scope_id}:{kind}:{identifier}"' in source
    assert "list_guild_heist_leaderboard(scope.scope_id, limit=10)" in source
    assert "for user_id, data in self.bot.db.data.items()" not in source


def test_heist_channel_configuration_remains_real_guild_scoped():
    source = (ROOT / "crime.py").read_text(encoding="utf-8")
    block = source.split('name="heistset"', 1)[1]
    assert "await self.bot.db.get_world(guild_id)" in block
    assert "self.bot.db.mark_world_dirty(guild_id)" in block


def test_supabase_has_indexed_heist_win_projection():
    migration = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(encoding="utf-8")
    backend = (ROOT / "supabase_scoped_backend.py").read_text(encoding="utf-8")
    assert "heist_wins bigint generated always as" in migration
    assert "guild_profiles_guild_heist_wins_idx" in migration
    assert "(guild_id, heist_wins desc, user_id)" in migration
    assert 'metric="heist_wins"' in backend
    assert '.eq("guild_id", guild_id)' in backend
    assert '.order(metric, desc=True)' in backend
''',
)
