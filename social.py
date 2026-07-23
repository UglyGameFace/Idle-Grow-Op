import asyncio
import random
import re
import time
from collections import deque

import discord
from discord.ext import commands

from utils import (
    QUEST_TEMPLATES,
    SESSION_MEDIA,
    SESH_COLORS,
    SESH_MESSAGES,
    STONER_ROLE_ID,
    STONER_ROLE_NAME,
    STREAK_BONUSES,
    _env_int,
    _env_str,
    _xp_needed_for_level,
    add_quest_progress,
    check_achievements,
    db_manager,
    jail_guard,
)

# ==========================================================
# ⚙️ SESH CONFIGURATION & STATE
# ==========================================================
_ACTIVE_SESHES = {}
_VC_TO_SESSION = {}

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

# ==========================================================
# 🤝 SUPPORT/VOTE CONFIGURATION
# ==========================================================
SUPPORT_CHANNEL_ID = 1447777409259671732
SUPPORT_SERVICES = {
    302050872383242240: "DISBOARD",
    678211574183362571: "D-Invites",
    1222548162741538938: "Discadia",
    189995110344425472: "Top.gg",
}
SUPPORT_COOLDOWN_SECONDS = {"DISBOARD": 7200, "Top.gg": 43200}
SUPPORT_REWARD_XP = 1000


def get_crews():
    world = db_manager.world_state
    crews = world.get("crews")
    if not isinstance(crews, dict):
        crews = {}
        world["crews"] = crews
    return crews


def _sanitize_crew(crew):
    crew.setdefault("members", [])
    crew.setdefault("bank", 0)
    return crew


