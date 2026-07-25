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


# Setup UI: expose the world policy without coupling guild config to gameplay scope.
replace_once(
    "setup.py",
    "from profile_signatures import (\n    ALL_PROFILE_FIELDS,\n    DEFAULT_SERVER_ALLOWED_FIELDS,\n    FIELD_LABELS,\n    SIGNATURE_ALLOWED_FIELDS_KEY,\n    SIGNATURE_CHANNELS_KEY,\n    SIGNATURE_CONFIG_KEY,\n    SIGNATURE_ENABLED_KEY,\n)\n",
    "from profile_signatures import (\n    ALL_PROFILE_FIELDS,\n    DEFAULT_SERVER_ALLOWED_FIELDS,\n    FIELD_LABELS,\n    SIGNATURE_ALLOWED_FIELDS_KEY,\n    SIGNATURE_CHANNELS_KEY,\n    SIGNATURE_CONFIG_KEY,\n    SIGNATURE_ENABLED_KEY,\n)\nfrom world_modes import (\n    ServerWorldModeView,\n    build_server_mode_embed,\n    world_mode_status,\n)\n",
)
replace_once(
    "setup.py",
    "    @discord.ui.button(\n        label=\"Optional Sesh\",\n",
    "    @discord.ui.button(\n        label=\"World Mode\",\n        emoji=\"🌍\",\n        style=discord.ButtonStyle.secondary,\n        row=3,\n    )\n    async def world_mode_setup(\n        self,\n        interaction: discord.Interaction,\n        _button: discord.ui.Button,\n    ) -> None:\n        guild = interaction.guild\n        if guild is None:\n            await interaction.response.send_message(\n                \"❌ Server context is unavailable.\", ephemeral=True\n            )\n            return\n        world_modes = self.cog.bot.get_cog(\"WorldModes\")\n        if world_modes is None:\n            await interaction.response.send_message(\n                \"❌ World mode controls are unavailable.\", ephemeral=True\n            )\n            return\n        view = ServerWorldModeView(world_modes, interaction.user.id, guild.id)\n        await interaction.response.send_message(\n            embed=await build_server_mode_embed(self.cog.bot.db, guild),\n            view=view,\n            ephemeral=True,\n        )\n        view.message = await interaction.original_response()\n\n    @discord.ui.button(\n        label=\"Optional Sesh\",\n",
)
replace_once(
    "setup.py",
    "        embed.add_field(name=\"🚨 Error Logging\", value=error_status, inline=False)\n        embed.add_field(name=\"🔥 Optional Sesh\", value=await self.sesh_status(guild), inline=False)\n",
    "        embed.add_field(name=\"🚨 Error Logging\", value=error_status, inline=False)\n        embed.add_field(\n            name=\"🌍 World Mode\",\n            value=await world_mode_status(self.bot.db, guild.id),\n            inline=False,\n        )\n        embed.add_field(name=\"🔥 Optional Sesh\", value=await self.sesh_status(guild), inline=False)\n",
)
replace_once(
    "setup.py",
    '            value="Multiplayer • Notifications",\n',
    '            value="Notifications",\n',
)

# Progression: daily rewards, quests, achievements, and level views follow the active save.
replace_once(
    "progression.py",
    "from progression_data import ACHIEVEMENTS\n",
    "from progression_data import ACHIEVEMENTS\nfrom world_modes import resolve_game_scope\n",
)
replace_once(
    "progression.py",
    "    async def _profile(self, ctx):\n        guild_id = require_guild_id(ctx)\n        profile = await self.bot.db.get_profile(guild_id, ctx.author.id)\n        return guild_id, profile\n",
    "    async def _profile(self, ctx):\n        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n        return scope, profile\n",
)
replace_all(
    "progression.py",
    "guild_id, profile = await self._profile(ctx)",
    "scope, profile = await self._profile(ctx)",
    3,
)
replace_all(
    "progression.py",
    "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)",
    "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)",
    3,
)

