import random
import time

import discord
from discord.ext import commands

from economy_integrity import require_positive_amount
from persistence_context import GuildContextRequired, require_guild_id
from utils import _xp_needed_for_level
from world_modes import WorldModeDenied, require_multiplayer, resolve_game_scope


SUPPORT_CHANNEL_ID = 1447777409259671732
SUPPORT_SERVICES = {
    302050872383242240: "DISBOARD",
    678211574183362571: "D-Invites",
    1222548162741538938: "Discadia",
    189995110344425472: "Top.gg",
}
SUPPORT_COOLDOWN_SECONDS = {
    "DISBOARD": 7200,
    "D-Invites": 7200,
    "Discadia": 7200,
    "Top.gg": 43200,
}
SUPPORT_REWARD_XP = 1000


def get_crews(world: dict) -> dict:
    crews = world.get("crews")
    if not isinstance(crews, dict):
        crews = {}
        world["crews"] = crews
    return crews


class Social(commands.Cog):
    """Guild-scoped profile, crew, district, and support-reward commands."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    @commands.hybrid_command(name="profile", aliases=["me", "stats"])
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

    @commands.group(invoke_without_command=True, aliases=["c"])
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

    @crew.command(name="create")
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

    @crew.command(name="join")
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

    @crew.command(name="info")
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
        owner_label = owner.mention if owner else f"User {owner_id}"
        embed = discord.Embed(title=f"🧢 {crew.get('name', 'Unknown Crew')}", color=0x2ECC71)
        embed.description = f"**World:** {scope.emoji} {scope.label}"
        embed.add_field(name="ID", value=f"`{resolved_id}`", inline=True)
        embed.add_field(name="Owner", value=owner_label, inline=True)
        embed.add_field(name="Members", value=str(len(member_ids)), inline=True)
        embed.add_field(name="Bank", value=f"${max(0, int(crew.get('bank', 0))):,}", inline=True)
        embed.add_field(name="Level", value=str(max(1, int(crew.get('level', 1)))), inline=True)
        await ctx.send(embed=embed)

    @crew.command(name="deposit")
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

    @crew.command(name="war")
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

    @commands.command(name="district")
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

    @commands.Cog.listener()
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


async def setup(bot):
    await bot.add_cog(Social(bot))
