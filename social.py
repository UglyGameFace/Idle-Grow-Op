import random
import time

import discord
from discord.ext import commands

from economy_integrity import require_positive_amount
from utils import (
    SESSION_MEDIA,
    SESH_COLORS,
    STONER_ROLE_NAME,
    STREAK_BONUSES,
    _xp_needed_for_level,
    db_manager,
)

_ACTIVE_SESHES = {}

DEFAULT_ACTIVITY_IDS = {
    "MOVIE": 880218394199220334,
    "KARAOKE": 755600276941176913,
}

SESH_QUOTES = [
    "Pass it to the left.",
    "Say less.",
    "Straight gas no brakes.",
    "Don't panic, it's organic.",
    "Certified loud.",
    "Stay lifted.",
    "Good vibes only.",
    "Rolling up another one...",
    "We geekin.",
]

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


def get_crews():
    world = db_manager.world_state
    crews = world.get("crews")
    if not isinstance(crews, dict):
        crews = {}
        world["crews"] = crews
    return crews


class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="profile", aliases=["me", "stats"])
    async def profile(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        user = self.bot.db.get_user(target.id)
        level = max(1, int(user.get("level", 1)))
        xp = max(0, int(user.get("xp", 0)))
        needed = _xp_needed_for_level(level)
        percent = min(100, int((xp / needed) * 100))
        filled = int(percent / 10)
        progress = "🟦" * filled + "⬜" * (10 - filled)

        crew_name = "None"
        crew_id = user.get("crew_id")
        if crew_id:
            crew = get_crews().get(str(crew_id))
            if crew:
                crew_name = crew.get("name", "Unknown")

        stats = user.get("stats", {})
        embed = discord.Embed(title=f"👤 {target.display_name}", color=target.color)
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

    @commands.hybrid_command(name="daily")
    async def daily(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)

        async with self.bot.db.lock:
            now = time.time()
            last = max(0.0, float(user.get("last_daily", 0)))
            elapsed = now - last
            if elapsed < 79200:
                remaining = int(79200 - elapsed)
                hours, minutes = divmod(remaining // 60, 60)
                return await ctx.send(f"⏳ **Wait:** {hours}h {minutes}m until next daily.")

            previous_streak = max(0, int(user.get("daily_streak", 0)))
            if last == 0 or elapsed > 172800:
                streak = 1
                streak_message = "🔥 Streak: 1"
            else:
                streak = previous_streak + 1
                streak_message = f"🔥 Streak: {streak}"

            base_reward = max(0, 500 + max(1, int(user.get("level", 1))) * 50)
            multiplier = 1.0
            for required_days in sorted(STREAK_BONUSES, reverse=True):
                if streak >= required_days:
                    multiplier = max(0.0, float(STREAK_BONUSES[required_days]["mult"]))
                    break

            reward = max(0, int(base_reward * multiplier))
            user["grams"] = max(0, int(user.get("grams", 0))) + reward
            user["last_daily"] = now
            user["daily_streak"] = streak
            stats = user.setdefault("stats", {})
            stats["total_earned"] = max(0, int(stats.get("total_earned", 0))) + reward
            await self.bot.db.save()

        await ctx.send(f"☀️ **Daily Collected!**\n💰 **+${reward:,}**\n{streak_message}")

    @commands.group(invoke_without_command=True, aliases=["c"])
    async def crew(self, ctx):
        await ctx.send(
            "ℹ️ **Crew Commands:**\n`!crew create <name>`\n`!crew join <id>`\n"
            "`!crew info`\n`!crew deposit <amount>`\n`!crew war` (Turf War)\n"
            "`!district` (Check control)"
        )

    @crew.command(name="create")
    async def crew_create(self, ctx, *, name: str):
        clean_name = name.strip()
        if not clean_name:
            return await ctx.send("❌ Crew name cannot be empty.")
        if len(clean_name) > 50:
            return await ctx.send("❌ Crew name is too long.")

        user = self.bot.db.get_user(ctx.author.id)
        async with self.bot.db.lock:
            if user.get("crew_id"):
                return await ctx.send("❌ Already in a crew.")
            balance = max(0, int(user.get("grams", 0)))
            if balance < 50000:
                return await ctx.send("💸 Cost: $50,000.")

            crews = get_crews()
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
            }
            user["grams"] = balance - 50000
            user["crew_id"] = crew_id
            await self.bot.db.save()

        await ctx.send(f"✅ **Crew Created!** ID: `{crew_id}`")

    @crew.command(name="join")
    async def crew_join(self, ctx, crew_id: str):
        user = self.bot.db.get_user(ctx.author.id)
        async with self.bot.db.lock:
            if user.get("crew_id"):
                return await ctx.send("❌ Leave current crew first.")
            crew = get_crews().get(crew_id)
            if not crew:
                return await ctx.send("❌ Crew not found.")
            members = crew.setdefault("members", [])
            if ctx.author.id not in members:
                members.append(ctx.author.id)
            user["crew_id"] = crew_id
            await self.bot.db.save()

        await ctx.send(f"✅ Joined **{crew['name']}**!")

    @crew.command(name="deposit")
    async def crew_deposit(self, ctx, amount: int):
        try:
            deposit = require_positive_amount(amount)
        except ValueError:
            return await ctx.send("❌ Deposit must be a positive whole number.")

        user = self.bot.db.get_user(ctx.author.id)
        async with self.bot.db.lock:
            crew_id = user.get("crew_id")
            if not crew_id:
                return await ctx.send("❌ No crew.")
            crew = get_crews().get(str(crew_id))
            if not crew:
                return await ctx.send("❌ Crew data missing.")
            balance = max(0, int(user.get("grams", 0)))
            if balance < deposit:
                return await ctx.send("💸 Insufficient funds.")
            user["grams"] = balance - deposit
            crew["bank"] = max(0, int(crew.get("bank", 0))) + deposit
            await self.bot.db.save()

        await ctx.send(f"🏦 Deposited ${deposit:,}.")

    @crew.command(name="war")
    @commands.cooldown(1, 3600, commands.BucketType.guild)
    async def crew_war(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")

        async with self.bot.db.lock:
            crews = get_crews()
            attacker = crews.get(str(crew_id))
            if not attacker:
                return await ctx.send("❌ Crew data missing.")
            district = self.bot.db.world_state.setdefault("district", {})
            current_owner = district.get("owner_crew_id")
            now = time.time()

            if not current_owner or now >= float(district.get("expires_at", 0)):
                district.update(
                    {
                        "owner_crew_id": str(crew_id),
                        "owner_name": attacker["name"],
                        "multiplier": 1.10,
                        "expires_at": now + 86400,
                    }
                )
                await self.bot.db.save()
                return await ctx.send(f"🔥 **{attacker['name']}** claimed the empty district!")
            if str(current_owner) == str(crew_id):
                return await ctx.send("🏙️ You already own the block.")

            defender = crews.get(str(current_owner))
            if not defender:
                return await ctx.send("❌ Error: Defending crew data missing.")
            attacker_score = len(attacker.get("members", [])) * random.uniform(0.8, 1.2)
            defender_score = len(defender.get("members", [])) * random.uniform(0.8, 1.2)
            attacker_won = attacker_score > defender_score
            if attacker_won:
                district.update(
                    {
                        "owner_crew_id": str(crew_id),
                        "owner_name": attacker["name"],
                        "multiplier": 1.10,
                        "expires_at": now + 86400,
                    }
                )
                await self.bot.db.save()

        if attacker_won:
            await ctx.send(f"💥 **WAR!** {attacker['name']} defeated {defender['name']} and took the district!")
        else:
            await ctx.send(f"🛡️ **Failed.** {defender['name']} held the district.")

    @commands.command(name="district")
    async def district(self, ctx):
        district = self.bot.db.world_state.get("district", {})
        owner = district.get("owner_name", "None")
        multiplier = max(1.0, float(district.get("multiplier", 1.0)))
        bonus = int((multiplier - 1) * 100)
        remaining = max(0, int((float(district.get("expires_at", 0)) - time.time()) / 60))
        embed = discord.Embed(title="🏙️ District Control", color=0xE67E22)
        embed.description = f"**Owner:** {owner}\n**Bonus:** +{bonus}% Sell Value\n**Expires:** {remaining} mins"
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sesh")
    async def sesh(self, ctx, *, args: str = ""):
        await self._start_sesh_flow(ctx, args, "SESH")

    @commands.hybrid_command(name="movie")
    async def movie(self, ctx, *, args: str = ""):
        await self._start_sesh_flow(ctx, args, "MOVIE")

    async def _start_sesh_flow(self, ctx, args, kind):
        guild = ctx.guild
        host = ctx.author
        target = ctx.message.mentions[0] if ctx.message and ctx.message.mentions else None
        media_pool = SESSION_MEDIA.get(kind) or SESSION_MEDIA.get("SESH", [])
        gif = random.choice(media_pool) if media_pool else None
        voice_channel = None
        created_private = False

        if target:
            voice_channel = await self._create_private_vc(guild, host, target)
            created_private = True
        elif host.voice:
            voice_channel = host.voice.channel

        embed = discord.Embed(
            title=f"🔥 {kind} DASHBOARD",
            description=f"**Activity:** {args or 'Chilling'}\n> *{random.choice(SESH_QUOTES)}*",
            color=SESH_COLORS.get(kind, 0x2ECC71),
        )
        if gif:
            embed.set_image(url=gif)
        if voice_channel:
            embed.add_field(name="🔊 Room", value=voice_channel.mention)
            if created_private:
                embed.set_footer(text="Private Room Created! Click Join below.")

        view = SeshView(self.bot, host.id, target.id if target else None)
        message = await ctx.send(embed=embed, view=view)
        _ACTIVE_SESHES[message.id] = {
            "guild_id": guild.id,
            "host_id": host.id,
            "vc_id": voice_channel.id if voice_channel else None,
            "private": created_private,
            "expiry": time.time() + 600,
        }

        if created_private and voice_channel:
            try:
                await host.move_to(voice_channel)
                if target:
                    await target.move_to(voice_channel)
            except discord.HTTPException:
                pass

    async def _create_private_vc(self, guild, host, target):
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            host: discord.PermissionOverwrite(view_channel=True, connect=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True),
        }
        if target:
            overwrites[target] = discord.PermissionOverwrite(view_channel=True, connect=True)
        category = host.voice.channel.category if host.voice else None
        return await guild.create_voice_channel(
            name=f"private-sesh-{host.display_name[:5]}",
            category=category,
            overwrites=overwrites,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and not before.channel.members and before.channel.name.startswith("private-sesh-"):
            try:
                await before.channel.delete()
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id != SUPPORT_CHANNEL_ID:
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

        async with self.bot.db.lock:
            user_data = self.bot.db.get_user(rewarded_user.id)
            cooldowns = user_data.setdefault("support_cooldowns", {})
            now = time.time()
            last_reward = max(0.0, float(cooldowns.get(service_name, 0)))
            cooldown = max(0, int(SUPPORT_COOLDOWN_SECONDS.get(service_name, 7200)))
            if now - last_reward < cooldown:
                return
            user_data["xp"] = max(0, int(user_data.get("xp", 0))) + SUPPORT_REWARD_XP
            cooldowns[service_name] = now
            await self.bot.db.save()

        await message.channel.send(
            f"✅ **{rewarded_user.mention}** received {SUPPORT_REWARD_XP} XP for {service_name}!"
        )


class SeshView(discord.ui.View):
    def __init__(self, bot, host_id, target_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.host_id = host_id

    @discord.ui.button(label="Join VC", style=discord.ButtonStyle.success, emoji="🔊")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _ACTIVE_SESHES.get(interaction.message.id)
        if not session or not session.get("vc_id"):
            return await interaction.response.send_message("❌ No VC attached.", ephemeral=True)
        voice_channel = interaction.guild.get_channel(session["vc_id"])
        if voice_channel:
            await voice_channel.set_permissions(interaction.user, connect=True, view_channel=True)
            await interaction.response.send_message(
                f"✅ Access granted to {voice_channel.mention}",
                ephemeral=True,
            )

    @discord.ui.button(label="Puff & Pass", style=discord.ButtonStyle.primary, emoji="🔥")
    async def puff_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_manager.lock:
            user = db_manager.get_user(interaction.user.id)
            xp = random.randint(15, 30)
            user["xp"] = max(0, int(user.get("xp", 0))) + xp
            await db_manager.save()
        await interaction.response.send_message(
            f"😮‍💨 **{random.choice(SESH_QUOTES)}** (+{xp} XP)",
            ephemeral=True,
        )

    @discord.ui.button(label="End Sesh", style=discord.ButtonStyle.danger)
    async def end_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            return await interaction.response.send_message("❌ Only the host can end this sesh.", ephemeral=True)
        session = _ACTIVE_SESHES.pop(interaction.message.id, None)
        if session and session.get("vc_id"):
            voice_channel = interaction.guild.get_channel(session["vc_id"])
            if voice_channel:
                await voice_channel.delete()
        await interaction.message.delete()


async def setup(bot):
    await bot.add_cog(Social(bot))
