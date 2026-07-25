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


# Lab: all queues, inventory, and value calculations follow the target save.
replace_once(
    "lab.py",
    "from persistence_context import require_guild_id\n",
    "from persistence_context import require_guild_id\nfrom world_modes import (\n    effective_market_multiplier,\n    processing_queue_limit,\n    resolve_game_scope,\n)\n",
)
replace_once(
    "lab.py",
    "def _lab_market_value(user, world, base_value):\n    market_mult = float(world.get(\"market_multiplier\", 1.0))\n    prestige_mult = _lab_prestige_mult(user)\n    district_mult = 1.0\n    district = world.get(\"district\", {})\n    if (\n        district.get(\"owner_crew_id\") == user.get(\"crew_id\")\n        and time.time() < float(district.get(\"expires_at\", 0) or 0)\n    ):\n        district_mult = float(district.get(\"multiplier\", 1.10))\n    return int(base_value * market_mult * prestige_mult * district_mult)\n",
    "def _lab_market_value(user, world, base_value, scope):\n    market_mult = effective_market_multiplier(world, scope)\n    prestige_mult = _lab_prestige_mult(user)\n    district_mult = 1.0\n    district = world.get(\"district\", {})\n    if (\n        scope.multiplayer\n        and district.get(\"owner_crew_id\") == user.get(\"crew_id\")\n        and time.time() < float(district.get(\"expires_at\", 0) or 0)\n    ):\n        district_mult = float(district.get(\"multiplier\", 1.10))\n    return int(base_value * market_mult * prestige_mult * district_mult)\n",
)
replace_all(
    "lab.py",
    "        guild_id = require_guild_id(ctx)\n        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n",
    "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n",
    3,
)
replace_once(
    "lab.py",
    "        async with self.bot.db.lock:\n            if int(user.get(\"level\", 1)) < required_level:\n",
    "        async with self.bot.db.lock:\n            queue = user.setdefault(\"processing_queue\", [])\n            queue_cap = processing_queue_limit(scope)\n            if queue_cap is not None and len(queue) >= queue_cap:\n                return await ctx.send(\n                    f\"🔒 Solo Grow allows **{queue_cap} active lab batches** at a time. \"\n                    \"Collect a completed batch before starting another.\"\n                )\n            if int(user.get(\"level\", 1)) < required_level:\n",
)
replace_once(
    "lab.py",
    "            user.setdefault(\"processing_queue\", []).append(\n",
    "            queue.append(\n",
)
replace_all(
    "lab.py",
    "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)",
    "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)",
    6,
)
replace_once(
    "lab.py",
    "        guild_id = require_guild_id(ctx)\n        target = user_target or ctx.author\n        player = await self.bot.db.get_profile(guild_id, target.id)\n        world = await self.bot.db.get_world(guild_id)\n",
    "        guild_id = require_guild_id(ctx)\n        target = user_target or ctx.author\n        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n        player = await self.bot.db.get_profile(scope.scope_id, target.id)\n        world = await self.bot.db.get_world(scope.scope_id)\n",
)
replace_once(
    "lab.py",
    "            final_value = _lab_market_value(player, world, base_total)\n",
    "            final_value = _lab_market_value(player, world, base_total, scope)\n",
)
replace_once(
    "lab.py",
    "        embed = discord.Embed(title=f\"🧪 {target.display_name}'s Concentrates\", color=0x9B59B6)\n",
    "        embed = discord.Embed(title=f\"🧪 {target.display_name}'s Concentrates\", color=0x9B59B6)\n        embed.description = f\"**Active save:** {scope.emoji} {scope.label}\"\n",
)

