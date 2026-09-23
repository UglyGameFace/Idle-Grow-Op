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
from progression_core import add_progress, check_achievements
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
    jail_left_seconds,
)
from world_modes import (
    WorldModeDenied,
    effective_market_multiplier,
    require_multiplayer,
    require_same_multiplayer_scope,
    resolve_game_scope,
)


def _shop_section(item: dict) -> str:
    item_type = str(item.get("type", "misc"))
    if "seed" in item_type:
        return "seeds"
    if any(token in item_type for token in ("equipment", "pot", "tool")):
        return "equipment"
    return "misc"


class ShopCategorySelect(discord.ui.Select):
    def __init__(self, view: "ShopView") -> None:
        options = [
            discord.SelectOption(label="All Items", value="all", emoji="🛒"),
            discord.SelectOption(label="Seeds", value="seeds", emoji="🌱"),
            discord.SelectOption(label="Equipment", value="equipment", emoji="💡"),
            discord.SelectOption(label="Misc", value="misc", emoji="🔧"),
        ]
        for option in options:
            option.default = option.value == view.category
        super().__init__(
            placeholder="Choose a shop category…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        view.category = self.values[0]
        view.selected_item = None
        await view.refresh(interaction)


class ShopItemSelect(discord.ui.Select):
    def __init__(self, view: "ShopView", profile: dict) -> None:
        items = [
            (name, item)
            for name, item in SHOP_ITEMS.items()
            if view.category == "all" or _shop_section(item) == view.category
        ]
        level = max(1, int(profile.get("level", 1) or 1))
        options = []
        for name, item in items[:25]:
            cost = _shop_price(item)
            required = max(1, int(item.get("level_req", 1) or 1))
            owned = inv_get(profile, name)
            status = "Owned" if owned and item.get("type") in {"equipment", "tool", "defense"} else f"Lv {required}"
            if level < required:
                status = f"Locked • Lv {required}"
            options.append(
                discord.SelectOption(
                    label=name.title()[:100],
                    value=name,
                    description=f"${cost:,} • {status}"[:100],
                    default=name == view.selected_item,
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label="No items in this category",
                    value="__none__",
                    description="Choose another category.",
                )
            ]
        super().__init__(
            placeholder="Choose an item to inspect or buy…",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        value = self.values[0]
        view.selected_item = None if value == "__none__" else value
        await view.refresh(interaction)


class ShopView(discord.ui.View):
    def __init__(
        self,
        cog: "Economy",
        owner_id: int,
        guild_id: int,
        *,
        category: str = "all",
        timeout: float = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)
        self.category = category if category in {"all", "seeds", "equipment", "misc"} else "all"
        self.selected_item: str | None = None
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This shop belongs to another player.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "❌ This shop belongs to another server.",
                ephemeral=True,
            )
            return False
        return True

    def rebuild(self, profile: dict) -> None:
        self.clear_items()
        self.add_item(ShopCategorySelect(self))
        self.add_item(ShopItemSelect(self, profile))

        buy = discord.ui.Button(
            label="Buy Selected",
            emoji="💳",
            style=discord.ButtonStyle.success,
            row=2,
            disabled=self.selected_item is None,
        )
        buy.callback = self.buy_selected
        self.add_item(buy)

        refresh = discord.ui.Button(
            label="Refresh",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        refresh.callback = self.refresh_button
        self.add_item(refresh)

        close = discord.ui.Button(
            label="Close",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        close.callback = self.close_button
        self.add_item(close)

    async def state(self):
        return await self.cog._profile_for(self.guild_id, self.owner_id)

    async def refresh(
        self,
        interaction: discord.Interaction,
        *,
        notice: str | None = None,
    ) -> None:
        scope, profile = await self.state()
        self.rebuild(profile)
        embed = self.cog.build_shop_embed(
            scope,
            profile,
            category=self.category,
            selected_item=self.selected_item,
            notice=notice,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def buy_selected(self, interaction: discord.Interaction) -> None:
        if not self.selected_item:
            return await interaction.response.send_message(
                "Choose an item first.",
                ephemeral=True,
            )
        scope, profile = await self.state()
        if jail_left_seconds(profile) > 0:
            return await interaction.response.send_message(
                "🚔 You cannot shop while jailed.",
                ephemeral=True,
            )
        _success, message = await self.cog._purchase_item(
            scope,
            profile,
            self.owner_id,
            self.selected_item,
        )
        await self.refresh(interaction, notice=message)

    async def refresh_button(self, interaction: discord.Interaction) -> None:
        await self.refresh(interaction)

    async def close_button(self, interaction: discord.Interaction) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()


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

    async def _profile_for(self, guild_id: int, user_id: int):
        scope = await resolve_game_scope(self.bot.db, int(guild_id), int(user_id))
        profile = await self.bot.db.get_profile(scope.scope_id, int(user_id))
        return scope, profile

    async def _profile(self, ctx, user_id=None):
        guild_id = require_guild_id(ctx)
        resolved_user_id = ctx.author.id if user_id is None else int(user_id)
        return await self._profile_for(guild_id, resolved_user_id)

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
        transfer_error = None
        async with self.bot.db.lock:
            receiver = await self.bot.db.get_profile(scope.scope_id, target.id)
            sender_balance = max(0, int(sender.get("grams", 0)))
            if sender_balance < transfer_amount:
                transfer_error = "💸 **Insufficient funds.**"
            else:
                sender["grams"] = sender_balance - transfer_amount
                receiver["grams"] = max(0, int(receiver.get("grams", 0))) + transfer_amount
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                self.bot.db.mark_profile_dirty(scope.scope_id, target.id)
        if transfer_error:
            return await ctx.send(transfer_error)
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
        for index, (user_id, amount) in enumerate(rows):
            user_id = int(user_id)
            amount = max(0, int(amount))
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

    def build_shop_embed(
        self,
        scope,
        profile: dict,
        *,
        category: str = "all",
        selected_item: str | None = None,
        notice: str | None = None,
    ) -> discord.Embed:
        wallet = max(0, int(profile.get("grams", 0) or 0))
        level = max(1, int(profile.get("level", 1) or 1))
        title = {
            "all": "🛒 Idle Grow Shop",
            "seeds": "🌱 Seed Shop",
            "equipment": "💡 Equipment Shop",
            "misc": "🔧 Misc Shop",
        }.get(category, "🛒 Idle Grow Shop")
        embed = discord.Embed(title=title, color=discord.Color.gold())
        embed.description = (
            f"**Save:** {scope.emoji} {scope.label}\n"
            f"💵 **Wallet:** ${wallet:,}  •  ⭐ **Level:** {level}\n"
            "Use the menus below to browse and buy. No command memorization required."
        )
        if notice:
            embed.add_field(name="Latest Action", value=notice[:1024], inline=False)

        if selected_item and selected_item in SHOP_ITEMS:
            item = SHOP_ITEMS[selected_item]
            cost = _shop_price(item)
            required = max(1, int(item.get("level_req", 1) or 1))
            owned = max(0, int(inv_get(profile, selected_item)))
            state = "✅ Available"
            if level < required:
                state = f"🔒 Requires Level {required}"
            elif wallet < cost:
                state = f"💸 Need ${cost - wallet:,} more"
            elif item.get("type") in {"equipment", "tool", "defense"} and owned:
                state = "✅ Already owned"
            details = [
                f"💰 **Price:** ${cost:,}",
                f"⭐ **Required Level:** {required}",
                f"🎒 **Owned:** {owned}",
                f"**Status:** {state}",
            ]
            description = str(item.get("description", "") or "").strip()
            if description:
                details.append(f"ℹ️ {description}")
            embed.add_field(
                name=f"Selected • {selected_item.title()}",
                value="\n".join(details),
                inline=False,
            )
        else:
            visible = [
                (name, item)
                for name, item in SHOP_ITEMS.items()
                if category == "all" or _shop_section(item) == category
            ]
            affordable = sum(1 for _name, item in visible if _shop_price(item) <= wallet)
            unlocked = sum(
                1
                for _name, item in visible
                if level >= max(1, int(item.get("level_req", 1) or 1))
            )
            embed.add_field(
                name="Browse",
                value=(
                    f"**{len(visible)} items** in this view • "
                    f"**{unlocked} unlocked** • **{affordable} affordable**\n"
                    "Select an item below for price, ownership, level requirement, and description."
                ),
                inline=False,
            )
        embed.set_footer(text="Shop panel expires after 5 minutes.")
        return embed

    async def _purchase_item(
        self,
        scope,
        user: dict,
        user_id: int,
        item_name: str,
    ) -> tuple[bool, str]:
        clean_name = str(item_name or "").lower().strip()
        item = SHOP_ITEMS.get(clean_name)
        if item is None:
            return False, "❌ Item not found."
        cost = _shop_price(item)
        if cost < 0:
            return False, "❌ This item is currently unavailable."
        if int(user.get("level", 1) or 1) < int(item.get("level_req", 1) or 1):
            return False, f"🔒 **{clean_name.title()}** is level locked."

        purchase_error = None
        async with self.bot.db.lock:
            if (
                item.get("type") in {"equipment", "tool", "defense"}
                and inv_get(user, clean_name) > 0
            ):
                purchase_error = f"✅ You already own **{clean_name.title()}**."
            balance = max(0, int(user.get("grams", 0) or 0))
            if purchase_error is None and balance < cost:
                purchase_error = f"💸 You need **${cost - balance:,}** more."
            new_capacity = None
            if purchase_error is None and item.get("type") == "pot_upgrade":
                try:
                    new_capacity = pot_upgrade_capacity(user, clean_name, POT_UPGRADE_LIMITS)
                except ValueError:
                    purchase_error = (
                        "🚫 You already own the maximum number of that pot upgrade."
                    )
            if purchase_error is None:
                user["grams"] = balance - cost
                inv_add(user, clean_name, 1)
                if new_capacity is not None:
                    user["max_pots"] = new_capacity
                add_progress(user, "buy", 1, user_id=int(user_id))
                check_achievements(user)
                self.bot.db.mark_profile_dirty(scope.scope_id, int(user_id))

        if purchase_error:
            return False, purchase_error
        return True, f"✅ Bought **{clean_name.title()}** for **${cost:,}**."

    @commands.hybrid_command(name="shop", aliases=["store"])
    async def shop(self, ctx, category: str = "all"):
        guild_id = require_guild_id(ctx)
        scope, profile = await self._profile(ctx)
        normalized = str(category or "all").lower().strip()
        if normalized not in {"all", "seeds", "equipment", "misc"}:
            normalized = "all"
        view = ShopView(
            self,
            ctx.author.id,
            guild_id,
            category=normalized,
        )
        view.rebuild(profile)
        embed = self.build_shop_embed(scope, profile, category=normalized)
        view.message = await ctx.send(
            embed=embed,
            view=view,
            ephemeral=ctx.interaction is not None,
        )

    @commands.hybrid_command(name="buy")
    async def buy(self, ctx, *, item_name: str):
        scope, user = await self._profile(ctx)
        if await jail_guard(ctx, user, "buy"):
            return
        _success, message = await self._purchase_item(
            scope,
            user,
            ctx.author.id,
            item_name,
        )
        await ctx.send(message)

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
        sale_error = None
        async with self.bot.db.lock:
            stash = user.setdefault("flower_stash", {})
            if amount.lower() == "all":
                sale_items = [(name, max(0, int(qty))) for name, qty in list(stash.items()) if int(qty) > 0]
                if not sale_items:
                    sale_error = "🎒 Your flower stash is empty."
            else:
                if not strain_name:
                    sale_error = "❌ Usage: `/sell amount:<amount> strain_name:<strain>`"
                    sale_items = []
                else:
                    try:
                        quantity = require_positive_amount(amount)
                    except ValueError:
                        sale_error = "❌ Amount must be a positive whole number."
                        sale_items = []
                    else:
                        clean_name = strain_name.lower().strip()
                        if max(0, int(stash.get(clean_name, 0))) < quantity:
                            sale_error = f"❌ You don\'t have {quantity}g of {clean_name}."
                            sale_items = []
                        else:
                            sale_items = [(clean_name, quantity)]
            if sale_error is None:
                for name, quantity in sale_items:
                    base_value = max(0, int(GROWTH_CYCLES.get(name, {"base_value": 10}).get("base_value", 10)))
                    unit_price = max(
                        0,
                        int(base_value * market_multiplier * district_multiplier),
                    )
                    total_earnings += unit_price * quantity
                    stash[name] = max(0, int(stash.get(name, 0))) - quantity
                    if stash[name] <= 0:
                        stash.pop(name, None)
                    sold_log.append(f"{quantity}g {name.title()}")
                user["grams"] = max(0, int(user.get("grams", 0))) + total_earnings
                stats = user.setdefault("stats", {})
                stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + total_earnings
                check_achievements(user)
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        if sale_error:
            return await ctx.send(sale_error)
        embed = discord.Embed(title="🤝 Market Sale", color=discord.Color.green())
        embed.add_field(name="Sold", value="\n".join(sold_log), inline=False)
        embed.add_field(
            name="Earnings",
            value=f"**${total_earnings:,}** (Market: {int(market_multiplier * 100)}%)",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sellconc")
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
        sale_error = None
        async with self.bot.db.lock:
            stash = user.setdefault("concentrates", {})
            if amount.lower() == "all":
                sale_items = [(name, max(0, int(qty))) for name, qty in list(stash.items()) if int(qty) > 0]
                if not sale_items:
                    sale_error = "🍯 No concentrates to sell."
            else:
                if not type_name:
                    sale_error = "❌ Usage: `/sellconc amount:<amount> type_name:<type>`"
                    sale_items = []
                else:
                    try:
                        quantity = require_positive_amount(amount)
                    except ValueError:
                        sale_error = "❌ Amount must be a positive whole number."
                        sale_items = []
                    else:
                        clean_name = type_name.lower().strip()
                        if max(0, int(stash.get(clean_name, 0))) < quantity:
                            sale_error = "❌ Not enough."
                            sale_items = []
                        else:
                            sale_items = [(clean_name, quantity)]
            if sale_error is None:
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
                check_achievements(user)
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        if sale_error:
            return await ctx.send(sale_error)
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

    @commands.hybrid_group(invoke_without_command=True)
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
        embed.set_footer(text="Use /bid auction_id:<id> amount:<amount> or /auction list item_name:<item> start_price:<price> buyout:<buyout>")
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
        list_error = None
        auction_id = None
        async with self.bot.db.lock:
            await self._settle_expired_auctions(scope.scope_id, world)
            if inv_get(user, clean_item) < 1 or not inv_take(user, clean_item, 1):
                list_error = f"❌ You don\'t have **{clean_item}**."
            else:
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
        if list_error:
            return await ctx.send(list_error)
        await ctx.send(f"🔨 **Listed!** {clean_item} for ${valid_start:,}. ID: `{auction_id}`")

    @commands.hybrid_command(name="bid")
    async def bid(self, ctx, auction_id: str, amount: int):
        scope, user = await self._profile(ctx)
        try:
            require_multiplayer(scope, "auction")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        world = await self.bot.db.get_world(scope.scope_id)
        bid_error = None
        bought_out = False
        valid_bid = 0
        async with self.bot.db.lock:
            await self._settle_expired_auctions(scope.scope_id, world)
            auctions = world.setdefault("auctions", {})
            auction = auctions.get(auction_id)
            if auction is None:
                bid_error = "❌ Invalid or expired Auction ID."
            elif int(auction["seller_id"]) == ctx.author.id:
                bid_error = "❌ You can\'t bid on your own item."
            else:
                buyout = max(0, int(auction.get("buyout", 0)))
                requested = buyout if buyout and amount >= buyout else amount
                previous_bidder_id = auction.get("highest_bidder")
                try:
                    valid_bid = validate_bid_amount(
                        requested,
                        current_bid=auction["current_bid"],
                        end_time=auction["end_time"],
                        now=time.time(),
                        allow_equal=previous_bidder_id is None,
                    )
                except ValueError as exc:
                    bid_error = f"❌ {exc}."

            if bid_error is None:
                current_bid = max(0, int(auction["current_bid"]))
                bidder_balance = max(0, int(user.get("grams", 0)))
                required_funds = valid_bid - current_bid if previous_bidder_id == ctx.author.id else valid_bid
                if bidder_balance < required_funds:
                    bid_error = "💸 Insufficient funds."

            if bid_error is None:
                previous_bidder = None
                previous_id = None
                if previous_bidder_id is not None and previous_bidder_id != ctx.author.id:
                    previous_id = int(previous_bidder_id)
                    previous_bidder = await self.bot.db.get_profile(scope.scope_id, previous_id)

                bought_out = bool(buyout and valid_bid >= buyout)
                seller = None
                seller_id = None
                if bought_out:
                    seller_id = int(auction["seller_id"])
                    seller = await self.bot.db.get_profile(scope.scope_id, seller_id)

                user["grams"] = bidder_balance - required_funds
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                if previous_bidder is not None and previous_id is not None:
                    previous_bidder["grams"] = max(0, int(previous_bidder.get("grams", 0))) + current_bid
                    self.bot.db.mark_profile_dirty(scope.scope_id, previous_id)
                auction["current_bid"] = valid_bid
                auction["highest_bidder"] = ctx.author.id
                if bought_out:
                    inv_add(user, auction["item_name"], 1)
                    seller["grams"] = max(0, int(seller.get("grams", 0))) + valid_bid
                    self.bot.db.mark_profile_dirty(scope.scope_id, seller_id)
                    del auctions[auction_id]
                self.bot.db.mark_world_dirty(scope.scope_id)
        if bid_error:
            return await ctx.send(bid_error)
        if bought_out:
            await ctx.send(f"🔨 **BOOM!** You bought out the item for ${valid_bid:,}!")
        else:
            await ctx.send(f"✅ **Bid Placed!** You are leading with ${valid_bid:,}.")


async def setup(bot):
    await bot.add_cog(Economy(bot))