class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="profile", aliases=["me", "stats"])
    async def profile(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        user = self.bot.db.get_user(target.id)
        lvl = int(user.get("level", 1))
        xp = int(user.get("xp", 0))
        needed = _xp_needed_for_level(lvl)
        pct = min(100, int((xp / needed) * 100))
        filled = int(pct / 10)
        prog_bar = "🟦" * filled + "⬜" * (10 - filled)
        crew_name = "None"
        if user.get("crew_id"):
            crew = get_crews().get(str(user["crew_id"]))
            if crew:
                crew_name = crew.get("name", "Unknown")
        stats = user.get("stats", {})
        embed = discord.Embed(title=f"👤 {target.display_name}", color=target.color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="⭐ Level", value=f"**{lvl}**", inline=True)
        embed.add_field(name="✨ XP", value=f"{xp} / {needed}\n{prog_bar}", inline=True)
        embed.add_field(name="🧢 Crew", value=crew_name, inline=True)
        embed.add_field(
            name="💰 Wealth",
            value=f"Clean: **${user.get('grams', 0):,}**\nDirty: **${user.get('dirty_cash', 0):,}**",
            inline=False,
        )
        stat_text = (
            f"🌿 Harvested: {stats.get('harvested', 0)}\n"
            f"🔫 Heists Won: {stats.get('heists_won', 0)}\n"
            f"😈 Robberies: {stats.get('steals', 0)}\n"
            f"🔥 Highest Heat: {stats.get('max_heat', 0)}%"
        )
        embed.add_field(name="📊 Career Stats", value=stat_text, inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="daily")
    async def daily(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)
        now = time.time()
        last = float(user.get("last_daily", 0))
        if now - last < 79200:
            rem = int(79200 - (now - last))
            h, m = divmod(rem // 60, 60)
            return await ctx.send(f"⏳ **Wait:** {h}h {m}m until next daily.")
        streak = int(user.get("daily_streak", 0))
        if now - last > 172800:
            streak = 0
            msg_streak = "💔 Streak lost!"
        else:
            streak += 1
            msg_streak = f"🔥 Streak: {streak}"
        base = 500 + (int(user.get("level", 1)) * 50)
        mult = 1.0
        for day_req in sorted(STREAK_BONUSES.keys(), reverse=True):
            if streak >= day_req:
                mult = STREAK_BONUSES[day_req]["mult"]
                break
        total = int(base * mult)
        user["grams"] = int(user.get("grams", 0) + total)
        user["last_daily"] = now
        user["daily_streak"] = streak
        await self.bot.db.save()
        await ctx.send(f"☀️ **Daily Collected!**\n💰 **+${total:,}**\n{msg_streak}")

    @commands.group(invoke_without_command=True, aliases=["c"])
    async def crew(self, ctx):
        await ctx.send(
            "ℹ️ **Crew Commands:**\n`!crew create <name>`\n`!crew join <id>`\n"
            "`!crew info`\n`!crew deposit <amount>`\n`!crew war` (Turf War)\n"
            "`!district` (Check control)"
        )

    @crew.command(name="create")
    async def crew_create(self, ctx, *, name: str):
        user = self.bot.db.get_user(ctx.author.id)
        if user.get("crew_id"):
            return await ctx.send("❌ Already in a crew.")
        if user.get("grams", 0) < 50000:
            return await ctx.send("💸 Cost: $50,000.")
        crews = get_crews()
        cid = str(random.randint(10000, 99999))
        crews[cid] = {
            "id": cid,
            "name": name,
            "owner_id": ctx.author.id,
            "members": [ctx.author.id],
            "bank": 0,
            "level": 1,
        }
        user["grams"] -= 50000
        user["crew_id"] = cid
        await self.bot.db.save()
        await ctx.send(f"✅ **Crew Created!** ID: `{cid}`")

    @crew.command(name="join")
    async def crew_join(self, ctx, crew_id: str):
        user = self.bot.db.get_user(ctx.author.id)
        if user.get("crew_id"):
            return await ctx.send("❌ Leave current crew first.")
        crew = get_crews().get(crew_id)
        if not crew:
            return await ctx.send("❌ Crew not found.")
        crew["members"].append(ctx.author.id)
        user["crew_id"] = crew_id
        await self.bot.db.save()
        await ctx.send(f"✅ Joined **{crew['name']}**!")

    @crew.command(name="deposit")
    async def crew_deposit(self, ctx, amount: int):
        user = self.bot.db.get_user(ctx.author.id)
        cid = user.get("crew_id")
        if not cid:
            return await ctx.send("❌ No crew.")
        if user.get("grams", 0) < amount:
            return await ctx.send("💸 Insufficient funds.")
        user["grams"] -= amount
        crews = get_crews()
        crews[cid]["bank"] = crews[cid].get("bank", 0) + amount
        await self.bot.db.save()
        await ctx.send(f"🏦 Deposited ${amount:,}.")

    @crew.command(name="war")
    @commands.cooldown(1, 3600, commands.BucketType.guild)
    async def crew_war(self, ctx):
        user = self.bot.db.get_user(ctx.author.id)
        cid = user.get("crew_id")
        if not cid:
            return await ctx.send("❌ You need a crew.")
        crews = get_crews()
        atk = crews[cid]
        world = self.bot.db.world_state
        district = world.setdefault("district", {})
        current_owner = district.get("owner_crew_id")
        now = time.time()
        if not current_owner or now >= district.get("expires_at", 0):
            district.update(
                {
                    "owner_crew_id": cid,
                    "owner_name": atk["name"],
                    "multiplier": 1.10,
                    "expires_at": now + 86400,
                }
            )
            await self.bot.db.save()
            return await ctx.send(f"🔥 **{atk['name']}** claimed the empty district!")
        if current_owner == cid:
            return await ctx.send("🏙️ You already own the block.")
        def_crew = crews.get(current_owner)
        if not def_crew:
            return await ctx.send("❌ Error: Defending crew data missing.")
        atk_score = len(atk["members"]) * random.uniform(0.8, 1.2)
        def_score = len(def_crew["members"]) * random.uniform(0.8, 1.2)
        if atk_score > def_score:
            district.update(
                {
                    "owner_crew_id": cid,
                    "owner_name": atk["name"],
                    "multiplier": 1.10,
                    "expires_at": now + 86400,
                }
            )
            await self.bot.db.save()
            await ctx.send(f"💥 **WAR!** {atk['name']} defeated {def_crew['name']} and took the district!")
        else:
            await ctx.send(f"🛡️ **Failed.** {def_crew['name']} held the district.")

    @commands.command(name="district")
    async def district(self, ctx):
        district = self.bot.db.world_state.get("district", {})
        owner = district.get("owner_name", "None")
        mult = int((district.get("multiplier", 1.0) - 1) * 100)
        rem = max(0, int((district.get("expires_at", 0) - time.time()) / 60))
        embed = discord.Embed(title="🏙️ District Control", color=0xE67E22)
        embed.description = f"**Owner:** {owner}\n**Bonus:** +{mult}% Sell Value\n**Expires:** {rem} mins"
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
        target = ctx.message.mentions[0] if ctx.message.mentions else None
        media_pool = SESSION_MEDIA.get(kind, SESSION_MEDIA["SESH"])
        gif = random.choice(media_pool)
        vc = None
        created_private = False
        if target:
            vc = await self._create_private_vc(guild, host, target)
            created_private = True
        elif host.voice:
            vc = host.voice.channel
        title = f"🔥 {kind} DASHBOARD"
        desc = f"**Activity:** {args or 'Chilling'}\n> *{random.choice(SESH_QUOTES)}*"
        embed = discord.Embed(title=title, description=desc, color=SESH_COLORS.get(kind, 0x2ECC71))
        embed.set_image(url=gif)
        if vc:
            embed.add_field(name="🔊 Room", value=vc.mention)
            if created_private:
                embed.set_footer(text="Private Room Created! Click Join below.")
        view = SeshView(self.bot, host.id, target.id if target else None)
        msg = await ctx.send(embed=embed, view=view)
        _ACTIVE_SESHES[msg.id] = {
            "guild_id": guild.id,
            "host_id": host.id,
            "vc_id": vc.id if vc else None,
            "private": created_private,
            "expiry": time.time() + 600,
        }
        if created_private and vc:
            try:
                await host.move_to(vc)
                if target:
                    await target.move_to(vc)
            except Exception:
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
        name = f"private-sesh-{host.display_name[:5]}"
        return await guild.create_voice_channel(name=name, category=category, overwrites=overwrites)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and len(before.channel.members) == 0:
            if before.channel.name.startswith("private-sesh-"):
                try:
                    await before.channel.delete()
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id != SUPPORT_CHANNEL_ID:
            return
        if message.author.bot or message.author.id in SUPPORT_SERVICES:
            content = message.content.lower() + " ".join(
                embed.description.lower()
                for embed in message.embeds
                if embed.description
            )
            if "bump done" in content or "voted" in content:
                user = message.mentions[0] if message.mentions else None
                if not user:
                    return
                user_data = self.bot.db.get_user(user.id)
                user_data["xp"] = int(user_data.get("xp", 0)) + SUPPORT_REWARD_XP
                await self.bot.db.save()
                await message.channel.send(
                    f"✅ **{user.mention}** received {SUPPORT_REWARD_XP} XP for voting!"
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
        vc = interaction.guild.get_channel(session["vc_id"])
        if vc:
            await vc.set_permissions(interaction.user, connect=True, view_channel=True)
            await interaction.response.send_message(f"✅ Access granted to {vc.mention}", ephemeral=True)

    @discord.ui.button(label="Puff & Pass", style=discord.ButtonStyle.primary, emoji="🔥")
    async def puff_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = db_manager.get_user(interaction.user.id)
        xp = random.randint(15, 30)
        user["xp"] = int(user.get("xp", 0)) + xp
        await db_manager.save()
        quote = random.choice(SESH_QUOTES)
        await interaction.response.send_message(f"😮‍💨 **{quote}** (+{xp} XP)", ephemeral=True)

    @discord.ui.button(label="End Sesh", style=discord.ButtonStyle.danger)
    async def end_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            return
        session = _ACTIVE_SESHES.get(interaction.message.id)
        if session and session.get("vc_id"):
            vc = interaction.guild.get_channel(session["vc_id"])
            if vc:
                await vc.delete()
        await interaction.message.delete()


async def setup(bot):
    await bot.add_cog(Social(bot))