# Casino: every wager and interactive settlement stays in the save where it started.
replace_once(
    "gambling.py",
    "from utils import GAMBLE_CONFIG, SLOTS_PAYOUTS, SLOTS_SYMBOLS, jail_guard\n",
    "from utils import GAMBLE_CONFIG, SLOTS_PAYOUTS, SLOTS_SYMBOLS, jail_guard\nfrom world_modes import (\n    WorldModeDenied,\n    require_multiplayer,\n    resolve_game_scope,\n)\n",
)
replace_once(
    "gambling.py",
    "    def __init__(self, cog: \"Gambling\", ctx, guild_id: int, user_id: int, bet: int, deck, player, dealer):\n",
    "    def __init__(self, cog: \"Gambling\", ctx, scope_id: int, user_id: int, bet: int, deck, player, dealer):\n",
)
replace_once("gambling.py", "        self.guild_id = guild_id\n", "        self.scope_id = scope_id\n")
replace_all(
    "gambling.py",
    "self.guild_id, self.user_id",
    "self.scope_id, self.user_id",
    2,
)
replace_once(
    "gambling.py",
    "    async def _profile(self, ctx, user_id: int | None = None):\n        guild_id = require_guild_id(ctx)\n        resolved = ctx.author.id if user_id is None else user_id\n        return guild_id, await self.bot.db.get_profile(guild_id, resolved)\n",
    "    async def _profile(self, ctx, user_id: int | None = None):\n        guild_id = require_guild_id(ctx)\n        resolved = ctx.author.id if user_id is None else user_id\n        scope = await resolve_game_scope(self.bot.db, guild_id, resolved)\n        return scope, await self.bot.db.get_profile(scope.scope_id, resolved)\n",
)
replace_once(
    "gambling.py",
    "    async def _atomic_game(self, ctx, raw_bet, game: str, resolver, *, min_bet=10, max_bet=None):\n        guild_id = require_guild_id(ctx)\n        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(guild_id, ctx.author.id)\n",
    "    async def _atomic_game(self, ctx, raw_bet, game: str, resolver, *, min_bet=10, max_bet=None):\n        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n",
)
replace_once(
    "gambling.py",
    "            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n        return bet, result\n",
    "            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n        return bet, result\n",
)
replace_once(
    "gambling.py",
    "        _, profile = await self._profile(ctx, target.id)\n",
    "        scope, profile = await self._profile(ctx, target.id)\n",
)
replace_once(
    "gambling.py",
    "        embed = discord.Embed(title=f\"🎰 {target.name}'s Gambling Record\", color=0x9B59B6)\n",
    "        embed = discord.Embed(title=f\"🎰 {target.name}'s Gambling Record\", color=0x9B59B6)\n        embed.description = f\"**Active save:** {scope.emoji} {scope.label}\"\n",
)
replace_once(
    "gambling.py",
    "        guild_id = require_guild_id(ctx)\n        metric = GAME_METRICS.get(_norm(game), \"casino_total_profit\")\n        rows = await self.bot.db.list_guild_casino_leaderboard(guild_id, metric=metric, limit=10)\n",
    "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        try:\n            require_multiplayer(scope, \"leaderboard\")\n        except WorldModeDenied as exc:\n            return await ctx.send(str(exc))\n        metric = GAME_METRICS.get(_norm(game), \"casino_total_profit\")\n        rows = await self.bot.db.list_guild_casino_leaderboard(\n            scope.scope_id, metric=metric, limit=10\n        )\n",
)
replace_once(
    "gambling.py",
    "        guild_id=require_guild_id(ctx)\n        async with self.bot.db.lock:\n            profile=await self.bot.db.get_profile(guild_id,ctx.author.id)\n",
    "        guild_id=require_guild_id(ctx)\n        scope=await resolve_game_scope(self.bot.db,guild_id,ctx.author.id)\n        async with self.bot.db.lock:\n            profile=await self.bot.db.get_profile(scope.scope_id,ctx.author.id)\n",
)
replace_once(
    "gambling.py",
    "            profile[\"grams\"]-=wager; self.bot.db.mark_profile_dirty(guild_id,ctx.author.id)\n",
    "            profile[\"grams\"]-=wager; self.bot.db.mark_profile_dirty(scope.scope_id,ctx.author.id)\n",
)
replace_once(
    "gambling.py",
    "        view=BlackjackView(self,ctx,guild_id,ctx.author.id,wager,deck,player,dealer)\n",
    "        view=BlackjackView(self,ctx,scope.scope_id,ctx.author.id,wager,deck,player,dealer)\n",
)
replace_all(
    "gambling.py",
    "await self.bot.db.get_profile(guild_id, ctx.author.id)",
    "await self.bot.db.get_profile(scope.scope_id, ctx.author.id)",
    1,
)
replace_all(
    "gambling.py",
    "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)",
    "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)",
    1,
)