# Farming: weather, plants, harvests, and stored upgrades route to the active scope.
replace_once(
    "farming.py",
    "from persistence_context import require_guild_id\n",
    "from persistence_context import require_guild_id\nfrom world_modes import effective_pot_capacity, resolve_game_scope\n",
)
replace_all(
    "farming.py",
    "        guild_id = require_guild_id(ctx)\n        user = await self.bot.db.get_profile(guild_id, ctx.author.id)\n",
    "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n",
    4,
)
replace_all(
    "farming.py",
    "await self.bot.db.get_world(guild_id)",
    "await self.bot.db.get_world(scope.scope_id)",
    3,
)
replace_once(
    "farming.py",
    '            max_pots = max(0, int(user.get("max_pots", 3)))\n',
    "            max_pots = effective_pot_capacity(user, scope)\n",
)
replace_all(
    "farming.py",
    "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)",
    "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)",
    3,
)

# Quick commands: calculators and smart planting use the same active profile/world.
replace_once(
    "quick.py",
    "from persistence_context import GuildContextRequired, require_guild_id\n",
    "from persistence_context import GuildContextRequired, require_guild_id\nfrom world_modes import (\n    effective_market_multiplier,\n    effective_pot_capacity,\n    resolve_game_scope,\n)\n",
)
replace_once(
    "quick.py",
    "    async def _scope(self, ctx):\n        guild_id = require_guild_id(ctx)\n        profile = await self.bot.db.get_profile(guild_id, ctx.author.id)\n        world = await self.bot.db.get_world(guild_id)\n        return guild_id, profile, world\n",
    "    async def _scope(self, ctx):\n        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)\n        profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)\n        world = await self.bot.db.get_world(scope.scope_id)\n        return scope, profile, world\n",
)
replace_once(
    "quick.py",
    "        _, profile, world = await self._scope(ctx)\n        now = time.time()\n        last_daily",
    "        scope, profile, world = await self._scope(ctx)\n        now = time.time()\n        last_daily",
)
replace_once(
    "quick.py",
    '        if profile.get("crew_id"):\n',
    '        if scope.multiplayer and profile.get("crew_id"):\n',
)
replace_once(
    "quick.py",
    '        market = max(0.0, float(world.get("market_multiplier", 1.0) or 1.0))\n',
    "        market = effective_market_multiplier(world, scope)\n",
)
replace_once(
    "quick.py",
    "        guild_id, profile, _ = await self._scope(ctx)\n",
    "        scope, profile, _ = await self._scope(ctx)\n",
)
replace_once(
    "quick.py",
    '            free_slots = max(0, _safe_int(profile.get("max_pots"), 3) - len(plants))\n',
    "            max_pots = effective_pot_capacity(profile, scope)\n            free_slots = max(0, max_pots - len(plants))\n",
)
replace_once(
    "quick.py",
    "                return await ctx.send(f\"🚫 **No Pots Available!** ({len(plants)}/{profile.get('max_pots', 3)})\")\n",
    "                return await ctx.send(f\"🚫 **No Pots Available!** ({len(plants)}/{max_pots})\")\n",
)
replace_once(
    "quick.py",
    "                self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)\n",
    "                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)\n",
)

