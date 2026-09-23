import random
import time

import discord
from discord.ext import commands

from economy_integrity import require_positive_amount
from persistence_context import GuildContextRequired, require_guild_id
from progression_core import add_progress, check_achievements, credit_xp, xp_needed_for_level
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
        needed = max(1, int(xp_needed_for_level(level)))
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

    @commands.hybrid_group(invoke_without_command=True, aliases=["c"])
    async def crew(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        await ctx.send(
            "ℹ️ **Crew Commands:**\n"
            "`/crew create name:<name>`\n"
            "`/crew join crew_id:<id>`\n"
            "`/crew leave`\n"
            "`/crew info`\n"
            "`/crew deposit amount:<amount>`\n"
            "`/crew war` (Turf War)\n"
            "`/district` (Check control)"
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

        create_error = None
        crew_id = None
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            if user.get("crew_id"):
                create_error = "❌ Already in a crew."
            else:
                balance = max(0, int(user.get("grams", 0)))
                if balance < 50000:
                    create_error = "💸 Cost: $50,000."
                else:
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
        if create_error:
            return await ctx.send(create_error)
        await ctx.send(f"✅ **Crew Created!** ID: `{crew_id}`")

    @crew.command(name="join")
    async def crew_join(self, ctx, crew_id: str):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        join_error = None
        crew = None
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            if user.get("crew_id"):
                join_error = "❌ Leave your current crew first."
            else:
                crew = get_crews(world).get(str(crew_id))
                if not crew:
                    join_error = "❌ Crew not found."
                else:
                    members = crew.setdefault("members", [])
                    if ctx.author.id not in members:
                        members.append(ctx.author.id)
                    user["crew_id"] = str(crew_id)
                    self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                    self.bot.db.mark_world_dirty(scope.scope_id)
        if join_error:
            return await ctx.send(join_error)
        await ctx.send(f"✅ Joined **{crew['name']}**!")

    @crew.command(name="leave")
    async def crew_leave(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "crew")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))

        leave_error = None
        leave_message = None
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            crew_id = user.get("crew_id")
            if not crew_id:
                leave_error = "❌ You are not in a crew."
            else:
                crews = get_crews(world)
                crew = crews.get(str(crew_id))
                if not crew:
                    user["crew_id"] = None
                    self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                    leave_message = "✅ Cleared stale crew membership. You can join another crew now."
                else:
                    member_ids = []
                    for value in crew.get("members", []):
                        try:
                            member_id = int(value)
                        except (TypeError, ValueError):
                            continue
                        if member_id not in member_ids:
                            member_ids.append(member_id)

                    remaining = [member_id for member_id in member_ids if member_id != ctx.author.id]
                    owner_id = int(crew.get("owner_id", 0) or 0)
                    user["crew_id"] = None

                    if owner_id == ctx.author.id and remaining:
                        new_owner_id = remaining[0]
                        crew["owner_id"] = new_owner_id
                        crew["members"] = remaining
                        leave_message = (
                            f"✅ Left **{crew.get('name', 'the crew')}**. "
                            f"Ownership transferred to <@{new_owner_id}>."
                        )
                    elif remaining:
                        crew["members"] = remaining
                        leave_message = f"✅ Left **{crew.get('name', 'the crew')}**."
                    else:
                        bank = max(0, int(crew.get("bank", 0) or 0))
                        user["grams"] = max(0, int(user.get("grams", 0))) + bank
                        crews.pop(str(crew_id), None)

                        district = world.get("district")
                        if (
                            isinstance(district, dict)
                            and str(district.get("owner_crew_id")) == str(crew_id)
                        ):
                            district.update(
                                {
                                    "owner_crew_id": None,
                                    "owner_name": None,
                                    "multiplier": 1.0,
                                    "expires_at": 0,
                                }
                            )
                        leave_message = (
                            f"✅ Disbanded **{crew.get('name', 'the crew')}**. "
                            f"Returned **${bank:,}** from the crew bank."
                        )

                    self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                    self.bot.db.mark_world_dirty(scope.scope_id)

        if leave_error:
            return await ctx.send(leave_error)
        await ctx.send(leave_message)

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

        deposit_error = None
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            crew_id = user.get("crew_id")
            if not crew_id:
                deposit_error = "❌ No crew."
            else:
                crew = get_crews(world).get(str(crew_id))
                if not crew:
                    deposit_error = "❌ Crew data missing."
                else:
                    balance = max(0, int(user.get("grams", 0)))
                    if balance < deposit:
                        deposit_error = "💸 Insufficient funds."
                    else:
                        user["grams"] = balance - deposit
                        crew["bank"] = max(0, int(crew.get("bank", 0))) + deposit
                        add_progress(user, "crew_deposit_cash", deposit, user_id=ctx.author.id)
                        check_achievements(user)
                        self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
                        self.bot.db.mark_world_dirty(scope.scope_id)
        if deposit_error:
            return await ctx.send(deposit_error)
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
        war_error = None
        immediate_message = None
        attacker_won = None
        async with self.bot.db.lock:
            user = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            world = await self.bot.db.get_world(scope.scope_id)
            crew_id = user.get("crew_id")
            if not crew_id:
                war_error = "❌ You need a crew."
            else:
                crews = get_crews(world)
                attacker = crews.get(str(crew_id))
                if not attacker:
                    war_error = "❌ Crew data missing."
                else:
                    now = time.time()
                    cooldowns = attacker.setdefault("cooldowns", {})
                    last_war = float(cooldowns.get("war", 0) or 0)
                    remaining = int(last_war + 3600 - now)
                    if remaining > 0:
                        war_error = f"⏳ Crew turf-war cooldown: **{remaining // 60 + 1}m**"
                    else:
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
                            immediate_message = f"🔥 **{attacker['name']}** claimed the empty district!"
                        elif str(current_owner) == str(crew_id):
                            war_error = "🏙️ You already own the block."
                        else:
                            defender = crews.get(str(current_owner))
                            if not defender:
                                war_error = "❌ Defending crew data is missing."
                            else:
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

        if war_error:
            return await ctx.send(war_error)
        if immediate_message:
            return await ctx.send(immediate_message)
        if attacker_won:
            await ctx.send(
                f"💥 **WAR!** {attacker['name']} defeated {defender['name']} and took the district!"
            )
        else:
            await ctx.send(f"🛡️ **Failed.** {defender['name']} held the district.")

    @commands.hybrid_command(name="district")
    async def district(self, ctx):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "district")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        world = await self.bot.db.get_world(scope.scope_id)
        district = world.get("district", {})
        now = time.time()
        active = bool(
            district.get("owner_crew_id")
            and now < float(district.get("expires_at", 0) or 0)
        )
        owner = district.get("owner_name") if active else "None"
        multiplier = (
            max(1.0, float(district.get("multiplier", 1.0)))
            if active
            else 1.0
        )
        bonus = int((multiplier - 1) * 100)
        remaining = (
            max(0, int((float(district.get("expires_at", 0)) - now) / 60))
            if active
            else 0
        )
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
            credit_xp(user_data, SUPPORT_REWARD_XP)
            check_achievements(user_data)
            cooldowns[service_name] = now
            self.bot.db.mark_profile_dirty(reward_scope.scope_id, rewarded_user.id)

        await message.channel.send(
            f"✅ **{rewarded_user.mention}** received {SUPPORT_REWARD_XP} XP for {service_name}!"
        )


async def setup(bot):
    await bot.add_cog(Social(bot))