# Sesh remains configured per Discord server, but every participant earns XP in their active save.
replace_once(
    "sesh.py",
    "from persistence_context import GuildContextRequired, require_guild_id\n",
    "from persistence_context import GuildContextRequired, require_guild_id\nfrom world_modes import mark_game_profile_dirty, resolve_game_scope\n",
)
replace_once(
    "sesh.py",
    "                profile = await self.bot.db.get_profile(\n                    session.guild_id,\n                    member.id,\n                )\n                gain = min(\n",
    "                scope = await resolve_game_scope(\n                    self.bot.db, session.guild_id, member.id\n                )\n                profile = await self.bot.db.get_profile(\n                    scope.scope_id,\n                    member.id,\n                )\n                gain = min(\n",
)
replace_all(
    "sesh.py",
    "                    self.bot.db.mark_profile_dirty(\n                        session.guild_id,\n                        member.id,\n                    )\n",
    "                    mark_game_profile_dirty(self.bot.db, scope, member.id)\n",
    2,
)
replace_once(
    "sesh.py",
    "                profile = await self.bot.db.get_profile(\n                    session.guild_id,\n                    member.id,\n                )\n                profile[\"xp\"] = int(profile.get(\"xp\", 0)) + reward\n                mark_game_profile_dirty(self.bot.db, scope, member.id)\n",
    "                scope = await resolve_game_scope(\n                    self.bot.db, session.guild_id, member.id\n                )\n                profile = await self.bot.db.get_profile(\n                    scope.scope_id,\n                    member.id,\n                )\n                profile[\"xp\"] = int(profile.get(\"xp\", 0)) + reward\n                mark_game_profile_dirty(self.bot.db, scope, member.id)\n",
)

# Profile rendering keeps privacy server-local while game data follows the target's active save.
replace_once(
    "profile_signatures.py",
    "from utils import _xp_needed_for_level, get_plant_grow_time\n",
    "from utils import _xp_needed_for_level, get_plant_grow_time\nfrom world_modes import MODE_LABELS, resolve_game_scope\n",
)
replace_once(
    "profile_signatures.py",
    "    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], set[str], list[dict[str, Any]]]:\n        account = await self.bot.db.get_account(member.id)\n        profile = await self.bot.db.get_profile(guild.id, member.id)\n        world = await self.bot.db.get_world(guild.id)\n        visible = effective_visible_fields(\n            account,\n            profile,\n            server_allowed=server_allowed,\n        )\n        platforms = shared_platform_entries(account) if \"platforms\" in visible else []\n        return account, profile, world, visible, platforms\n",
    "    ) -> tuple[\n        dict[str, Any],\n        dict[str, Any],\n        dict[str, Any],\n        set[str],\n        list[dict[str, Any]],\n        Any,\n    ]:\n        account = await self.bot.db.get_account(member.id)\n        privacy_profile = await self.bot.db.get_profile(guild.id, member.id)\n        game_scope = await resolve_game_scope(self.bot.db, guild.id, member.id)\n        profile = await self.bot.db.get_profile(game_scope.scope_id, member.id)\n        world = await self.bot.db.get_world(game_scope.scope_id)\n        visible = effective_visible_fields(\n            account,\n            privacy_profile,\n            server_allowed=server_allowed,\n        )\n        visible = set(visible)\n        if game_scope.solo:\n            visible.discard(\"crew\")\n            visible.discard(\"rank\")\n        platforms = shared_platform_entries(account) if \"platforms\" in visible else []\n        return account, profile, world, visible, platforms, game_scope\n",
)
replace_once(
    "profile_signatures.py",
    "        _account, profile, world, visible, platforms = await self._profile_components(\n            guild,\n            member,\n        )\n        embed = discord.Embed(\n",
    "        _account, profile, world, visible, platforms, game_scope = await self._profile_components(\n            guild,\n            member,\n        )\n        embed = discord.Embed(\n",
)
replace_once(
    "profile_signatures.py",
    "        embed.set_thumbnail(url=member.display_avatar.url)\n\n        if \"level\" in visible:\n",
    "        embed.set_thumbnail(url=member.display_avatar.url)\n        embed.add_field(\n            name=\"🌍 Active Save\",\n            value=f\"{game_scope.emoji} **{MODE_LABELS[game_scope.mode]}**\",\n            inline=False,\n        )\n\n        if \"level\" in visible:\n",
)
replace_once(
    "profile_signatures.py",
    "        if \"rank\" in visible:\n            rank = await self._rank_for(guild.id, member.id)\n            if rank is not None:\n                embed.add_field(name=\"🏆 Server Rank\", value=f\"#{rank}\", inline=True)\n",
    "        if \"rank\" in visible and game_scope.multiplayer:\n            rank = await self._rank_for(game_scope.scope_id, member.id)\n            if rank is not None:\n                rank_label = \"Open World Rank\" if game_scope.cross_server else \"Server Rank\"\n                embed.add_field(name=f\"🏆 {rank_label}\", value=f\"#{rank}\", inline=True)\n",
)
replace_once(
    "profile_signatures.py",
    "        _account, profile, world, visible, platforms = await self._profile_components(\n            guild,\n            member,\n            server_allowed=server_allowed,\n        )\n",
    "        _account, profile, world, visible, platforms, game_scope = await self._profile_components(\n            guild,\n            member,\n            server_allowed=server_allowed,\n        )\n",
)
replace_once(
    "profile_signatures.py",
    "        lines: list[str] = []\n        if \"level\" in visible:\n",
    "        lines: list[str] = [\n            f\"{game_scope.emoji} **{MODE_LABELS[game_scope.mode]}**\"\n        ]\n        if \"level\" in visible:\n",
)
replace_once(
    "profile_signatures.py",
    "        if \"rank\" in visible:\n            rank = await self._rank_for(guild.id, member.id)\n            if rank is not None:\n                lines.append(f\"🏆 **Server rank:** #{rank}\")\n",
    "        if \"rank\" in visible and game_scope.multiplayer:\n            rank = await self._rank_for(game_scope.scope_id, member.id)\n            if rank is not None:\n                rank_label = \"Open World rank\" if game_scope.cross_server else \"Server rank\"\n                lines.append(f\"🏆 **{rank_label}:** #{rank}\")\n",
)