# Owner tools: mutate the target's selected save and say which save was changed.
replace_once(
    "admin.py",
    "from persistence_context import (\n    get_context_profile,\n    mark_context_profile_dirty,\n    require_guild_id,\n)\n",
    "from persistence_context import require_guild_id\n",
)
replace_once(
    "admin.py",
    "from utils import inv_add\n",
    "from utils import inv_add\nfrom world_modes import resolve_game_scope\n",
)
for command_body, replacement in (
    (
        "        require_guild_id(ctx)\n        async with self.bot.db.lock:\n            profile = await get_context_profile(self.bot.db, ctx, target.id)\n            profile[\"grams\"] = int(amount)\n            mark_context_profile_dirty(self.bot.db, ctx, target.id)\n        await ctx.send(f\"✅ Set {target.name}'s balance to **${amount:,}** in this server.\")\n",
        "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(scope.scope_id, target.id)\n            profile[\"grams\"] = int(amount)\n            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)\n        await ctx.send(f\"✅ Set {target.name}'s balance to **${amount:,}** in {scope.label}.\")\n",
    ),
    (
        "        require_guild_id(ctx)\n        async with self.bot.db.lock:\n            profile = await get_context_profile(self.bot.db, ctx, target.id)\n            inv_add(profile, clean_name, quantity)\n            mark_context_profile_dirty(self.bot.db, ctx, target.id)\n        await ctx.send(f\"✅ Gave **x{quantity} {clean_name}** to {target.name} in this server.\")\n",
        "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(scope.scope_id, target.id)\n            inv_add(profile, clean_name, quantity)\n            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)\n        await ctx.send(f\"✅ Gave **x{quantity} {clean_name}** to {target.name} in {scope.label}.\")\n",
    ),
    (
        "        require_guild_id(ctx)\n        async with self.bot.db.lock:\n            profile = await get_context_profile(self.bot.db, ctx, target.id)\n            profile[\"level\"] = validated_level\n            profile[\"xp\"] = 0\n            mark_context_profile_dirty(self.bot.db, ctx, target.id)\n        await ctx.send(f\"✅ Set {target.name}'s level to **{validated_level}** in this server.\")\n",
        "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(scope.scope_id, target.id)\n            profile[\"level\"] = validated_level\n            profile[\"xp\"] = 0\n            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)\n        await ctx.send(f\"✅ Set {target.name}'s level to **{validated_level}** in {scope.label}.\")\n",
    ),
):
    replace_once("admin.py", command_body, replacement)
replace_once(
    "admin.py",
    "        require_guild_id(ctx)\n        await ctx.send(\n            f\"⚠️ **WARNING:** Wipe {target.name}'s Idle Grow profile in this server? Type `yes`.\"\n        )\n",
    "        guild_id = require_guild_id(ctx)\n        scope = await resolve_game_scope(self.bot.db, guild_id, target.id)\n        await ctx.send(\n            f\"⚠️ **WARNING:** Wipe {target.name}'s **{scope.label}** profile? Type `yes`.\"\n        )\n",
)
replace_once(
    "admin.py",
    "        async with self.bot.db.lock:\n            profile = await get_context_profile(self.bot.db, ctx, target.id)\n            profile.clear()\n            profile.update(make_default_profile())\n            mark_context_profile_dirty(self.bot.db, ctx, target.id)\n        await ctx.send(f\"💀 **Wiped {target.name}'s profile in this server.**\")\n",
    "        async with self.bot.db.lock:\n            profile = await self.bot.db.get_profile(scope.scope_id, target.id)\n            profile.clear()\n            profile.update(make_default_profile())\n            self.bot.db.mark_profile_dirty(scope.scope_id, target.id)\n        await ctx.send(f\"💀 **Wiped {target.name}'s {scope.label} profile.**\")\n",
)

# Assistant copy must not imply that server-local and global saves blend together.
replace_once(
    "ai.py",
    "Explain that server economies and progress\nmay be guild-scoped. Sesh is an optional server feature configured by server managers.\n",
    "Explain Solo Grow, Open World, Player Choice, and Current Server World when relevant.\nSolo and Open World saves never mix: cash, plants, inventory, crews, cooldowns, and progress\nstay in their own save. Sesh is an optional server feature configured by server managers.\n",
)

# Keep the legacy-artifact guard aware of the new canonical module.
replace_once(
    ".github/workflows/ci.yml",
    "            admin.py ai.py crime.py economy.py farming.py gambling.py lab.py progression.py quick.py sesh.py social.py tasks.py\n",
    "            admin.py ai.py crime.py economy.py farming.py gambling.py lab.py progression.py quick.py sesh.py social.py tasks.py world_modes.py\n",
)
