from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != expected:
        raise RuntimeError(f"expected {expected} anchors in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new), encoding="utf-8")


# ECONOMY ---------------------------------------------------------------------
replace_once(
    "economy.py",
    "from utils import SHOP_ITEMS, calculate_level, inv_add, inv_get, inv_take, jail_guard\n",
    "from utils import SHOP_ITEMS, calculate_level, inv_add, inv_get, inv_take, jail_guard\n"
    "from world_modes import (\n"
    "    WorldModeDenied,\n"
    "    effective_market_multiplier,\n"
    "    require_multiplayer,\n"
    "    require_same_multiplayer_scope,\n"
    "    resolve_game_scope,\n"
    ")\n",
)
replace_once(
    "economy.py",
    "    async def _profile(self, ctx, user_id: int | None = None):\n"
    "        guild_id = require_guild_id(ctx)\n"
    "        resolved_user_id = ctx.author.id if user_id is None else user_id\n"
    "        return await self.bot.db.get_profile(guild_id, resolved_user_id)\n\n"
    "    async def _world(self, ctx):\n"
    "        guild_id = require_guild_id(ctx)\n"
    "        return await self.bot.db.get_world(guild_id)\n",
    "    async def _profile(self, ctx, user_id: int | None = None):\n"
    "        guild_id = require_guild_id(ctx)\n"
    "        resolved_user_id = ctx.author.id if user_id is None else user_id\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)\n"
    "        profile = await self.bot.db.get_profile(scope.scope_id, resolved_user_id)\n"
    "        return scope, profile\n\n"
    "    async def _world(self, ctx, user_id: int | None = None):\n"
    "        guild_id = require_guild_id(ctx)\n"
    "        resolved_user_id = ctx.author.id if user_id is None else user_id\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, resolved_user_id)\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n"
    "        return scope, world\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(guild_id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n",
)
replace_once(
    "economy.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n"
    "        await ctx.send(f\"✅ Bought **{quantity}x {item_name.title()}** for **${total_cost:,}**.\")\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n"
    "        await ctx.send(f\"✅ Bought **{quantity}x {item_name.title()}** for **${total_cost:,}**.\")\n",
)
replace_once(
    "economy.py",
    "        target = user_target or ctx.author\n"
    "        user = await self._profile(ctx, target.id)\n"
    "        world = await self._world(ctx)\n",
    "        target = user_target or ctx.author\n"
    "        scope, user = await self._profile(ctx, target.id)\n"
    "        _world_scope, world = await self._world(ctx, target.id)\n",
)
replace_once(
    "economy.py",
    "        embed = discord.Embed(title=f\"💰 {target.name}'s Empire\", color=0xF1C40F)\n",
    "        embed = discord.Embed(title=f\"💰 {target.name}'s Empire\", color=0xF1C40F)\n"
    "        embed.description = f\"**Active save:** {scope.emoji} {scope.label}\"\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        if await jail_guard(ctx, user, \"sell\"):\n"
    "            return\n"
    "        world = await self.bot.db.get_world(guild_id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        if await jail_guard(ctx, user, \"sell\"):\n"
    "            return\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n",
)
replace_once(
    "economy.py",
    "            market_mult = float(world.get(\"market_multiplier\", 1.0))\n"
    "            district_mult = 1.0\n"
    "            district = world.get(\"district\", {})\n"
    "            if (\n"
    "                district.get(\"owner_crew_id\") == user.get(\"crew_id\")\n",
    "            market_mult = effective_market_multiplier(world, scope)\n"
    "            district_mult = 1.0\n"
    "            district = world.get(\"district\", {})\n"
    "            if (\n"
    "                scope.multiplayer\n"
    "                and district.get(\"owner_crew_id\") == user.get(\"crew_id\")\n",
)
replace_once(
    "economy.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n\n"
    "        await ctx.send(\n"
    "            f\"💵 Sold **{qty}x {item.title()}** for **${payout:,}** clean cash.\"\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n\n"
    "        await ctx.send(\n"
    "            f\"💵 Sold **{qty}x {item.title()}** for **${payout:,}** clean cash.\"\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        async with self.bot.db.lock:\n"
    "            sender = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "            receiver = await self.bot.db.get_profile(guild_id, target.id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        target_scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n"
    "        try:\n"
    "            require_same_multiplayer_scope(scope, target_scope, \"transfer\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        async with self.bot.db.lock:\n"
    "            sender = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "            receiver = await self.bot.db.get_profile(scope.scope_id, target.id)\n",
)
replace_once(
    "economy.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n"
    "            self.bot.db.mark_profile_dirty(guild_id, target.id)\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n"
    "            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        rows = await self.bot.db.list_guild_leaderboard(guild_id, limit=10)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        try:\n"
    "            require_multiplayer(scope, \"leaderboard\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        rows = await self.bot.db.list_guild_leaderboard(scope.scope_id, limit=10)\n",
)
replace_once(
    "economy.py",
    "        embed = discord.Embed(\n"
    "            title=f\"🏆 {ctx.guild.name} Leaderboard\",\n",
    "        leaderboard_name = \"Open World\" if scope.cross_server else ctx.guild.name\n"
    "        embed = discord.Embed(\n"
    "            title=f\"🏆 {leaderboard_name} Leaderboard\",\n",
)
replace_once(
    "economy.py",
    "        world = await self._world(ctx)\n"
    "        multiplier = float(world.get(\"market_multiplier\", 1.0))\n",
    "        scope, world = await self._world(ctx)\n"
    "        multiplier = effective_market_multiplier(world, scope)\n",
)
replace_once(
    "economy.py",
    "        district = world.get(\"district\", {})\n"
    "        if district and time.time() < float(district.get(\"expires_at\", 0) or 0):\n",
    "        district = world.get(\"district\", {})\n"
    "        if scope.multiplayer and district and time.time() < float(district.get(\"expires_at\", 0) or 0):\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        cost = max(1, int(user.get(\"max_pots\", 3))) * 5_000\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        cost = max(1, int(user.get(\"max_pots\", 3))) * 5_000\n",
)
replace_once(
    "economy.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n"
    "        await ctx.send(\n"
    "            f\"🪴 **Pot Capacity Upgraded!** You can now grow {user['max_pots']} plants at once.\"\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n"
    "        await ctx.send(\n"
    "            f\"🪴 **Pot Capacity Upgraded!** You own capacity for {user['max_pots']} plants. \"\n"
    "            f\"Active {scope.label} limits still apply.\"\n",
)
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(guild_id)\n"
    "        async with self.bot.db.lock:\n"
    "            stash = user.setdefault(\"concentrate_stash\", {})\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n"
    "        async with self.bot.db.lock:\n"
    "            stash = user.setdefault(\"concentrate_stash\", {})\n",
)
replace_once(
    "economy.py",
    "            final_payout = int(base_total * float(world.get(\"market_multiplier\", 1.0)))\n",
    "            final_payout = int(base_total * effective_market_multiplier(world, scope))\n",
)
replace_once(
    "economy.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n"
    "        await ctx.send(\n"
    "            f\"💎 Sold **{qty}x {item_name.title()}** for **${final_payout:,}** clean cash.\"\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n"
    "        await ctx.send(\n"
    "            f\"💎 Sold **{qty}x {item_name.title()}** for **${final_payout:,}** clean cash.\"\n",
)
replace_once(
    "economy.py",
    "    async def _settle_expired_auctions(self, guild_id: int, world: dict | None = None) -> int:\n"
    "        if world is None:\n"
    "            world = await self.bot.db.get_world(guild_id)\n",
    "    async def _settle_expired_auctions(self, scope_id: int, world: dict | None = None) -> int:\n"
    "        if world is None:\n"
    "            world = await self.bot.db.get_world(scope_id)\n",
)
replace_all("economy.py", "get_profile(guild_id,", "get_profile(scope_id,", 2)
replace_all("economy.py", "mark_profile_dirty(guild_id,", "mark_profile_dirty(scope_id,", 2)
replace_once("economy.py", "            self.bot.db.mark_world_dirty(guild_id)\n        return settled\n", "            self.bot.db.mark_world_dirty(scope_id)\n        return settled\n")
replace_once(
    "economy.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        world = await self.bot.db.get_world(guild_id)\n"
    "        await self._settle_expired_auctions(guild_id, world)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        try:\n"
    "            require_multiplayer(scope, \"auction\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n"
    "        await self._settle_expired_auctions(scope.scope_id, world)\n",
)
replace_once("economy.py", "await self._auction_list(ctx, guild_id, world, args)", "await self._auction_list(ctx, scope.scope_id, world, args)")
replace_once("economy.py", "await self._auction_bid(ctx, guild_id, world, args)", "await self._auction_bid(ctx, scope.scope_id, world, args)")
replace_once("economy.py", "await self._auction_cancel(ctx, guild_id, world, args)", "await self._auction_cancel(ctx, scope.scope_id, world, args)")

# SOCIAL ----------------------------------------------------------------------
replace_once(
    "social.py",
    "from utils import calculate_level, get_plant_grow_time\n",
    "from utils import calculate_level, get_plant_grow_time\n"
    "from world_modes import (\n"
    "    WorldModeDenied,\n"
    "    require_multiplayer,\n"
    "    resolve_game_scope,\n"
    ")\n",
)
replace_once(
    "social.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        target = user_target or ctx.author\n"
    "        user = await self.bot.db.get_profile(guild_id, target.id)\n"
    "        world = await self.bot.db.get_world(guild_id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        target = user_target or ctx.author\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, target.id)\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n",
)
replace_once(
    "social.py",
    "        embed = discord.Embed(title=f\"👤 {target.name}'s Profile\", color=target.color)\n",
    "        embed = discord.Embed(title=f\"👤 {target.name}'s Profile\", color=target.color)\n"
    "        embed.description = f\"**Active save:** {scope.emoji} {scope.label}\"\n",
)
replace_once(
    "social.py",
    "        crew_id = user.get(\"crew_id\")\n"
    "        if crew_id:\n",
    "        crew_id = user.get(\"crew_id\") if scope.multiplayer else None\n"
    "        if crew_id:\n",
)
replace_once(
    "social.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(guild_id)\n\n"
    "        action = (action or \"\").lower().strip()\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        try:\n"
    "            require_multiplayer(scope, \"crew\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n\n"
    "        action = (action or \"\").lower().strip()\n",
)
replace_all("social.py", "ctx, guild_id, user, world", "ctx, scope.scope_id, user, world", 6)
replace_once(
    "social.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        world = await self.bot.db.get_world(guild_id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        try:\n"
    "            require_multiplayer(scope, \"district\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        world = await self.bot.db.get_world(scope.scope_id)\n",
)
replace_once(
    "social.py",
    "        guild_id = int(message.guild.id)\n"
    "        async with self.bot.db.lock:\n"
    "            user_data = await self.bot.db.get_profile(guild_id, rewarded_user.id)\n",
    "        guild_id = int(message.guild.id)\n"
    "        reward_scope = await resolve_game_scope(self.bot.db, guild_id, rewarded_user.id)\n"
    "        async with self.bot.db.lock:\n"
    "            user_data = await self.bot.db.get_profile(\n"
    "                reward_scope.scope_id, rewarded_user.id\n"
    "            )\n",
)
replace_once(
    "social.py",
    "            self.bot.db.mark_profile_dirty(guild_id, rewarded_user.id)\n",
    "            self.bot.db.mark_profile_dirty(reward_scope.scope_id, rewarded_user.id)\n",
)

# CRIME -----------------------------------------------------------------------
replace_once(
    "crime.py",
    "from utils import add_heat, has_item, jail_guard\n",
    "from utils import add_heat, has_item, jail_guard\n"
    "from world_modes import (\n"
    "    WorldModeDenied,\n"
    "    require_multiplayer,\n"
    "    require_same_multiplayer_scope,\n"
    "    resolve_game_scope,\n"
    ")\n",
)
replace_once(
    "crime.py",
    "    def _session_key(guild_id: int, kind: str, identifier: object) -> str:\n"
    "        return f\"guild:{guild_id}:{kind}:{identifier}\"\n",
    "    def _session_key(scope_id: int, kind: str, identifier: object) -> str:\n"
    "        return f\"scope:{scope_id}:{kind}:{identifier}\"\n",
)
replace_once(
    "crime.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n"
    "        if await jail_guard(ctx, user, \"heist\"):\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n"
    "        if await jail_guard(ctx, user, \"heist\"):\n",
)
replace_once("crime.py", "await self._solo_heist(ctx, guild_id, user, arg or \"stealth\")", "await self._solo_heist(ctx, scope, user, arg or \"stealth\")")
replace_once(
    "crime.py",
    "        elif mode in (\"crew\", \"coop\"):\n"
    "            await self._start_crew_heist(ctx, guild_id, user)\n"
    "        elif mode == \"join\":\n"
    "            await self._join_crew_heist(ctx, guild_id, user)\n"
    "        elif mode in (\"raid\", \"pvp\"):\n"
    "            await self._raid(ctx, guild_id, user, arg)\n",
    "        elif mode in (\"crew\", \"coop\"):\n"
    "            try:\n"
    "                require_multiplayer(scope, \"crew_heist\")\n"
    "            except WorldModeDenied as exc:\n"
    "                return await ctx.send(str(exc))\n"
    "            await self._start_crew_heist(ctx, scope, user)\n"
    "        elif mode == \"join\":\n"
    "            try:\n"
    "                require_multiplayer(scope, \"crew_heist\")\n"
    "            except WorldModeDenied as exc:\n"
    "                return await ctx.send(str(exc))\n"
    "            await self._join_crew_heist(ctx, scope, user)\n"
    "        elif mode in (\"raid\", \"pvp\"):\n"
    "            try:\n"
    "                require_multiplayer(scope, \"raid\")\n"
    "            except WorldModeDenied as exc:\n"
    "                return await ctx.send(str(exc))\n"
    "            await self._raid(ctx, scope, user, arg)\n",
)
replace_once("crime.py", "async def _solo_heist(self, ctx, guild_id: int, user: dict, plan: str)", "async def _solo_heist(self, ctx, scope, user: dict, plan: str)")
replace_once("crime.py", "self._session_key(guild_id, \"user\", ctx.author.id)", "self._session_key(scope.scope_id, \"user\", ctx.author.id)")
replace_once("crime.py", "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n        finally:", "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n        finally:")
replace_once("crime.py", "async def _start_crew_heist(self, ctx, guild_id: int, user: dict)", "async def _start_crew_heist(self, ctx, scope, user: dict)")
replace_all("crime.py", "await self.bot.db.get_world(guild_id)", "await self.bot.db.get_world(scope.scope_id)", 3)
replace_once("crime.py", "self._session_key(guild_id, \"crew\", crew_id)", "self._session_key(scope.scope_id, \"crew\", crew_id)")
replace_once(
    "crime.py",
    "            for member_id in session.get(\"members\", set()):\n"
    "                member = await self.bot.db.get_profile(guild_id, member_id)\n"
    "                if self._in_jail(member) <= 0 and str(member.get(\"crew_id\")) == str(crew_id):\n"
    "                    valid_members.append((int(member_id), member))\n",
    "            for member_id in session.get(\"members\", set()):\n"
    "                member_scope = await resolve_game_scope(\n"
    "                    self.bot.db, scope.guild_id, member_id\n"
    "                )\n"
    "                if member_scope.scope_id != scope.scope_id:\n"
    "                    continue\n"
    "                member = await self.bot.db.get_profile(scope.scope_id, member_id)\n"
    "                if self._in_jail(member) <= 0 and str(member.get(\"crew_id\")) == str(crew_id):\n"
    "                    valid_members.append((int(member_id), member))\n",
)
replace_all("crime.py", "self.bot.db.mark_profile_dirty(guild_id, member_id)", "self.bot.db.mark_profile_dirty(scope.scope_id, member_id)", 2)
replace_once("crime.py", "self.bot.db.mark_world_dirty(guild_id)\n\n        if success:", "self.bot.db.mark_world_dirty(scope.scope_id)\n\n        if success:")
replace_once("crime.py", "async def _join_crew_heist(self, ctx, guild_id: int, user: dict)", "async def _join_crew_heist(self, ctx, scope, user: dict)")
replace_once("crime.py", "self._session_key(guild_id, \"crew\", crew_id)", "self._session_key(scope.scope_id, \"crew\", crew_id)")
replace_once("crime.py", "async def _raid(self, ctx, guild_id: int, user: dict, target_id: str | None)", "async def _raid(self, ctx, scope, user: dict, target_id: str | None)")
replace_once("crime.py", "profile = await self.bot.db.get_profile(guild_id, int(member_id))", "profile = await self.bot.db.get_profile(scope.scope_id, int(member_id))")
replace_once("crime.py", "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n            self.bot.db.mark_world_dirty(guild_id)", "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n            self.bot.db.mark_world_dirty(scope.scope_id)")
replace_once(
    "crime.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        robber = await self.bot.db.get_profile(guild_id, ctx.author.id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        target_scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n"
    "        try:\n"
    "            require_same_multiplayer_scope(scope, target_scope, \"theft\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        robber = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n",
)
replace_once("crime.py", "victim = await self.bot.db.get_profile(guild_id, target.id)", "victim = await self.bot.db.get_profile(scope.scope_id, target.id)")
replace_once("crime.py", "self.bot.db.mark_profile_dirty(guild_id, target.id)", "self.bot.db.mark_profile_dirty(scope.scope_id, target.id)")
replace_once("crime.py", "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n\n        if success:", "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n\n        if success:")
replace_all(
    "crime.py",
    "        guild_id = require_guild_id(ctx)\n        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n",
    "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n",
    2,
)
replace_all("crime.py", "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)", "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)", 1)
replace_once(
    "crime.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        target = member or ctx.author\n"
    "        profile = await self.bot.db.get_profile(guild_id, target.id)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        target = member or ctx.author\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n"
    "        profile = await self.bot.db.get_profile(scope.scope_id, target.id)\n",
)
replace_once(
    "crime.py",
    "        embed = discord.Embed(title=f\"🏆 Heist Stats: {target.display_name}\", color=0x3498DB)\n",
    "        embed = discord.Embed(title=f\"🏆 Heist Stats: {target.display_name}\", color=0x3498DB)\n"
    "        embed.description = f\"**Active save:** {scope.emoji} {scope.label}\"\n",
)
replace_once(
    "crime.py",
    "        guild_id = require_guild_id(ctx)\n"
    "        rows = await self.bot.db.list_guild_heist_leaderboard(guild_id, limit=10)\n",
    "        guild_id = require_guild_id(ctx)\n"
    "        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n"
    "        try:\n"
    "            require_multiplayer(scope, \"leaderboard\")\n"
    "        except WorldModeDenied as exc:\n"
    "            return await ctx.send(str(exc))\n"
    "        rows = await self.bot.db.list_guild_heist_leaderboard(scope.scope_id, limit=10)\n",
)

# MIGRATE EXISTING CONTRACTS --------------------------------------------------
(ROOT / "tests/test_economy_scoped_persistence_contract.py").write_text(
    '''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_economy_uses_explicit_active_scope_storage_paths():\n    source = (ROOT / "economy.py").read_text(encoding="utf-8")\n    assert "resolve_game_scope" in source\n    assert "scope.scope_id" in source\n    assert "require_same_multiplayer_scope" in source\n    assert "require_multiplayer" in source\n    assert "self.bot.db.get_user" not in source\n    assert "self.bot.db.world_state" not in source\n    assert "self.bot.db.data" not in source\n    assert "await self.bot.db.save()" not in source\n\n\ndef test_economy_uses_backend_leaderboard_queries_for_active_scope():\n    source = (ROOT / "economy.py").read_text(encoding="utf-8")\n    assert "list_guild_leaderboard(scope.scope_id, limit=10)" in source\n    assert "for uid, data in self.bot.db.data.items()" not in source\n\n\ndef test_auction_state_and_settlement_use_explicit_multiplayer_scope():\n    source = (ROOT / "economy.py").read_text(encoding="utf-8")\n    assert "def _settle_expired_auctions(self, scope_id" in source\n    assert "await self.bot.db.get_world(scope_id)" in source\n    assert "await self._settle_expired_auctions(scope.scope_id, world)" in source\n    assert "require_multiplayer(scope, \"auction\")" in source\n''',
    encoding="utf-8",
)
(ROOT / "tests/test_social_guild_scope_contract.py").write_text(
    '''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_social_uses_explicit_active_scope_storage_paths():\n    source = (ROOT / "social.py").read_text(encoding="utf-8")\n    assert "resolve_game_scope" in source\n    assert "scope.scope_id" in source\n    assert "require_multiplayer" in source\n    assert "self.bot.db.get_user" not in source\n    assert "self.bot.db.world_state" not in source\n    assert "self.bot.db.data" not in source\n    assert "await self.bot.db.save()" not in source\n    assert "db_manager" not in source\n\n\ndef test_social_support_rewards_follow_the_rewarded_users_active_save():\n    source = (ROOT / "social.py").read_text(encoding="utf-8")\n    assert "if message.guild is None" in source\n    assert "reward_scope = await resolve_game_scope" in source\n    assert "reward_scope.scope_id" in source\n\n\ndef test_social_no_longer_owns_daily_or_sesh_interactions():\n    source = (ROOT / "social.py").read_text(encoding="utf-8")\n    assert '@commands.hybrid_command(name="daily")' not in source\n    assert '@commands.hybrid_command(name="sesh")' not in source\n    assert '@commands.hybrid_command(name="movie")' not in source\n    assert "class SeshView" not in source\n    assert "_ACTIVE_SESHES" not in source\n\n\ndef test_social_crew_and_district_state_use_the_active_multiplayer_world():\n    source = (ROOT / "social.py").read_text(encoding="utf-8")\n    assert "def get_crews(world: dict)" in source\n    assert 'district = world.setdefault("district", {})' in source\n    assert "require_multiplayer(scope, \"crew\")" in source\n    assert "require_multiplayer(scope, \"district\")" in source\n''',
    encoding="utf-8",
)
(ROOT / "tests/test_crime_scoped_persistence_contract.py").write_text(
    '''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_crime_routes_gameplay_through_explicit_active_scopes():\n    source = (ROOT / "crime.py").read_text(encoding="utf-8")\n    assert "resolve_game_scope" in source\n    assert "scope.scope_id" in source\n    assert "require_multiplayer" in source\n    assert "require_same_multiplayer_scope" in source\n    assert "self.bot.db.get_user" not in source\n    assert "self.bot.db.world_state" not in source\n    assert "self.bot.db.data" not in source\n    assert "await self.bot.db.save()" not in source\n\n\ndef test_crime_sessions_and_rankings_are_active_scope_isolated():\n    source = (ROOT / "crime.py").read_text(encoding="utf-8")\n    assert 'return f"scope:{scope_id}:{kind}:{identifier}"' in source\n    assert "list_guild_heist_leaderboard(scope.scope_id, limit=10)" in source\n    assert "for user_id, data in self.bot.db.data.items()" not in source\n\n\ndef test_heist_channel_configuration_remains_real_guild_scoped():\n    source = (ROOT / "crime.py").read_text(encoding="utf-8")\n    block = source.split('name="heistset"', 1)[1]\n    assert "await self.bot.db.get_world(guild_id)" in block\n    assert "self.bot.db.mark_world_dirty(guild_id)" in block\n\n\ndef test_supabase_has_indexed_heist_win_projection():\n    migration = (ROOT / "migrations/001_guild_scoped_persistence.sql").read_text(encoding="utf-8")\n    backend = (ROOT / "supabase_scoped_backend.py").read_text(encoding="utf-8")\n    assert "heist_wins bigint generated always as" in migration\n    assert "guild_profiles_guild_heist_wins_idx" in migration\n    assert "(guild_id, heist_wins desc, user_id)" in migration\n    assert 'metric="heist_wins"' in backend\n    assert '.eq("guild_id", guild_id)' in backend\n    assert '.order(metric, desc=True)' in backend\n''',
    encoding="utf-8",
)