# Changing a player's save or a server policy must immediately remove stale live cards.
replace_once(
    "world_modes.py",
    "        try:\n            await choose_player_mode(\n                self.cog.bot.db,\n                self.guild_id,\n                self.owner_id,\n                mode,\n            )\n",
    "        try:\n            await choose_player_mode(\n                self.cog.bot.db,\n                self.guild_id,\n                self.owner_id,\n                mode,\n            )\n",
)
replace_once(
    "world_modes.py",
    "        except WorldModeError as exc:\n            await interaction.response.send_message(f\"❌ {exc}\", ephemeral=True)\n            return\n        await interaction.response.edit_message(\n",
    "        except WorldModeError as exc:\n            await interaction.response.send_message(f\"❌ {exc}\", ephemeral=True)\n            return\n        signatures = self.cog.bot.get_cog(\"ProfileSignatures\")\n        if signatures is not None and hasattr(signatures, \"remove_user_cards\"):\n            await signatures.remove_user_cards(self.guild_id, self.owner_id)\n        await interaction.response.edit_message(\n",
)
replace_once(
    "world_modes.py",
    "    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:\n        await set_server_policy(self.cog.bot.db, self.guild_id, self.policy)\n        await interaction.response.edit_message(\n",
    "    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:\n        await set_server_policy(self.cog.bot.db, self.guild_id, self.policy)\n        signatures = self.cog.bot.get_cog(\"ProfileSignatures\")\n        if signatures is not None and hasattr(signatures, \"invalidate_guild_cards\"):\n            await signatures.invalidate_guild_cards(interaction.guild)\n        await interaction.response.edit_message(\n",
)

# Migrate source contracts that intentionally stop requiring guild-only gameplay records.
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    "def test_lab_uses_only_guild_scoped_profiles_and_worlds():\n",
    "def test_lab_uses_only_explicit_active_scope_profiles_and_worlds():\n",
)
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    '    assert "await self.bot.db.get_profile(guild_id, ctx.author.id)" in source\n    assert "await self.bot.db.get_world(guild_id)" in source\n',
    '    assert "resolve_game_scope" in source\n    assert "await self.bot.db.get_profile(scope.scope_id, ctx.author.id)" in source\n    assert "await self.bot.db.get_world(scope.scope_id)" in source\n',
)
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    "def test_lab_market_value_requires_an_explicit_guild_world():\n",
    "def test_lab_market_value_requires_an_explicit_active_world_and_scope():\n",
)
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    '    assert "def _lab_market_value(user, world, base_value):" in source\n    assert "_lab_market_value(player, world, base_total)" in source\n',
    '    assert "def _lab_market_value(user, world, base_value, scope):" in source\n    assert "effective_market_multiplier(world, scope)" in source\n    assert "_lab_market_value(player, world, base_total, scope)" in source\n    assert "processing_queue_limit(scope)" in source\n',
)
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    "def test_lab_mutations_mark_only_the_current_profile_dirty():\n",
    "def test_lab_mutations_mark_only_the_active_scope_profile_dirty():\n",
)
replace_once(
    "tests/test_lab_scoped_persistence_contract.py",
    '    assert source.count("self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)") >= 5\n',
    '    assert source.count("self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)") >= 5\n',
)
